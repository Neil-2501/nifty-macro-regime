"""Momentum-basket bake-off V4 — attack individual-name blowups.

V3 diagnosis: median stock in 2018-19 window GAINED 33%. The DD came from
3-5 specific names blowing up 30-75% (ALANKIT -75%, DCMSHRIRAM -29%, etc).
Equal-weight × 3.33% × handful of -30 to -75% names = the drag.

V4 stacks 3 constructions on top of the V3 winner (eq_N0_U200, hard_rules, buf=45):
  A. baseline (V3 winner)
  B. A + pledging filter (drop heavily-pledged names) + vol cap 40% (drop blowups)
  C. B + Novy-Marx: rank by 0.7 × z(momentum) + 0.3 × z(F_score)
     F_score NaN → 25th percentile fallback (conservative "unknown = mediocre")

Fixed: U200 @ 15bps, buf=45, N=30, no persistence gate.
Same identity checks as V2/V3.

Also prints per-name attribution for the 2018-19 window so we can SEE
which specific names got excluded by each filter and how it moved the DD.
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backtest_defensive_rotation as brd
import defensive_sleeve_v6 as v6
import strategy as prod

OUT_DIR = os.path.join(REPO_ROOT, "data", "momentum_basket_bakeoff_v4")
os.makedirs(OUT_DIR, exist_ok=True)

MOM30_COST_BPS = 6
BASKET_COST_BPS = 15                       # U200 realistic
DEFENSIVE_COST_BPS_PER_SIDE = 30
STCG_PRE, STCG_POST = 0.15, 0.20
STCG_CHANGE_DATE = pd.Timestamp('2024-07-23')
TAX_RATE = 0.15

END_FULL  = pd.Timestamp('2026-05-11')
IS_END    = pd.Timestamp('2016-12-31')
OOS_START = pd.Timestamp('2017-01-01')

DEFENSIVE_N = 40
DEFENSIVE_ALLOC = 0.5

N_HOLD = 30
DE_MAX = 2.0
BUF    = 45
UNIVERSE = 200

VOL_CAP = 0.40                             # cap ann vol per name at 40%

ETF_PATTERNS = ['GOLD','SILVER','SILV','BEES','NIFTY','BANKN','LIQUID','NAV',
                'IETF','NIFTYIETF','GOLDIETF','SETFGOLD','JGOLD','MAFANG',
                'CPSE','PSU','MOM100']


def _is_etf(sym): return any(p in str(sym).upper() for p in ETF_PATTERNS)


# --- Config 7 ---
def run_cfg7(raw, rotate_stress=True, use_g10_gate=True, use_momentum_gold=True):
    combiner = prod.make_combiner(rotate_stress=rotate_stress, rotate_panic=False,
                                    use_momentum_gold=use_momentum_gold,
                                    gold_gate_external=use_g10_gate,
                                    slow_stress_lock_days=5, panic_short_dd_threshold=0.15)
    strat = prod.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                                    long_target="NIFTYMOM30", long_cost_bps=MOM30_COST_BPS,
                                    enable_v2=True, v2_dd_threshold=0.15, v2_days=60)
    return strat.run(raw).loc['2008-04-01':'2026-06-15']


# --- Fund lookup ---
def build_fund_lookup(fund_wide):
    return {int(fy): grp.set_index('symbol') for fy, grp in fund_wide.groupby('fiscal_year')}


def passes_hard_rules(sym, rd, fund_by_fy):
    fy = brd.latest_fy_at_date(rd)
    fund_year = fund_by_fy.get(int(fy))
    if fund_year is None or sym not in fund_year.index:
        return False
    return brd.check_hard_rules(fund_year.loc[sym].to_dict(), cap_intensive_de_max=DE_MAX)


# --- Quality lookup (F_score + pledging per rebalance) ---
def build_quality_lookup(quality_scored):
    out = {}
    for rd, grp in quality_scored.groupby('rebalance_date'):
        out[pd.Timestamp(rd)] = grp.set_index('symbol')
    return out


def get_pledging_ok(sym, rd, quality_by_rd) -> bool:
    """current_pledging_under_25 == True means pledging < 25% (OK to hold).
    If data missing → default TRUE (don't punish missing data on this filter)."""
    q = quality_by_rd.get(pd.Timestamp(rd))
    if q is None or sym not in q.index:
        return True
    val = q.loc[sym].get('current_pledging_under_25', True)
    return bool(val) if pd.notna(val) else True


def get_fscore(sym, rd, quality_by_rd):
    q = quality_by_rd.get(pd.Timestamp(rd))
    if q is None or sym not in q.index:
        return np.nan
    return q.loc[sym].get('F_score', np.nan)


# --- Basket construction (parametric) ---
def select_basket(scored, fund_wide, quality_by_rd, prices, nifty_close_series,
                    rebalance_dates,
                    use_pledging_filter: bool,
                    use_vol_cap: bool,
                    use_novy_marx: bool,
                    novy_marx_lambda: float = 0.3,
                    beta_vol_cache=None):
    """Universe: top-UNIVERSE liquid, non-ETF, hard_rules pass.
    Optional filters: pledging (drop pledged), vol cap (drop >VOL_CAP ann).
    Ranking: if use_novy_marx, combined = (1-λ)·z(momentum) + λ·z(F_score-with-fallback);
             else pure z(momentum).
    """
    fund_by_fy = build_fund_lookup(fund_wide)
    if beta_vol_cache is None:
        beta_vol_cache = {}
    baskets = {}
    prev_holdings = []
    excluded_log = []       # for diagnostic printouts

    for rd in rebalance_dates:
        rd_ts = pd.Timestamp(rd)
        sub = scored[scored['rebalance_date'] == rd_ts].copy()
        sub = sub[sub['universe_rank_turnover'] <= UNIVERSE]
        sub = sub[~sub['symbol'].map(_is_etf)]
        # Hard rules
        sub['hard_ok'] = [passes_hard_rules(s, rd_ts, fund_by_fy) for s in sub['symbol']]
        sub = sub[sub['hard_ok']].reset_index(drop=True)

        # Optional pledging filter
        if use_pledging_filter:
            sub['pledge_ok'] = [get_pledging_ok(s, rd_ts, quality_by_rd) for s in sub['symbol']]
            excluded_pledge = sub[~sub['pledge_ok']]['symbol'].tolist()
            sub = sub[sub['pledge_ok']].reset_index(drop=True)
        else:
            excluded_pledge = []

        # Optional vol cap
        if use_vol_cap:
            vol_ok = []
            excluded_vol = []
            for s in sub['symbol']:
                key = (s, rd_ts)
                if key in beta_vol_cache:
                    b, v = beta_vol_cache[key]
                else:
                    b, v = brd.compute_beta_vol(prices, s, rd_ts, nifty_close_series)
                    beta_vol_cache[key] = (b, v)
                if v is None or v > VOL_CAP:
                    vol_ok.append(False)
                    if v is not None:
                        excluded_vol.append((s, v))
                else:
                    vol_ok.append(True)
            sub['vol_ok'] = vol_ok
            excluded_vol_syms = sub[~sub['vol_ok']]['symbol'].tolist()
            sub = sub[sub['vol_ok']].reset_index(drop=True)
        else:
            excluded_vol_syms = []

        # Ranking
        sub['z_mom'] = (sub['composite_risk_adj'] - sub['composite_risk_adj'].mean()) / \
                          (sub['composite_risk_adj'].std() or 1)
        if use_novy_marx:
            sub['F_score_pt'] = [get_fscore(s, rd_ts, quality_by_rd) for s in sub['symbol']]
            # Fallback: names without F_score get the 25th percentile of names that DO have it
            fs_present = sub['F_score_pt'].dropna()
            if len(fs_present) >= 5:
                fallback = fs_present.quantile(0.25)
            else:
                fallback = 3.0                          # neutral-low default
            sub['F_score_use'] = sub['F_score_pt'].fillna(fallback)
            sub['z_qual'] = (sub['F_score_use'] - sub['F_score_use'].mean()) / \
                              (sub['F_score_use'].std() or 1)
            sub['combined_z'] = (1 - novy_marx_lambda) * sub['z_mom'] + novy_marx_lambda * sub['z_qual']
            sub = sub.sort_values('combined_z', ascending=False).reset_index(drop=True)
        else:
            sub = sub.sort_values('z_mom', ascending=False).reset_index(drop=True)

        # Buffered incumbent retention
        if len(sub) < N_HOLD:
            picks = sub['symbol'].tolist()
        else:
            elig_set = set(sub['symbol'].tolist())
            buffer_set = set(sub.head(BUF)['symbol'].tolist())
            top_N_names = sub.head(N_HOLD)['symbol'].tolist()
            held = [s for s in prev_holdings if s in elig_set and s in buffer_set]
            new_names = [s for s in top_N_names if s not in held]
            picks = (held + new_names)[:N_HOLD]

        w = {s: 1.0 / len(picks) for s in picks}
        baskets[rd_ts] = w
        prev_holdings = picks

        excluded_log.append({'rd': rd_ts, 'n_eligible_after_filters': len(sub),
                              'excluded_pledge': excluded_pledge, 'excluded_vol': excluded_vol_syms})

    return baskets, excluded_log


def compute_basket_daily_returns(baskets, prices_wide, date_index):
    rebalance_dates = sorted(baskets.keys())
    daily_ret = pd.Series(0.0, index=date_index)
    turnover_by_reb = {}
    all_symbols = set()
    for w in baskets.values(): all_symbols.update(w.keys())
    cols_all = [s for s in all_symbols if s in prices_wide.columns]
    all_ret = prices_wide[cols_all].pct_change().fillna(0)
    prev_w = pd.Series(dtype=float)
    for i, rd in enumerate(rebalance_dates):
        end = rebalance_dates[i+1] if i+1 < len(rebalance_dates) else date_index[-1] + pd.Timedelta(days=1)
        w = pd.Series(baskets[rd])
        all_syms = prev_w.index.union(w.index)
        pv = prev_w.reindex(all_syms).fillna(0)
        cv = w.reindex(all_syms).fillna(0)
        turnover_by_reb[rd] = float((pv - cv).abs().sum() / 2)
        prev_w = w
        period = (date_index > pd.Timestamp(rd)) & (date_index <= pd.Timestamp(end))
        if not period.any(): continue
        cols = [s for s in w.index if s in all_ret.columns]
        if not cols: continue
        weights = pd.Series({s: w[s] for s in cols})
        weights = weights / weights.sum()
        basket_r = all_ret.loc[period, cols] @ weights
        daily_ret.loc[period] = basket_r.values
    return daily_ret, turnover_by_reb


def build_swap_pretax(cfg7, raw, my_basket_daily_ret, turnover_by_reb, rebalance_dates, cost_bps):
    active = (cfg7['long_mom_default'] & ~cfg7['composition_swap_active']).astype(float)
    mom30_ret = raw['NIFTYMOM30'].reindex(cfg7.index).pct_change().fillna(0)
    mom30_pnl  = active.shift(1).fillna(0) * mom30_ret
    mom30_cost = active.diff().abs().fillna(0) * (MOM30_COST_BPS / 10_000)
    my_pnl     = active.shift(1).fillna(0) * my_basket_daily_ret.reindex(cfg7.index).fillna(0)
    my_ent_cost = active.diff().abs().fillna(0) * (cost_bps / 10_000)
    my_rebal_cost = pd.Series(0.0, index=cfg7.index)
    for rd, tvr in turnover_by_reb.items():
        rd = pd.Timestamp(rd)
        cand = cfg7.index[cfg7.index >= rd]
        if len(cand) == 0: continue
        day = cand[0]
        if active.loc[day] == 1.0:
            my_rebal_cost.loc[day] += 2 * tvr * (cost_bps / 10_000)
    return cfg7['strategy_return_pretax'] - (mom30_pnl - mom30_cost) + (my_pnl - my_ent_cost - my_rebal_cost), active


def apply_annual_tax(daily_returns, tax_rate=TAX_RATE):
    out = daily_returns.copy()
    annual = (1 + daily_returns).groupby(daily_returns.index.year).prod() - 1
    for y in annual.index:
        if annual[y] > 0:
            mask = (daily_returns.index.year == y)
            out.loc[mask] = daily_returns.loc[mask] * (1.0 - tax_rate)
    return out


def identify_latches(nifty_pos_series):
    is_flat = (nifty_pos_series == 0.0).values
    n = len(is_flat)
    latch_id = np.zeros(n, dtype=int); day_in_latch = np.zeros(n, dtype=int)
    cur_id, cur_day = 0, 0
    for i in range(n):
        if is_flat[i]:
            if i == 0 or not is_flat[i-1]:
                cur_id += 1; cur_day = 1
            else:
                cur_day += 1
            latch_id[i] = cur_id; day_in_latch[i] = cur_day
        else:
            cur_day = 0
    return latch_id, day_in_latch, is_flat


def apply_defensive_overlay(base, defensive_ret, latch_id, day_in_latch, is_flat,
                             N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC):
    ret = base.values.copy()
    b = defensive_ret.reindex(base.index).fillna(0).values
    active = is_flat & (day_in_latch > N)
    ret[active] = alloc * b[active] + (1 - alloc) * base.values[active]
    cps = DEFENSIVE_COST_BPS_PER_SIDE / 10_000
    dates = base.index
    for i in range(1, len(ret)):
        if active[i] and not active[i-1]:
            ret[i] -= alloc * cps
        elif not active[i] and active[i-1]:
            j = i - 1
            while j > 0 and active[j-1]: j -= 1
            cum = np.prod(1 + ret[j:i]) - 1
            gain = alloc * cum if cum > 0 else 0
            rate = STCG_POST if dates[i] >= STCG_CHANGE_DATE else STCG_PRE
            ret[i] -= alloc * cps + gain * rate
    return pd.Series(ret, index=base.index)


def perf(r):
    r = pd.Series(r).dropna()
    if r.empty: return {'CAGR': np.nan, 'AnnVol': np.nan, 'Sharpe': np.nan, 'MaxDD': np.nan}
    cum = (1 + r).cumprod()
    days = len(r); years = days / 252
    return {'CAGR': cum.iloc[-1] ** (1/years) - 1 if years > 0 else np.nan,
              'AnnVol': r.std() * np.sqrt(252),
              'Sharpe': (r.mean() * 252) / (r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
              'MaxDD': (cum / cum.cummax() - 1).min()}


def main():
    print("=" * 78)
    print("MOMENTUM-BASKET V4 — attack individual-name blowups")
    print("A: V3 winner  |  B: A+pledging+vol_cap  |  C: B+Novy-Marx quality")
    print("=" * 78)

    print("\n[Loading data]", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data()
    quality_scored = pd.read_parquet(os.path.join(REPO_ROOT, 'data', 'momentum_scores',
                                                    'quality_scored_universe.parquet'))
    quality_scored['rebalance_date'] = pd.to_datetime(quality_scored['rebalance_date'])
    quality_by_rd = build_quality_lookup(quality_scored)

    print("\n[Config 7 native]", flush=True)
    cfg7_on      = run_cfg7(raw)
    cfg7_no_gold = run_cfg7(raw, rotate_stress=False, use_g10_gate=False, use_momentum_gold=False)
    m_baseline = perf(cfg7_on.loc[:END_FULL]['strategy_return'])
    print(f"  Config 7 baseline: {m_baseline['CAGR']*100:.4f}% CAGR / Sh {m_baseline['Sharpe']:.4f}")

    print("[Building defensive basket]", flush=True)
    def_holdings, def_reb_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    def_ret, _ = v6.compute_daily_basket_returns(def_holdings, def_reb_dates, prices, cfg7_on.index)
    def_ret = def_ret.fillna(0)
    latch_id, day_in_latch, is_flat = identify_latches(cfg7_on['nifty_position'])
    prices_wide = prices.pivot_table(index='Date', columns='symbol', values='close', aggfunc='last')
    prices_wide = prices_wide.reindex(cfg7_on.index).ffill()
    nifty_close = raw['^NSEI'].copy()

    # --- Identity checks ---
    print("\n" + "=" * 78)
    print("IDENTITY CHECKS")
    print("=" * 78)
    ic1 = perf(cfg7_on.loc[:END_FULL]['strategy_return'])
    print(f"  IC1: {ic1['CAGR']*100:.4f}%  diff {(ic1['CAGR']-m_baseline['CAGR'])*100:+.6f}pp")
    ic2_ret = apply_defensive_overlay(cfg7_no_gold['strategy_return'], def_ret,
                                        latch_id, day_in_latch, is_flat)
    ic2 = perf(ic2_ret.loc[:END_FULL])
    print(f"  IC2 (def ON): {ic2['CAGR']*100:.4f}%  target 16.85%  Δ {(ic2['CAGR']-0.1685)*100:+.4f}pp")
    mom30_ret_series = raw['NIFTYMOM30'].reindex(cfg7_on.index).pct_change().fillna(0)
    ic3_pretax, _ = build_swap_pretax(cfg7_no_gold, raw, mom30_ret_series, {}, [], MOM30_COST_BPS)
    ic3 = perf(apply_annual_tax(ic3_pretax.fillna(0)).loc[:END_FULL])
    m_nogold = perf(cfg7_no_gold.loc[:END_FULL]['strategy_return'])
    diff3 = (ic3['CAGR'] - m_nogold['CAGR']) * 100
    print(f"  IC3 (swap identity): {ic3['CAGR']*100:.4f}%  vs cfg7_no_gold {m_nogold['CAGR']*100:.4f}%  Δ {diff3:+.6f}pp")
    if abs(diff3) > 1e-3:
        print("  ⚠ IC3 drift — check reconstruction"); return
    print("  ✓ All identity checks OK")

    # --- Build 3 variants ---
    reb_dates = sorted(scored['rebalance_date'].unique())
    beta_vol_cache = {}

    configs = [
        ('A_baseline',           False, False, False),
        ('B_pledge_volcap',      True,  True,  False),
        ('C_pledge_volcap_novy', True,  True,  True),
    ]

    variant_results = {}
    variant_baskets = {}
    variant_excluded = {}

    for label, use_pledge, use_vol, use_novy in configs:
        print(f"\n[Building {label}]", flush=True)
        baskets, excluded_log = select_basket(
            scored, fund_wide, quality_by_rd, prices, nifty_close, reb_dates,
            use_pledging_filter=use_pledge, use_vol_cap=use_vol,
            use_novy_marx=use_novy, beta_vol_cache=beta_vol_cache)
        variant_baskets[label] = baskets
        variant_excluded[label] = excluded_log
        # Coverage summary
        exc_pledge = sum(len(e['excluded_pledge']) for e in excluded_log)
        exc_vol    = sum(len(e['excluded_vol'])    for e in excluded_log)
        med_elig   = int(np.median([e['n_eligible_after_filters'] for e in excluded_log]))
        print(f"  Median eligible after filters: {med_elig}  |  Total pledge-excluded: {exc_pledge}  "
              f"|  Total vol-excluded: {exc_vol}")

        daily_ret, tvr = compute_basket_daily_returns(baskets, prices_wide, cfg7_on.index)
        new_pretax, _ = build_swap_pretax(cfg7_no_gold, raw, daily_ret, tvr, reb_dates, BASKET_COST_BPS)
        new_ret_swap = apply_annual_tax(new_pretax.fillna(0))
        final_ret = apply_defensive_overlay(new_ret_swap, def_ret, latch_id, day_in_latch, is_flat)
        variant_results[label] = final_ret

    # --- Report ---
    variants_final = {'R1': ic2_ret.loc[:END_FULL]}
    for label, _, _, _ in configs:
        variants_final[label] = variant_results[label].loc[:END_FULL]

    print("\n" + "=" * 78)
    print("HEADLINE — R1 vs A/B/C  (defensive basket ON in all)")
    print("=" * 78)
    for w_label in ['FULL 2008-2026', 'OOS 2017-2026']:
        w_start = cfg7_on.index.min() if 'FULL' in w_label else OOS_START
        w_end = END_FULL
        print(f"\n--- {w_label} ---")
        base_r = perf(variants_final['R1'].loc[w_start:w_end])
        print(f"  {'variant':22s} {'CAGR':>8s} {'ΔCAGR':>8s} {'Sharpe':>7s} {'ΔSh':>7s} "
              f"{'MaxDD':>8s} {'ΔMaxDD':>8s} {'AnnVol':>7s}")
        for k, ser in variants_final.items():
            r = perf(ser.loc[w_start:w_end])
            print(f"  {k:22s} {r['CAGR']*100:>7.2f}% {(r['CAGR']-base_r['CAGR'])*100:>+7.2f}pp "
                  f"{r['Sharpe']:>7.2f} {r['Sharpe']-base_r['Sharpe']:>+7.2f} "
                  f"{r['MaxDD']*100:>+7.2f}% {(r['MaxDD']-base_r['MaxDD'])*100:>+7.2f}pp "
                  f"{r['AnnVol']*100:>6.2f}%")

    # --- 2018-19 attribution per variant ---
    print("\n" + "=" * 78)
    print("2018-2019 WINDOW — did the filters help?")
    print("=" * 78)
    wstart, wend = pd.Timestamp('2018-01-01'), pd.Timestamp('2019-12-31')
    print(f"  {'variant':22s} {'2018':>8s} {'2019':>8s} {'MaxDD':>8s}")
    for k in ['R1', 'A_baseline', 'B_pledge_volcap', 'C_pledge_volcap_novy']:
        s = variants_final[k].loc[wstart:wend]
        r2018 = (1 + s.loc['2018-01-01':'2018-12-31']).prod() - 1
        r2019 = (1 + s.loc['2019-01-01':'2019-12-31']).prod() - 1
        cum = (1 + s).cumprod()
        dd = (cum / cum.cummax() - 1).min()
        print(f"  {k:22s} {r2018*100:>+7.2f}% {r2019*100:>+7.2f}% {dd*100:>+7.2f}%")

    # --- Individual name comparison at 2019-06-28 rebalance (mid-crash) ---
    print("\n" + "=" * 78)
    print("BASKET COMPOSITION at 2019-06-28 (mid-crash) — A vs B vs C")
    print("=" * 78)
    rd = pd.Timestamp('2019-06-28')
    for k in ['A_baseline', 'B_pledge_volcap', 'C_pledge_volcap_novy']:
        b = variant_baskets[k].get(rd)
        if b is None: continue
        names = list(b.keys())
        print(f"\n  {k} ({len(names)} names):")
        print(f"    {', '.join(names[:15])}")
        if len(names) > 15:
            print(f"    ... + {len(names)-15} more")
    # What A had that B/C dropped
    a_names = set(variant_baskets['A_baseline'].get(rd, {}).keys())
    b_names = set(variant_baskets['B_pledge_volcap'].get(rd, {}).keys())
    c_names = set(variant_baskets['C_pledge_volcap_novy'].get(rd, {}).keys())
    print(f"\n  A - B (dropped by pledge+vol filters):     {sorted(a_names - b_names)}")
    print(f"  B - C (moved due to Novy-Marx re-ranking): {sorted(b_names - c_names)}")
    print(f"  C - B (added due to Novy-Marx re-ranking): {sorted(c_names - b_names)}")

    # --- Verdict ---
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    for k in ['A_baseline', 'B_pledge_volcap', 'C_pledge_volcap_novy']:
        for w_label in ['FULL', 'OOS']:
            w_start = cfg7_on.index.min() if w_label == 'FULL' else OOS_START
            w_end = END_FULL
            r1 = perf(variants_final['R1'].loc[w_start:w_end])
            v  = perf(variants_final[k].loc[w_start:w_end])
            print(f"  {k:24s} {w_label:5s}: ΔCAGR {(v['CAGR']-r1['CAGR'])*100:+.2f}pp  "
                  f"ΔSh {v['Sharpe']-r1['Sharpe']:+.2f}  ΔMaxDD {(v['MaxDD']-r1['MaxDD'])*100:+.2f}pp")

    print(f"\nOutputs → {OUT_DIR}")


if __name__ == '__main__':
    main()

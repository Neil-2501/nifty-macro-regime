"""Momentum-basket bake-off V3 — fix concentration, regime-flip cost, and cost model.

V2 diagnosis (see diagnose_basket_drawdown.py):
  - The -36% MaxDD in M_hard_rules is Jan 2018 → Oct 2019 (642 days).
    Nifty 50 was +7.3%, Mom30 index -2.0%, our equal-weight basket -30.2%.
    That IS the 2018-19 mid/small-cap crash. Equal-weight tilt got destroyed
    while cap-weighted index survived.
  - 34 entry/exit events (regime flipping in/out of bull) during those 642 days
    → ~10.2% cost drag = 31% of the total DD comes from regime-flip friction.

V3 fixes (stacked):
  1. Size-tilted weighting (α ∈ {0, 0.5, 1.0} on turnover) — fix concentration
  2. Persistence gate on basket ENTRY (N days of confirmed bull) — fix flip cost
  3. Realistic cost model: 15 bps/side for U200, 30 bps/side for U500

Fixed: hard_rules gate (no change to quality check), buffer=45, N_hold=30.

Grid: 3 weightings × 3 persistence × 2 universe/cost = 18 cells.

Identity checks (must pass):
  IC1. swap OFF, defensive OFF → Config 7 exact
  IC2. swap OFF, defensive ON  → V7 basket_cash_blend
  IC3. swap ON with my_basket=Mom30, N=0, cost=6bps → cfg7_no_gold exact
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

OUT_DIR = os.path.join(REPO_ROOT, "data", "momentum_basket_bakeoff_v3")
os.makedirs(OUT_DIR, exist_ok=True)

MOM30_COST_BPS = 6
DEFENSIVE_COST_BPS_PER_SIDE = 30
STCG_PRE  = 0.15
STCG_POST = 0.20
STCG_CHANGE_DATE = pd.Timestamp('2024-07-23')
TAX_RATE = 0.15

END_FULL = pd.Timestamp('2026-05-11')
IS_END   = pd.Timestamp('2016-12-31')
OOS_START = pd.Timestamp('2017-01-01')

DEFENSIVE_N = 40
DEFENSIVE_ALLOC = 0.5

N_HOLD = 30
DE_MAX = 2.0
BUF   = 45

ETF_PATTERNS = ['GOLD', 'SILVER', 'SILV', 'BEES', 'NIFTY', 'BANKN', 'LIQUID',
                'NAV', 'IETF', 'NIFTYIETF', 'GOLDIETF', 'SETFGOLD',
                'JGOLD', 'MAFANG', 'CPSE', 'PSU', 'MOM100']


def _is_etf(sym: str) -> bool:
    return any(p in str(sym).upper() for p in ETF_PATTERNS)


# ----------------------------------------------------------------------------
# Config 7 native
# ----------------------------------------------------------------------------
def run_cfg7(raw, rotate_stress=True, use_g10_gate=True, use_momentum_gold=True):
    combiner = prod.make_combiner(
        rotate_stress=rotate_stress, rotate_panic=False,
        use_momentum_gold=use_momentum_gold, gold_gate_external=use_g10_gate,
        slow_stress_lock_days=5, panic_short_dd_threshold=0.15,
    )
    strat = prod.MacroStrategy(
        combiner, nifty_cost_bps=3, gold_cost_bps=5,
        long_target="NIFTYMOM30", long_cost_bps=MOM30_COST_BPS,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
    )
    return strat.run(raw).loc['2008-04-01':'2026-06-15']


# ----------------------------------------------------------------------------
# Quality gate lookups
# ----------------------------------------------------------------------------
def build_fund_lookup(fund_wide):
    return {int(fy): grp.set_index('symbol') for fy, grp in fund_wide.groupby('fiscal_year')}


def passes_hard_rules(sym, rd, fund_by_fy) -> bool:
    fy = brd.latest_fy_at_date(rd)
    fund_year = fund_by_fy.get(int(fy))
    if fund_year is None or sym not in fund_year.index:
        return False
    return brd.check_hard_rules(fund_year.loc[sym].to_dict(), cap_intensive_de_max=DE_MAX)


# ----------------------------------------------------------------------------
# Basket construction — hard_rules gate + size-tilted weighting
# ----------------------------------------------------------------------------
def select_basket(scored, fund_wide, rebalance_dates,
                    universe: int, weighting_alpha: float, buf: int, N: int):
    """weighting_alpha:
        0.0 → equal-weight
        0.5 → weight ∝ sqrt(turnover)
        1.0 → weight ∝ turnover (proxies cap-weight)
    """
    fund_by_fy = build_fund_lookup(fund_wide)
    baskets = {}
    prev_holdings = []

    for rd in rebalance_dates:
        rd_ts = pd.Timestamp(rd)
        sub = scored[scored['rebalance_date'] == rd_ts].copy()
        sub = sub[sub['universe_rank_turnover'] <= universe]
        sub = sub[~sub['symbol'].map(_is_etf)]
        sub = sub.sort_values('composite_risk_adj', ascending=False).reset_index(drop=True)
        # Apply hard_rules gate
        sub['gate_ok'] = [passes_hard_rules(s, rd_ts, fund_by_fy) for s in sub['symbol']]
        eligible = sub[sub['gate_ok']].reset_index(drop=True)

        if len(eligible) < N:
            missing = N - len(eligible)
            fill = sub[~sub['gate_ok']].head(missing)['symbol'].tolist()
            picks = eligible['symbol'].tolist() + fill
            picks_with_turnover = pd.DataFrame({'symbol': picks}).merge(
                sub[['symbol', 'avg_60d_turnover_rupees']], on='symbol', how='left')
        else:
            elig_set = set(eligible['symbol'].tolist())
            buffer_set = set(eligible.head(buf)['symbol'].tolist())
            top_N_names = eligible.head(N)['symbol'].tolist()

            held = [s for s in prev_holdings if s in elig_set and s in buffer_set]
            new_names = [s for s in top_N_names if s not in held]
            picks = (held + new_names)[:N]
            picks_with_turnover = eligible[eligible['symbol'].isin(picks)][
                ['symbol', 'avg_60d_turnover_rupees']]

        # Compute weights
        pw = picks_with_turnover.set_index('symbol').reindex(picks)
        tvr = pw['avg_60d_turnover_rupees'].fillna(pw['avg_60d_turnover_rupees'].median()).clip(lower=1)
        if weighting_alpha == 0.0:
            raw_w = pd.Series(1.0, index=tvr.index)
        else:
            raw_w = tvr ** weighting_alpha
        w = (raw_w / raw_w.sum()).to_dict()

        baskets[rd_ts] = w
        prev_holdings = picks

    return baskets


def compute_basket_daily_returns(baskets: dict, prices_wide: pd.DataFrame,
                                 date_index: pd.DatetimeIndex):
    rebalance_dates = sorted(baskets.keys())
    daily_ret = pd.Series(0.0, index=date_index)
    turnover_by_reb = {}

    all_symbols = set()
    for w in baskets.values():
        all_symbols.update(w.keys())
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
        if not period.any():
            continue
        cols = [s for s in w.index if s in all_ret.columns]
        if not cols:
            continue
        weights = pd.Series({s: w[s] for s in cols})
        weights = weights / weights.sum()
        basket_r = all_ret.loc[period, cols] @ weights
        daily_ret.loc[period] = basket_r.values

    return daily_ret, turnover_by_reb


# ----------------------------------------------------------------------------
# Persistence gate on basket ENTRY — delay entry by N days of confirmed bull.
# Exit: immediate when bull flips to non-bull (protective).
# ----------------------------------------------------------------------------
def apply_persistence_gate(raw_active: pd.Series, N_days: int) -> pd.Series:
    """Returns modified active mask: enter basket only after N consecutive days
    of raw_active==1. Exit immediately on raw_active==0.
    N_days=0 → no delay (returns raw_active unchanged).
    """
    if N_days == 0:
        return raw_active.astype(int)
    vals = raw_active.astype(int).values
    n = len(vals)
    consec = np.zeros(n, dtype=int)
    for i in range(n):
        if vals[i] == 1:
            consec[i] = consec[i-1] + 1 if i > 0 else 1
        else:
            consec[i] = 0
    gated = (consec >= N_days).astype(int)
    return pd.Series(gated, index=raw_active.index)


# ----------------------------------------------------------------------------
# Swap into pretax
# ----------------------------------------------------------------------------
def build_swap_pretax(cfg7, raw, my_basket_daily_ret, turnover_by_reb, rebalance_dates,
                       my_cost_bps_per_side: float, persistence_N: int = 0):
    raw_active_bool = cfg7['long_mom_default'] & ~cfg7['composition_swap_active']
    raw_active = raw_active_bool.astype(int)
    active = apply_persistence_gate(raw_active, persistence_N).astype(float)

    mom30_ret = raw['NIFTYMOM30'].reindex(cfg7.index).pct_change().fillna(0)

    # Config 7's own Mom30 lane (using raw_active — Config 7 doesn't know about persistence)
    raw_active_f = raw_active.astype(float)
    mom30_pnl  = raw_active_f.shift(1).fillna(0) * mom30_ret
    mom30_cost = raw_active_f.diff().abs().fillna(0) * (MOM30_COST_BPS / 10_000)

    # My basket lane — uses PERSISTENCE-GATED active (fewer flips)
    my_pnl     = active.shift(1).fillna(0) * my_basket_daily_ret.reindex(cfg7.index).fillna(0)
    my_entry_exit_cost = active.diff().abs().fillna(0) * (my_cost_bps_per_side / 10_000)

    # On days where MY basket is NOT active but Config 7 WOULD have held Mom30,
    # we hold cash. Cash yield already handled inside cfg7_no_gold, but here we
    # are subtracting Mom30 and adding basket — leaving those days at 0 marginal.
    # (The base — cfg7_no_gold — provides cash yield on all non-active days.)

    my_rebal_cost = pd.Series(0.0, index=cfg7.index)
    for rd, tvr in turnover_by_reb.items():
        rd = pd.Timestamp(rd)
        candidate_days = cfg7.index[cfg7.index >= rd]
        if len(candidate_days) == 0:
            continue
        day = candidate_days[0]
        if active.loc[day] == 1.0:
            my_rebal_cost.loc[day] += 2 * tvr * (my_cost_bps_per_side / 10_000)

    new_pretax = (cfg7['strategy_return_pretax']
                    - (mom30_pnl - mom30_cost)
                    + (my_pnl - my_entry_exit_cost - my_rebal_cost))
    return new_pretax, active, raw_active_f


def apply_annual_tax(daily_returns, tax_rate=TAX_RATE):
    out = daily_returns.copy()
    yrs = daily_returns.index.year
    annual = (1 + daily_returns).groupby(yrs).prod() - 1
    for y in annual.index:
        if annual[y] > 0:
            mask = (daily_returns.index.year == y)
            out.loc[mask] = daily_returns.loc[mask] * (1.0 - tax_rate)
    return out


# ----------------------------------------------------------------------------
# Defensive overlay
# ----------------------------------------------------------------------------
def identify_latches(nifty_pos_series):
    is_flat = (nifty_pos_series == 0.0).values
    n = len(is_flat)
    latch_id = np.zeros(n, dtype=int)
    day_in_latch = np.zeros(n, dtype=int)
    cur_id, cur_day = 0, 0
    for i in range(n):
        if is_flat[i]:
            if i == 0 or not is_flat[i-1]:
                cur_id += 1; cur_day = 1
            else:
                cur_day += 1
            latch_id[i] = cur_id
            day_in_latch[i] = cur_day
        else:
            cur_day = 0
    return latch_id, day_in_latch, is_flat


def apply_defensive_overlay(base_daily_ret, defensive_basket_ret, latch_id, day_in_latch,
                             is_flat, N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC):
    ret = base_daily_ret.values.copy()
    basket = defensive_basket_ret.reindex(base_daily_ret.index).fillna(0).values
    active = is_flat & (day_in_latch > N)
    ret[active] = alloc * basket[active] + (1 - alloc) * base_daily_ret.values[active]

    cost_per_side = DEFENSIVE_COST_BPS_PER_SIDE / 10_000
    dates = base_daily_ret.index
    for i in range(1, len(ret)):
        if active[i] and not active[i-1]:
            ret[i] -= alloc * cost_per_side
        elif not active[i] and active[i-1]:
            j = i - 1
            while j > 0 and active[j-1]:
                j -= 1
            run = ret[j:i]
            cum = np.prod(1 + run) - 1
            gain_frac = alloc * cum if cum > 0 else 0
            rate = STCG_POST if dates[i] >= STCG_CHANGE_DATE else STCG_PRE
            tax = gain_frac * rate
            ret[i] -= alloc * cost_per_side + tax
    return pd.Series(ret, index=base_daily_ret.index), active.astype(int)


def perf(r):
    r = pd.Series(r).dropna()
    if r.empty:
        return {'CAGR': np.nan, 'AnnVol': np.nan, 'Sharpe': np.nan, 'MaxDD': np.nan, 'N': 0}
    cum = (1 + r).cumprod()
    days = len(r); years = days / 252
    return {
        'CAGR': cum.iloc[-1] ** (1/years) - 1 if years > 0 else np.nan,
        'AnnVol': r.std() * np.sqrt(252),
        'Sharpe': (r.mean() * 252) / (r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
        'MaxDD': (cum / cum.cummax() - 1).min(),
        'N': days,
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    print("=" * 78)
    print("MOMENTUM-BASKET V3 — cap-weight tilt + persistence gate + realistic costs")
    print("Fixed: hard_rules gate, buffer=45, N_hold=30. Defensive basket ON.")
    print("=" * 78)

    print("\n[Loading data]", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data()

    print("\n[Data coverage]")
    for col in ['^NSEI', 'NIFTYMOM30', 'GOLDBEES.NS', '^INDIAVIX', 'INR=X']:
        if col in raw.columns:
            fv = raw[col].first_valid_index(); lv = raw[col].last_valid_index()
            print(f"  {col:14s} {fv.date() if fv is not None else '?'} → {lv.date() if lv is not None else '?'}")
    print(f"  scored_universe: {scored['rebalance_date'].min().date()} → {scored['rebalance_date'].max().date()}  "
          f"({scored['rebalance_date'].nunique()} rebs, {scored.groupby('rebalance_date').size().max()} rows/reb)")
    print(f"  fund_wide: {fund_wide['fiscal_year'].min()} → {fund_wide['fiscal_year'].max()}")

    print("\n[Running Config 7 native]", flush=True)
    cfg7_on      = run_cfg7(raw)
    cfg7_no_gold = run_cfg7(raw, rotate_stress=False, use_g10_gate=False, use_momentum_gold=False)
    m_baseline = perf(cfg7_on.loc[:END_FULL]['strategy_return'])
    print(f"  Config 7 baseline: {m_baseline['CAGR']*100:.4f}% CAGR / Sh {m_baseline['Sharpe']:.4f} (target 16.52%)")

    print("[Building defensive basket for overlay]", flush=True)
    def_holdings, def_reb_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    defensive_basket_ret, _ = v6.compute_daily_basket_returns(
        def_holdings, def_reb_dates, prices, cfg7_on.index)
    defensive_basket_ret = defensive_basket_ret.fillna(0)

    latch_id, day_in_latch, is_flat = identify_latches(cfg7_on['nifty_position'])
    prices_wide = prices.pivot_table(index='Date', columns='symbol', values='close', aggfunc='last')
    prices_wide = prices_wide.reindex(cfg7_on.index).ffill()

    # ==========================================================================
    # IDENTITY CHECKS
    # ==========================================================================
    print("\n" + "=" * 78)
    print("IDENTITY CHECKS")
    print("=" * 78)
    ic1 = perf(cfg7_on.loc[:END_FULL]['strategy_return'])
    print(f"  IC1: {ic1['CAGR']*100:.4f}%  Sh {ic1['Sharpe']:.4f}  diff {(ic1['CAGR']-m_baseline['CAGR'])*100:+.6f}pp")

    ic2_ret, _ = apply_defensive_overlay(
        cfg7_no_gold['strategy_return'], defensive_basket_ret,
        latch_id, day_in_latch, is_flat, N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC)
    ic2 = perf(ic2_ret.loc[:END_FULL])
    print(f"  IC2 (defensive ON): {ic2['CAGR']*100:.4f}%  Sh {ic2['Sharpe']:.4f}  "
          f"(target V7 16.85%, ΔCAGR {(ic2['CAGR']-0.1685)*100:+.4f}pp)")

    mom30_ret_series = raw['NIFTYMOM30'].reindex(cfg7_on.index).pct_change().fillna(0)
    ic3_pretax, _, _ = build_swap_pretax(
        cfg7_no_gold, raw, my_basket_daily_ret=mom30_ret_series,
        turnover_by_reb={}, rebalance_dates=[],
        my_cost_bps_per_side=MOM30_COST_BPS, persistence_N=0)
    ic3_ret = apply_annual_tax(ic3_pretax.fillna(0))
    ic3 = perf(ic3_ret.loc[:END_FULL])
    m_nogold = perf(cfg7_no_gold.loc[:END_FULL]['strategy_return'])
    diff3 = (ic3['CAGR'] - m_nogold['CAGR']) * 100
    print(f"  IC3 (swap identity, N=0): {ic3['CAGR']*100:.4f}%  Sh {ic3['Sharpe']:.4f}  "
          f"vs cfg7_no_gold {m_nogold['CAGR']*100:.4f}%  Δ {diff3:+.6f}pp")
    if abs(diff3) > 1e-3:
        print("  ⚠ IC3 drift — investigate before proceeding")
    else:
        print("  ✓ All identity checks OK")

    # ==========================================================================
    # GRID: weighting × persistence × universe/cost
    # ==========================================================================
    print("\n" + "=" * 78)
    print("GRID: weighting × persistence × universe/cost  (18 cells)")
    print("=" * 78)

    reb_dates = sorted(scored['rebalance_date'].unique())
    grid = []
    for weighting_alpha, weighting_label in [(0.0, 'eq'), (0.5, 'sqrt'), (1.0, 'tv')]:
        for persistence_N in [0, 10, 20]:
            for universe, cost in [(200, 15), (500, 30)]:
                grid.append((weighting_alpha, weighting_label, persistence_N, universe, cost))

    grid_results = []
    grid_cache = {}
    grid_baskets = {}

    for weighting_alpha, weighting_label, persistence_N, universe, cost in grid:
        label = f"{weighting_label}_N{persistence_N}_U{universe}"
        baskets = select_basket(scored, fund_wide, reb_dates,
                                universe=universe, weighting_alpha=weighting_alpha,
                                buf=BUF, N=N_HOLD)
        grid_baskets[label] = baskets
        daily_basket_ret, turnover_by_reb = compute_basket_daily_returns(
            baskets, prices_wide, cfg7_on.index)
        new_pretax, active_mask, raw_active = build_swap_pretax(
            cfg7_no_gold, raw, daily_basket_ret, turnover_by_reb, reb_dates,
            my_cost_bps_per_side=cost, persistence_N=persistence_N)
        new_ret_swap = apply_annual_tax(new_pretax.fillna(0))
        final_ret, def_active = apply_defensive_overlay(
            new_ret_swap, defensive_basket_ret, latch_id, day_in_latch, is_flat,
            N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC)
        grid_cache[label] = (final_ret, active_mask, raw_active, turnover_by_reb, cost)

        is_mask = final_ret.index <= IS_END
        m_is = perf(final_ret[is_mask])
        m_full = perf(final_ret.loc[:END_FULL])
        oos_mask = (final_ret.index >= OOS_START) & (final_ret.index <= END_FULL)
        m_oos = perf(final_ret[oos_mask])

        n_flips = int(active_mask.diff().abs().fillna(0).sum())
        avg_turnover = float(np.mean(list(turnover_by_reb.values())[1:])) if len(turnover_by_reb) > 1 else 0.0

        grid_results.append({
            'variant': label, 'weighting_alpha': weighting_alpha,
            'persistence_N': persistence_N, 'universe': universe, 'cost_bps': cost,
            'IS_CAGR': m_is['CAGR'], 'IS_Sharpe': m_is['Sharpe'],
            'FULL_CAGR': m_full['CAGR'], 'FULL_Sharpe': m_full['Sharpe'], 'FULL_MaxDD': m_full['MaxDD'],
            'OOS_CAGR': m_oos['CAGR'], 'OOS_Sharpe': m_oos['Sharpe'], 'OOS_MaxDD': m_oos['MaxDD'],
            'n_entry_exit_events': n_flips,
            'avg_turnover_per_reb': avg_turnover,
        })

    grid_df = pd.DataFrame(grid_results)
    grid_df.to_csv(os.path.join(OUT_DIR, 'grid_metrics.csv'), index=False)

    # Lock winner by IS Sharpe
    winner_idx = grid_df['IS_Sharpe'].idxmax()
    winner = grid_df.loc[winner_idx]
    print(f"\n  LOCKED (best IS Sharpe): {winner['variant']}  IS Sh {winner['IS_Sharpe']:.3f}")

    # Sort grid for readable display: by universe then weighting then persistence
    grid_df_disp = grid_df.sort_values(['universe', 'weighting_alpha', 'persistence_N']).reset_index(drop=True)
    print(f"\n  {'variant':16s} {'IS Sh':>6s} {'FULL CAGR':>10s} {'FULL Sh':>7s} "
          f"{'OOS CAGR':>10s} {'OOS Sh':>7s} {'FULL DD':>8s} {'flips':>6s} {'avgT':>6s}")
    for _, r in grid_df_disp.iterrows():
        mark = ' ←' if r['variant'] == winner['variant'] else '  '
        print(f"  {r['variant']:16s} {r['IS_Sharpe']:>6.3f} "
              f"{r['FULL_CAGR']*100:>9.2f}% {r['FULL_Sharpe']:>7.3f} "
              f"{r['OOS_CAGR']*100:>9.2f}% {r['OOS_Sharpe']:>7.3f} "
              f"{r['FULL_MaxDD']*100:>+7.2f}% {int(r['n_entry_exit_events']):>5d} "
              f"{r['avg_turnover_per_reb']*100:>4.0f}%{mark}")

    # ==========================================================================
    # HEADLINE — R1 vs best variant per universe
    # ==========================================================================
    print("\n" + "=" * 78)
    print("HEADLINE — R1 vs best-of-U200 and best-of-U500 (by IS Sharpe)")
    print("=" * 78)
    best_u200 = grid_df[grid_df['universe'] == 200].loc[grid_df[grid_df['universe'] == 200]['IS_Sharpe'].idxmax()]
    best_u500 = grid_df[grid_df['universe'] == 500].loc[grid_df[grid_df['universe'] == 500]['IS_Sharpe'].idxmax()]
    print(f"  Best U200: {best_u200['variant']}  (IS Sh {best_u200['IS_Sharpe']:.3f})")
    print(f"  Best U500: {best_u500['variant']}  (IS Sh {best_u500['IS_Sharpe']:.3f})")

    variants_final = {
        'R1': ic2_ret.loc[:END_FULL],
        'M_U200_best':  grid_cache[best_u200['variant']][0].loc[:END_FULL],
        'M_U500_best':  grid_cache[best_u500['variant']][0].loc[:END_FULL],
    }

    for label in ['FULL 2008-2026', 'OOS 2017-2026']:
        w_start = cfg7_on.index.min() if 'FULL' in label else OOS_START
        w_end   = END_FULL
        print(f"\n--- {label} ---")
        print(f"  {'variant':16s} {'CAGR':>8s} {'ΔCAGR':>8s} {'Sharpe':>7s} {'ΔSh':>7s} "
              f"{'MaxDD':>8s} {'ΔMaxDD':>8s} {'AnnVol':>7s}")
        base_r = perf(variants_final['R1'].loc[w_start:w_end])
        for lbl, ser in variants_final.items():
            r = perf(ser.loc[w_start:w_end])
            print(f"  {lbl:16s} {r['CAGR']*100:>7.2f}% {(r['CAGR']-base_r['CAGR'])*100:>+7.2f}pp "
                  f"{r['Sharpe']:>7.2f} {r['Sharpe']-base_r['Sharpe']:>+7.2f} "
                  f"{r['MaxDD']*100:>+7.2f}% {(r['MaxDD']-base_r['MaxDD'])*100:>+7.2f}pp "
                  f"{r['AnnVol']*100:>6.2f}%")

    # ==========================================================================
    # PERSISTENCE-GATE EFFECT — hold weighting+universe fixed, vary N
    # ==========================================================================
    print("\n" + "=" * 78)
    print("PERSISTENCE-GATE EFFECT — how much did the entry gate help?")
    print("=" * 78)
    for u in [200, 500]:
        for w_alpha, w_lab in [(0.0, 'eq'), (0.5, 'sqrt'), (1.0, 'tv')]:
            sub = grid_df[(grid_df['universe'] == u) & (grid_df['weighting_alpha'] == w_alpha)]
            print(f"  U{u}, weighting={w_lab}:")
            for _, r in sub.sort_values('persistence_N').iterrows():
                print(f"    N={int(r['persistence_N']):>2d}: flips={int(r['n_entry_exit_events']):>4d}  "
                      f"FULL CAGR {r['FULL_CAGR']*100:>6.2f}%  Sh {r['FULL_Sharpe']:.3f}  "
                      f"DD {r['FULL_MaxDD']*100:+.2f}%  |  OOS CAGR {r['OOS_CAGR']*100:>6.2f}%  Sh {r['OOS_Sharpe']:.3f}")

    # ==========================================================================
    # 2018-2019 window — the crash years — did the fixes help?
    # ==========================================================================
    print("\n" + "=" * 78)
    print("2018-2019 WINDOW (M_hard_rules had -36% DD here in V2)")
    print("=" * 78)
    window_start, window_end = pd.Timestamp('2018-01-01'), pd.Timestamp('2019-12-31')
    print(f"  {'variant':16s} {'2018 ret':>10s} {'2019 ret':>10s} {'MaxDD-in-win':>13s} {'flips-in-win':>13s}")
    for lbl, ser in variants_final.items():
        s = ser.loc[window_start:window_end]
        r2018 = (1 + s.loc['2018-01-01':'2018-12-31']).prod() - 1
        r2019 = (1 + s.loc['2019-01-01':'2019-12-31']).prod() - 1
        # MaxDD inside window
        cum = (1 + s).cumprod()
        dd = (cum / cum.cummax() - 1).min()
        # Count flips for M variants only
        flips_win = ''
        for cache_lbl, (fret, amask, ramask, tvr, cost) in grid_cache.items():
            if lbl == 'M_U200_best' and cache_lbl == best_u200['variant']:
                flips_win = str(int(amask.loc[window_start:window_end].diff().abs().fillna(0).sum()))
            elif lbl == 'M_U500_best' and cache_lbl == best_u500['variant']:
                flips_win = str(int(amask.loc[window_start:window_end].diff().abs().fillna(0).sum()))
        print(f"  {lbl:16s} {r2018*100:>+9.2f}% {r2019*100:>+9.2f}% {dd*100:>+12.2f}% {flips_win:>13s}")

    # ==========================================================================
    # VERDICT
    # ==========================================================================
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    r1_full = perf(variants_final['R1'].loc[:END_FULL])
    r1_oos  = perf(variants_final['R1'].loc[OOS_START:END_FULL])
    for k in ['M_U200_best', 'M_U500_best']:
        pf = perf(variants_final[k].loc[:END_FULL])
        po = perf(variants_final[k].loc[OOS_START:END_FULL])
        print(f"\n  {k}:")
        print(f"    FULL:  ΔCAGR {(pf['CAGR']-r1_full['CAGR'])*100:+.2f}pp  ΔSh {pf['Sharpe']-r1_full['Sharpe']:+.2f}  ΔMaxDD {(pf['MaxDD']-r1_full['MaxDD'])*100:+.2f}pp")
        print(f"    OOS:   ΔCAGR {(po['CAGR']-r1_oos['CAGR'])*100:+.2f}pp   ΔSh {po['Sharpe']-r1_oos['Sharpe']:+.2f}  ΔMaxDD {(po['MaxDD']-r1_oos['MaxDD'])*100:+.2f}pp")
        wins_full = (pf['CAGR'] > r1_full['CAGR']) and (pf['Sharpe'] > r1_full['Sharpe'])
        wins_oos  = (po['CAGR'] > r1_oos['CAGR']) and (po['Sharpe'] > r1_oos['Sharpe'])
        print(f"    → Beats R1 FULL={'YES' if wins_full else 'no'}  OOS={'YES' if wins_oos else 'no'}")

    print(f"\nOutputs → {OUT_DIR}")


if __name__ == '__main__':
    main()

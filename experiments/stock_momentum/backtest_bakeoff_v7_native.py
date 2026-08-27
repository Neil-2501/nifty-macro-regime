"""V7 defensive bake-off — NATIVE approach.

Instead of computing our own cash yield (which drifts from Config 7's internal
model), we use strategy.py NATIVE runs to source the cash and gold behavior:

  cfg7_on         = Config 7 with G10 gold rotation (incumbent baseline)
  cfg7_no_gold    = Config 7 with rotate_stress=False (source of pure-cash
                    behavior on stress-flat days)
  cfg7_simple_gold= Config 7 with gold_gate_external=False + rotate_with_momentum=False
                    (rotate_stress=True but no G10 conditions — pure bear-regime gold)

For basket candidates we still need an overlay, but the cash portion comes
from cfg7_no_gold's actual return (not our own formula), and the basket
return replaces the cash return only on the basket-active days.

Candidates:
  0. baseline_cfg7   (cfg7_on)
  1. pure_cash       (cfg7_no_gold — native)
  2. simple_gold     (cfg7_simple_gold — native)
  3. g10_incumbent   (cfg7_on again for symmetry)
  4. basket_gated    (cfg7_no_gold + basket on days_in_latch > N)
  5. basket_cash_blend  (cfg7_no_gold + 50/50 basket)
  6. basket_gold_blend  (cfg7_simple_gold + 50/50 basket)
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

import defensive_sleeve_v6 as v6
import strategy as prod

OUT_DIR = os.path.join(REPO_ROOT, "data", "bakeoff_v7_native")
os.makedirs(OUT_DIR, exist_ok=True)

BASKET_COST_BPS_PER_SIDE = 30
STCG_PRE  = 0.15
STCG_POST = 0.20
STCG_CHANGE_DATE = pd.Timestamp('2024-07-23')


def run_cfg7(raw, rotate_stress: bool, use_g10_gate: bool = True,
                use_momentum_gold: bool = True):
    """Run Config 7 with the given gold-side flags. Everything else stays Config 7.
    rotate_stress=False → no gold at all (pure cash on stress-flat)
    rotate_stress=True + use_g10_gate=False + use_momentum_gold=False →
        simple gold whenever regime allows (approximates Config 2 with Mom30).
    """
    combiner = prod.make_combiner(
        rotate_stress=rotate_stress,
        rotate_panic=False,
        use_momentum_gold=use_momentum_gold,
        gold_gate_external=use_g10_gate,
        slow_stress_lock_days=5,
        panic_short_dd_threshold=0.15,
    )
    strat = prod.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                                     long_target="NIFTYMOM30", long_cost_bps=6,
                                     enable_v2=True, v2_dd_threshold=0.15, v2_days=60)
    return strat.run(raw).loc['2008-04-01':'2026-06-15']


def identify_latches(cfg7):
    is_flat = (cfg7['nifty_position'] == 0.0).values
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


def apply_basket_cost_tax(ret, active_mask, alloc, dates):
    """In-place: charge basket entry/exit + STCG on exit gains."""
    cost_per_side = BASKET_COST_BPS_PER_SIDE / 10_000
    for i in range(1, len(ret)):
        if active_mask[i] and not active_mask[i-1]:
            ret[i] -= alloc * cost_per_side
        elif not active_mask[i] and active_mask[i-1]:
            j = i - 1
            while j > 0 and active_mask[j-1]:
                j -= 1
            run = ret[j:i]
            cum = np.prod(1 + run) - 1
            gain_frac = alloc * cum if cum > 0 else 0
            rate = STCG_POST if dates[i] >= STCG_CHANGE_DATE else STCG_PRE
            tax = gain_frac * rate
            ret[i] -= alloc * cost_per_side + tax
    return ret


def build_basket_variant(base_ret_series, basket_ret, is_flat, day_in_latch, N, alloc):
    """Take a base return series (which handles cash/gold on stress-flat days)
    and OVERRIDE it with the basket on days_in_latch > N.

    alloc=1.0 → 100% basket (replaces base on active days)
    alloc<1.0 → alloc*basket + (1-alloc)*base on active days
    """
    ret = base_ret_series.values.copy()
    active = is_flat & (day_in_latch > N)
    ret[active] = alloc * basket_ret.values[active] + (1 - alloc) * base_ret_series.values[active]
    apply_basket_cost_tax(ret, active, alloc, base_ret_series.index)
    return ret, active.astype(int)


def perf(r):
    r = pd.Series(r).dropna()
    if r.empty:
        return {'CAGR': np.nan, 'AnnVol': np.nan, 'Sharpe': np.nan,
                'MaxDD': np.nan, 'HitRate': np.nan, 'N': 0}
    cum = (1 + r).cumprod()
    days = len(r); years = days/252
    return {
        'CAGR': cum.iloc[-1]**(1/years) - 1 if years > 0 else np.nan,
        'AnnVol': r.std() * np.sqrt(252),
        'Sharpe': (r.mean()*252)/(r.std()*np.sqrt(252)) if r.std() > 0 else np.nan,
        'MaxDD': (cum/cum.cummax() - 1).min(),
        'HitRate': (r > 0).mean(),
        'N': days, 'years': years,
    }


def per_episode(cfg7_on, cand_rets, latch_id):
    rows = []
    for lid in np.unique(latch_id):
        if lid == 0:
            continue
        mask = latch_id == lid
        idxs = np.where(mask)[0]
        row = {'latch_id': int(lid),
                'start': cfg7_on.index[idxs[0]], 'end': cfg7_on.index[idxs[-1]],
                'days': int(mask.sum())}
        for name, arr in cand_rets.items():
            row[f'{name}'] = (1 + arr[mask]).prod() - 1
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    print("=" * 70)
    print("V7 BAKE-OFF — NATIVE APPROACH (all cash/gold from strategy.py)")
    print("=" * 70)

    print("\nLoading data...", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data()

    print("\nData ranges:")
    for col in ['^NSEI', 'NIFTYMOM30', 'GOLDBEES.NS']:
        if col in raw.columns:
            print(f"  {col:16s} {raw[col].first_valid_index().date()} → {raw[col].last_valid_index().date()}")

    # ---- 3 native strategy.py runs ----
    print("\n[Native runs]")
    print("  Running cfg7_on (incumbent Config 7 with G10 gold)...", flush=True)
    cfg7_on = run_cfg7(raw, rotate_stress=True, use_g10_gate=True, use_momentum_gold=True)

    print("  Running cfg7_no_gold (Config 7 no rotation)...", flush=True)
    cfg7_no_gold = run_cfg7(raw, rotate_stress=False, use_g10_gate=False, use_momentum_gold=False)

    print("  Running cfg7_simple_gold (Config 7 with rotation, no G10 conditions)...", flush=True)
    cfg7_simple_gold = run_cfg7(raw, rotate_stress=True, use_g10_gate=False, use_momentum_gold=False)

    END_FULL = pd.Timestamp('2026-05-11')
    m_on   = perf(cfg7_on.loc['2008-04-01':END_FULL]['strategy_return'])
    m_off  = perf(cfg7_no_gold.loc['2008-04-01':END_FULL]['strategy_return'])
    m_sg   = perf(cfg7_simple_gold.loc['2008-04-01':END_FULL]['strategy_return'])
    print(f"\n  cfg7_on (incumbent):   CAGR {m_on['CAGR']*100:.2f}%  Sharpe {m_on['Sharpe']:.2f}  MaxDD {m_on['MaxDD']*100:.2f}%")
    print(f"  cfg7_no_gold:          CAGR {m_off['CAGR']*100:.2f}%  Sharpe {m_off['Sharpe']:.2f}  MaxDD {m_off['MaxDD']*100:.2f}%")
    print(f"  cfg7_simple_gold:      CAGR {m_sg['CAGR']*100:.2f}%  Sharpe {m_sg['Sharpe']:.2f}  MaxDD {m_sg['MaxDD']*100:.2f}%")
    print(f"\n  Δ vs incumbent:")
    print(f"    no_gold     Δ CAGR {(m_off['CAGR']-m_on['CAGR'])*100:+.2f}pp  Δ Sharpe {m_off['Sharpe']-m_on['Sharpe']:+.2f}")
    print(f"    simple_gold Δ CAGR {(m_sg['CAGR']-m_on['CAGR'])*100:+.2f}pp  Δ Sharpe {m_sg['Sharpe']-m_on['Sharpe']:+.2f}")

    # ---- Latches (same for all three since nifty_position is regime-driven) ----
    latch_id, day_in_latch, is_flat = identify_latches(cfg7_on)
    print(f"\n  Stress-flat days: {is_flat.sum():,} in {latch_id.max()} latches")

    # Sanity check: cfg7_on / cfg7_no_gold / cfg7_simple_gold should have IDENTICAL nifty_position
    same_pos_off = (cfg7_on['nifty_position'] == cfg7_no_gold['nifty_position']).mean()
    same_pos_sg  = (cfg7_on['nifty_position'] == cfg7_simple_gold['nifty_position']).mean()
    print(f"  nifty_position alignment vs cfg7_on: no_gold={same_pos_off*100:.1f}%  simple_gold={same_pos_sg*100:.1f}%")

    # ---- Defensive basket ----
    print("\n[Building defensive basket]")
    holdings, rebalance_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    daily_basket_ret, _ = v6.compute_daily_basket_returns(
        holdings, rebalance_dates, prices, cfg7_on.index)
    daily_basket_ret = daily_basket_ret.fillna(0)
    print(f"  Basket rebalances: {len(rebalance_dates)}, sample: {holdings[rebalance_dates[-1]][:5]}")
    print(f"  Non-zero basket days: {(daily_basket_ret != 0).sum():,}")

    # ---- Assemble non-basket candidates ----
    cand_ret = {}
    cand_deploy = {}
    cand_ret['0_baseline_cfg7']  = cfg7_on['strategy_return'].values.copy()
    cand_deploy['0_baseline_cfg7'] = np.zeros(len(cfg7_on), dtype=int)

    cand_ret['1_pure_cash']  = cfg7_no_gold['strategy_return'].values.copy()
    cand_deploy['1_pure_cash']   = is_flat.astype(int)   # every stress-flat day is a "cash day"

    cand_ret['2_simple_gold'] = cfg7_simple_gold['strategy_return'].values.copy()
    # simple_gold deploys on stress-flat + bear regime days (native handles it)
    cand_deploy['2_simple_gold']  = is_flat.astype(int)

    cand_ret['3_g10_incumbent'] = cfg7_on['strategy_return'].values.copy()
    cand_deploy['3_g10_incumbent'] = np.zeros(len(cfg7_on), dtype=int)

    # ---- Tune N for basket candidates on 2008-2016 ----
    print("\n[Tuning N ∈ {10,20,30,40,50,60} on 2008-2016]")
    IS_END = pd.Timestamp('2016-12-31')
    is_mask = cfg7_on.index <= IS_END

    def _tune(builder):
        best_N, best_sh = None, -np.inf
        for N in [10, 20, 30, 40, 50, 60]:
            r, _ = builder(N)
            sh = perf(pd.Series(r, index=cfg7_on.index)[is_mask])['Sharpe']
            if sh > best_sh:
                best_sh, best_N = sh, N
        return best_N, best_sh

    # Basket-gated: base = no_gold, alloc=1.0
    def _bg(N):
        return build_basket_variant(cfg7_no_gold['strategy_return'],
                                          daily_basket_ret, is_flat, day_in_latch, N, alloc=1.0)
    N_bg, sh_bg = _tune(_bg)
    print(f"  4_basket_gated:      N={N_bg} (IS Sharpe {sh_bg:.3f})")

    # Basket + cash 50/50: base = no_gold, alloc=0.5
    def _bcb(N):
        return build_basket_variant(cfg7_no_gold['strategy_return'],
                                          daily_basket_ret, is_flat, day_in_latch, N, alloc=0.5)
    N_bcb, sh_bcb = _tune(_bcb)
    print(f"  5_basket_cash_blend: N={N_bcb} (IS Sharpe {sh_bcb:.3f})")

    # Basket + simple_gold 50/50: base = simple_gold, alloc=0.5
    def _bgb(N):
        return build_basket_variant(cfg7_simple_gold['strategy_return'],
                                          daily_basket_ret, is_flat, day_in_latch, N, alloc=0.5)
    N_bgb, sh_bgb = _tune(_bgb)
    print(f"  6_basket_gold_blend: N={N_bgb} (IS Sharpe {sh_bgb:.3f})")

    r_bg, d_bg = _bg(N_bg);   cand_ret['4_basket_gated'] = r_bg; cand_deploy['4_basket_gated'] = d_bg
    r_cb, d_cb = _bcb(N_bcb); cand_ret['5_basket_cash_blend'] = r_cb; cand_deploy['5_basket_cash_blend'] = d_cb
    r_gb, d_gb = _bgb(N_bgb); cand_ret['6_basket_gold_blend'] = r_gb; cand_deploy['6_basket_gold_blend'] = d_gb

    locked_N = {'4_basket_gated': N_bg, '5_basket_cash_blend': N_bcb, '6_basket_gold_blend': N_bgb}

    # ---- Report ----
    print("\n" + "=" * 70)
    print("PERFORMANCE — post-tax, net of real costs")
    print("(2025-12-31 → mid-2026 is PARTIAL, ~4.5 months)")
    print("=" * 70)

    OOS_START = pd.Timestamp('2017-01-01')
    windows = {
        'FULL 2008-2026': (cfg7_on.index.min(), END_FULL),
        'OOS 2017-2026':  (OOS_START, END_FULL),
    }
    rows = []
    for w_label, (w_s, w_e) in windows.items():
        w_mask = (cfg7_on.index >= w_s) & (cfg7_on.index <= w_e)
        for name in sorted(cand_ret.keys()):
            sub = cand_ret[name][w_mask]
            m = perf(sub)
            dep_sub = cand_deploy[name][w_mask]
            n_days = int(dep_sub.sum())
            n_dep = int((np.diff(np.concatenate([[0], dep_sub])) > 0).sum())
            rows.append({
                'candidate': name, 'window': w_label,
                'locked_N': locked_N.get(name),
                'CAGR': m['CAGR'], 'AnnVol': m['AnnVol'], 'Sharpe': m['Sharpe'],
                'MaxDD': m['MaxDD'], 'HitRate': m['HitRate'],
                'deploy_days': n_days, 'n_deployments': n_dep,
            })
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT_DIR, "metrics.csv"), index=False)

    for w_label in windows.keys():
        print(f"\n--- {w_label} ---")
        sub = df[df['window'] == w_label].copy().sort_values('candidate')
        base = sub[sub['candidate'] == '0_baseline_cfg7'].iloc[0]
        sub['ΔCAGR']  = (sub['CAGR']  - base['CAGR'])  * 100
        sub['ΔSh']    =  sub['Sharpe'] - base['Sharpe']
        sub['ΔMaxDD'] = (sub['MaxDD'] - base['MaxDD']) * 100
        print(f"  {'candidate':22s} {'N':>4s} {'CAGR':>7s} {'ΔCAGR':>8s}  {'Sh':>5s} {'ΔSh':>6s}  "
              f"{'MaxDD':>7s} {'ΔMaxDD':>8s}  {'deploys':>8s}")
        for _, r in sub.iterrows():
            n_s = f"{int(r['locked_N'])}" if pd.notna(r['locked_N']) else '  -'
            print(f"  {r['candidate']:22s} {n_s:>4s} {r['CAGR']*100:>6.2f}% {r['ΔCAGR']:>+7.2f}pp  "
                  f"{r['Sharpe']:>5.2f} {r['ΔSh']:>+6.2f}  {r['MaxDD']*100:>+6.2f}% {r['ΔMaxDD']:>+7.2f}pp  "
                  f"{int(r['n_deployments']):>8d}")

    # Per-episode
    ep = per_episode(cfg7_on, cand_ret, latch_id)
    ep.to_csv(os.path.join(OUT_DIR, "episodes.csv"), index=False)
    print(f"\n\nPer-episode attribution → {OUT_DIR}/episodes.csv  ({len(ep)} latches)")

    # Verdict
    print("\n" + "=" * 70)
    print("VERDICT — 4 questions")
    print("=" * 70)
    def _row(c, w): return df[(df['candidate']==c) & (df['window']==w)].iloc[0]
    for w in windows.keys():
        print(f"\n[{w}]")
        base = _row('0_baseline_cfg7', w)
        cash = _row('1_pure_cash', w)
        sg   = _row('2_simple_gold', w)
        g10  = _row('3_g10_incumbent', w)
        bg   = _row('4_basket_gated', w)
        cb   = _row('5_basket_cash_blend', w)
        gb   = _row('6_basket_gold_blend', w)
        print(f"  Q1. Cost of removing G10 gate:")
        print(f"      pure_cash vs g10:   ΔCAGR {(cash['CAGR']-g10['CAGR'])*100:+.2f}pp  ΔSh {cash['Sharpe']-g10['Sharpe']:+.2f}")
        print(f"      simple_gold vs g10: ΔCAGR {(sg['CAGR']-g10['CAGR'])*100:+.2f}pp  ΔSh {sg['Sharpe']-g10['Sharpe']:+.2f}")
        print(f"  Q2. Gold (no gate) vs pure_cash:")
        print(f"      simple_gold vs pure_cash: ΔCAGR {(sg['CAGR']-cash['CAGR'])*100:+.2f}pp  "
              f"ΔSh {sg['Sharpe']-cash['Sharpe']:+.2f}  ΔMaxDD {(sg['MaxDD']-cash['MaxDD'])*100:+.2f}pp")
        print(f"  Q3. Quality basket vs incumbent:")
        for c, lbl in [(bg, '4_basket_gated'), (cb, '5_basket_cash_blend'), (gb, '6_basket_gold_blend')]:
            print(f"      {lbl:22s}: ΔCAGR {(c['CAGR']-g10['CAGR'])*100:+.2f}pp  "
                  f"ΔSh {c['Sharpe']-g10['Sharpe']:+.2f}  ΔMaxDD {(c['MaxDD']-g10['MaxDD'])*100:+.2f}pp")
        print(f"  Q4. Best-Sharpe candidate:")
        by_sh = sorted([(r['candidate'], r['Sharpe'], r['CAGR'], r['MaxDD']) for _, r in df[df['window']==w].iterrows()],
                          key=lambda t: -t[1])
        for c, sh, ca, dd in by_sh[:3]:
            print(f"      {c:22s} Sharpe {sh:.2f}  CAGR {ca*100:.2f}%  MaxDD {dd*100:.2f}%")

    print(f"\nOutputs → {OUT_DIR}")


if __name__ == '__main__':
    main()

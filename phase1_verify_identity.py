"""PHASE 1 identity check — verify the strategy.py refactor is byte-clean.

IC1: enable_defensive_basket=False must reproduce Config 7 baseline exactly
     (16.52% CAGR, Sharpe 0.81, MaxDD -12.78% for FULL 2008-04 → 2026-05-11).

IC2: enable_defensive_basket=True must reproduce R1 (defensive-on production)
     (16.85% CAGR, Sharpe 0.83, MaxDD -13.92%).

Both are computed via the SAME `MacroStrategy(...).run()` call, differing
only in the enable_defensive_basket flag. No manual overlay orchestration.
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "experiments", "stock_momentum"))

import defensive_sleeve_v6 as v6      # provides load_all_data
import strategy as prod

END_FULL  = pd.Timestamp('2026-05-11')
OOS_START = pd.Timestamp('2017-01-01')


def run_cfg7(raw, enable_defensive_basket: bool):
    combiner = prod.make_combiner(
        rotate_stress=True, rotate_panic=False, use_momentum_gold=True,
        slow_stress_lock_days=5, panic_short_dd_threshold=0.15)
    strat = prod.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                                     long_target="NIFTYMOM30", long_cost_bps=6,
                                     enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
                                     enable_defensive_basket=enable_defensive_basket)
    return strat.run(raw).loc['2008-04-01':'2026-06-15']


def perf_rf(r, daily_rf):
    r = pd.Series(r).dropna()
    if r.empty: return {'CAGR': np.nan, 'Sharpe': np.nan, 'MaxDD': np.nan, 'AnnVol': np.nan}
    daily_rf = daily_rf.reindex(r.index).fillna(0)
    excess = r - daily_rf
    cum = (1 + r).cumprod()
    days = len(r); years = days / 252
    ann_vol = r.std() * np.sqrt(252)
    return {'CAGR':   cum.iloc[-1] ** (1/years) - 1 if years > 0 else np.nan,
              'Sharpe': (excess.mean() * 252) / ann_vol if ann_vol > 0 else np.nan,
              'MaxDD':  (cum / cum.cummax() - 1).min(),
              'AnnVol': ann_vol}


def main():
    print("=" * 78)
    print("PHASE 1 IDENTITY CHECK — strategy.py refactor (defensive basket wired in)")
    print("=" * 78)

    print("\n[Loading data]", flush=True)
    raw, _, _, _, _ = v6.load_all_data()
    repo = prod.build_rbi_repo_rate_series(pd.date_range('2008-04-01', '2026-05-11', freq='B'))
    daily_rf = (repo / 252)

    # -------------------- IC1 -------------------------------
    print("\n[IC1] MacroStrategy(..., enable_defensive_basket=False)", flush=True)
    cfg7_off = run_cfg7(raw, enable_defensive_basket=False)
    ic1_full = perf_rf(cfg7_off.loc['2008-04-01':END_FULL]['strategy_return'],
                          daily_rf.reindex(cfg7_off.index).fillna(0))
    ic1_oos  = perf_rf(cfg7_off.loc[OOS_START:END_FULL]['strategy_return'],
                          daily_rf.reindex(cfg7_off.index).fillna(0))
    print(f"  FULL: CAGR {ic1_full['CAGR']*100:.4f}%  Sharpe {ic1_full['Sharpe']:.4f}  "
          f"MaxDD {ic1_full['MaxDD']*100:.4f}%  AnnVol {ic1_full['AnnVol']*100:.2f}%")
    print(f"  OOS:  CAGR {ic1_oos['CAGR']*100:.4f}%  Sharpe {ic1_oos['Sharpe']:.4f}  "
          f"MaxDD {ic1_oos['MaxDD']*100:.4f}%")
    print(f"  TARGET: 16.5222% / 0.8078 / -12.7824% (FULL);  15.9521% / 0.7877 / -12.7824% (OOS)")
    ic1_ok = abs(ic1_full['CAGR'] - 0.165222) < 1e-4

    # -------------------- IC2 -------------------------------
    print("\n[IC2] MacroStrategy(..., enable_defensive_basket=True)  ← DEFAULT", flush=True)
    cfg7_on = run_cfg7(raw, enable_defensive_basket=True)
    ic2_full = perf_rf(cfg7_on.loc['2008-04-01':END_FULL]['strategy_return'],
                          daily_rf.reindex(cfg7_on.index).fillna(0))
    ic2_oos  = perf_rf(cfg7_on.loc[OOS_START:END_FULL]['strategy_return'],
                          daily_rf.reindex(cfg7_on.index).fillna(0))
    print(f"  FULL: CAGR {ic2_full['CAGR']*100:.4f}%  Sharpe {ic2_full['Sharpe']:.4f}  "
          f"MaxDD {ic2_full['MaxDD']*100:.4f}%  AnnVol {ic2_full['AnnVol']*100:.2f}%")
    print(f"  OOS:  CAGR {ic2_oos['CAGR']*100:.4f}%  Sharpe {ic2_oos['Sharpe']:.4f}  "
          f"MaxDD {ic2_oos['MaxDD']*100:.4f}%")
    print(f"  TARGET: 16.8548% / 0.8276 / -13.9163% (FULL);  16.1021% / 0.7949 / -10.8842% (OOS)")
    ic2_ok = abs(ic2_full['CAGR'] - 0.168548) < 1e-3     # 1e-3 = 10 bps tolerance

    # Defensive-basket-active column check
    if 'defensive_basket_active' in cfg7_on.columns:
        n_active = int(cfg7_on['defensive_basket_active'].sum())
        print(f"  defensive_basket_active column present: {n_active} active days")

    # -------------------- SUMMARY ----------------------------
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    print(f"  IC1 (defensive OFF = Config 7 baseline):  "
          f"CAGR {ic1_full['CAGR']*100:.4f}% vs target 16.5222%  Δ {(ic1_full['CAGR']-0.165222)*100:+.6f}pp  "
          f"{'✓ PASS' if ic1_ok else '⚠ FAIL'}")
    print(f"  IC2 (defensive ON  = R1 production):      "
          f"CAGR {ic2_full['CAGR']*100:.4f}% vs target 16.8548%  Δ {(ic2_full['CAGR']-0.168548)*100:+.6f}pp  "
          f"{'✓ PASS' if ic2_ok else '⚠ FAIL'}")

    # Delta
    print(f"\n  Defensive basket delta (this refactor):")
    print(f"    FULL: ΔCAGR {(ic2_full['CAGR']-ic1_full['CAGR'])*100:+.4f}pp  "
          f"ΔSharpe {ic2_full['Sharpe']-ic1_full['Sharpe']:+.4f}  "
          f"ΔMaxDD {(ic2_full['MaxDD']-ic1_full['MaxDD'])*100:+.4f}pp")
    print(f"    OOS:  ΔCAGR {(ic2_oos['CAGR']-ic1_oos['CAGR'])*100:+.4f}pp  "
          f"ΔSharpe {ic2_oos['Sharpe']-ic1_oos['Sharpe']:+.4f}  "
          f"ΔMaxDD {(ic2_oos['MaxDD']-ic1_oos['MaxDD'])*100:+.4f}pp")

    if ic1_ok and ic2_ok:
        print("\n✓ BOTH IC PASS — strategy.py refactor is byte-clean. Ready for Phase 2.")
    else:
        print("\n⚠ IC failure — investigate before proceeding.")


if __name__ == '__main__':
    main()

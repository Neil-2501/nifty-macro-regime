"""Verify that strategy.py reproduces the README's headline numbers, and that
switching the newer features off reproduces the earlier versions.

Checks (period 2008-04-01 → 2026-10-31, post-tax, Sharpe over RBI repo):
  1. v2.3 (all MacroStrategy defaults)                    → README: 17.49% / 0.87 / -12.97%
  2. v2.2 (cash_source="repo_haircut", idle_gold_alloc=0) → README: 16.31% / 0.80 / -13.92%
  3. Config 7 / v2.1 (v2.2 settings + basket off)         → README: 15.94% / 0.77 / -12.78%
  4. Each step changes only what it should: Config 7 and v2.2 hold equities
     on exactly the same days (the basket only affects flat days), and v2.2
     and v2.3 differ only on flat days.

Tolerance: 0.05pp CAGR, 0.01 Sharpe, 0.1pp max drawdown — Yahoo Finance
occasionally revises past prices, which can move results by a few hundredths.
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

START, END = '2008-04-01', '2026-10-31'

TARGETS = {
    'v2.3 (production)': ({}, 17.49, 0.87, -12.97),
    'v2.2': ({'cash_source': 'repo_haircut', 'idle_gold_alloc': 0}, 16.31, 0.80, -13.92),
    'Config 7 (v2.1)': ({'cash_source': 'repo_haircut', 'idle_gold_alloc': 0,
                         'enable_defensive_basket': False}, 15.94, 0.77, -12.78),
}


def run(raw, **kw):
    combiner = prod.make_combiner(rotate_stress=True, rotate_panic=False, use_momentum_gold=True,
                                  slow_stress_lock_days=5, panic_short_dd_threshold=0.15)
    strat = prod.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                               long_target="NIFTYMOM30", long_cost_bps=6,
                               enable_v2=True, v2_dd_threshold=0.15, v2_days=60, **kw)
    return strat.run(raw).loc[START:END]


def perf(r):
    rf = prod.build_rbi_repo_rate_series(r.index) / 252
    cum = (1 + r).cumprod()
    vol = r.std() * np.sqrt(252)
    return ((cum.iloc[-1] ** (252 / len(r)) - 1) * 100,
            ((r - rf).mean() * 252) / vol,
            (cum / cum.cummax() - 1).min() * 100)


def main():
    raw, *_ = v6.load_all_data(end_fetch="2026-11-01")
    results, ok = {}, True
    print(f"Period {START} → {END}, post-tax\n")
    for name, (kw, t_cagr, t_sh, t_dd) in TARGETS.items():
        res = run(raw, **kw); results[name] = res
        cagr, sh, dd = perf(res['strategy_return'])
        good = abs(cagr - t_cagr) <= 0.05 and abs(sh - t_sh) <= 0.01 and abs(dd - t_dd) <= 0.1
        ok &= good
        print(f"  {name:20s} CAGR {cagr:6.2f}% (README {t_cagr:.2f})  Sharpe {sh:.2f} ({t_sh:.2f})  "
              f"MaxDD {dd:6.2f}% ({t_dd:.2f})   {'PASS' if good else 'FAIL'}")

    c7, v22, v23 = results['Config 7 (v2.1)'], results['v2.2'], results['v2.3 (production)']
    same_days = (c7['nifty_position'] == v22['nifty_position']).all() and (v22['nifty_position'] == v23['nifty_position']).all()
    flat = v22['nifty_position'] == 0
    diff = (v22['strategy_return'] - v23['strategy_return']).abs() > 1e-12
    only_flat = not (diff & ~flat & ~flat.shift(1, fill_value=False)).any()
    print(f"\n  Same equity positions in Config 7, v2.2 and v2.3: {'PASS' if same_days else 'FAIL'}")
    print(f"  v2.3 differs from v2.2 only on flat days:          {'PASS' if only_flat else 'FAIL'}")
    ok &= same_days and only_flat
    print("\nALL CHECKS PASS" if ok else "\nSOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())

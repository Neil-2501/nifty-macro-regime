"""Rebuild the defensive basket artifacts from source data.

Run this ONCE to regenerate:
  data/defensive_basket_holdings.parquet       (holdings per rebalance date)
  data/defensive_basket_daily_returns.parquet  (daily basket return series)

These artifacts are what production loads at runtime via defensive_basket.py.

Source data required:
  data/momentum_scores/scored_universe.parquet      (bundled)
  data/quality_factor/quality_scores_pit.parquet    (bundled)
  data/bse_pipeline/extended_fundamentals_v2.parquet (bundled)
  data/yfinance_bulk/adjusted_prices_panel.parquet  (fetch via fetch_stock_prices.py)

If any input is missing, this script fails with an explicit message.
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

# Reuse the canonical basket selector + helpers from research code.
# TODO(prod-cleanup): move these helpers into defensive_basket.py in a
# follow-up refactor. For now they live in experiments/ and get imported.
import backtest_defensive_rotation as brd
import defensive_sleeve_v6 as v6

import strategy as prod


HOLDINGS_OUT = os.path.join(REPO_ROOT, "data", "defensive_basket_holdings.parquet")
RETURNS_OUT  = os.path.join(REPO_ROOT, "data", "defensive_basket_daily_returns.parquet")


def main(end_fetch="2026-06-15"):
    """end_fetch: exclusive end date for market data (e.g. "2026-11-14").
    Usage: python build_defensive_basket.py [END_DATE]"""
    print("=" * 78)
    print(f"Rebuilding defensive basket artifacts from source data (data end, exclusive: {end_fetch})")
    print("=" * 78)

    print("\n[Loading raw + panel data]", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data(end_fetch=end_fetch)
    print(f"  Data spans: {raw.index.min().date()} → {raw.index.max().date()}")
    print(f"  Stock prices panel: {prices['symbol'].nunique()} symbols")
    print(f"  Quality scores: {quality['rebalance_date'].nunique()} rebalance dates")
    print(f"  Fundamentals: {fund_wide['symbol'].nunique()} symbols, "
          f"FY {int(fund_wide['fiscal_year'].min())}–{int(fund_wide['fiscal_year'].max())}")

    print("\n[Running Config 7 to get canonical trading-day index]", flush=True)
    combiner = prod.make_combiner(True, False, use_momentum_gold=True,
                                     slow_stress_lock_days=5,
                                     panic_short_dd_threshold=0.15)
    strat = prod.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                                     long_target="NIFTYMOM30", long_cost_bps=6,
                                     enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
                                     enable_defensive_basket=False)
    cfg7 = strat.run(raw).loc['2008-04-01':end_fetch]
    print(f"  Config 7 trading days: {len(cfg7)}  ({cfg7.index.min().date()} → {cfg7.index.max().date()})")

    print("\n[Computing defensive basket holdings per rebalance date]", flush=True)
    holdings, rebalance_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    print(f"  {len(rebalance_dates)} rebalance dates, "
          f"{np.mean([len(h) for h in holdings.values()]):.1f} avg holdings per rebalance")

    print("\n[Computing daily basket returns]", flush=True)
    daily_ret, _ = v6.compute_daily_basket_returns(holdings, rebalance_dates, prices, cfg7.index)
    daily_ret = daily_ret.fillna(0.0)
    print(f"  Daily basket returns: {len(daily_ret)} days, non-zero on {int((daily_ret != 0).sum())} days")

    # -----------------------------------------------------------------------
    # Save artifacts
    # -----------------------------------------------------------------------
    holdings_rows = []
    for rd, syms in holdings.items():
        for sym in syms:
            holdings_rows.append({'rebalance_date': pd.Timestamp(rd),
                                    'symbol': sym,
                                    'weight': 1.0 / len(syms)})
    holdings_df = pd.DataFrame(holdings_rows)
    holdings_df.to_parquet(HOLDINGS_OUT, index=False)
    print(f"\n  Wrote holdings ({len(holdings_df)} rows) → {HOLDINGS_OUT}")

    # basket_available: True on days the basket actually held priced stocks.
    # Same period convention as compute_daily_basket_returns: (rebalance, next rebalance].
    # Days before the first rebalance, or after a rebalance that left the basket
    # empty, are False — the overlay keeps that money in cash instead.
    priced = set(prices['symbol'].unique())
    idx = daily_ret.index
    available = pd.Series(False, index=idx)
    rds = [pd.Timestamp(r) for r in rebalance_dates]
    for i, rd in enumerate(rds):
        end = rds[i + 1] if i + 1 < len(rds) else idx[-1]
        if any(s in priced for s in holdings.get(rebalance_dates[i], [])):
            available[(idx > rd) & (idx <= end)] = True
    empty = [r.date() for i, r in enumerate(rds) if not any(s in priced for s in holdings.get(rebalance_dates[i], []))]
    print(f"  Rebalances with an empty basket: {empty}")
    daily_ret_df = pd.DataFrame({'ret': daily_ret, 'basket_available': available})
    daily_ret_df.index.name = 'date'
    daily_ret_df.to_parquet(RETURNS_OUT)
    print(f"  Wrote daily returns ({len(daily_ret_df)} rows) → {RETURNS_OUT}")

    print("\n[Done] Production strategy.py + defensive_basket.py will load these artifacts at runtime.")


if __name__ == '__main__':
    main(*sys.argv[1:2])

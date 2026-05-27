"""
test_dma_sensitivity.py — TEST ONLY (NOT for production).

Sensitivity analysis on the regime-filter DMA window. Production (Config 6 / v1.3)
uses 100 DMA; this script runs the same strategy with 50, 75, 100, 125, 150,
200 DMA and reports key metrics.

Important note on the panic-short DMA. The PanicShortSignal definition also
references a DMA condition internally ("NIFTY < N DMA" as one of its three
trigger conditions). Historically the strategy had a bug where the regime
filter's DMA and the panic-short's DMA were mismatched — the panic-short
would fire on (e.g.) NIFTY < 100 DMA, but the regime filter using 50 DMA
would immediately kill the short. For a clean sensitivity test, this script
SYNCS both DMAs together. So "DMA=75" means BOTH the regime filter AND the
panic-short use a 75-day window.

strategy.py is NOT modified. We import the signal/combiner classes and
construct a custom combiner locally that mirrors make_combiner() but with
the DMA parameterized.
"""

import os
import sys
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from strategy import (
    SupplyShockSignal, PanicShortSignal, USDINRSignal, IndiaVIXSignal,
    RegimeFilter, SignalCombiner, MacroStrategy, metrics, load_nse_index_csv,
)

# ────────────────────────────────────────────────────────────────────────
# Data loading
# ────────────────────────────────────────────────────────────────────────

WARMUP    = "2006-01-01"
IS_START  = "2008-04-01"
IS_END    = "2025-12-31"
OOS_START = "2026-01-01"
TICKERS   = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS"]

print("Downloading data ...", file=sys.stderr)
raw = yf.download(TICKERS, start=WARMUP, end=None, auto_adjust=True, progress=False)["Close"]
raw.dropna(how="all", inplace=True)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv, "GOLDBEES.NS"].ffill()

_data_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "momentum30_history.csv",
)
mom30 = load_nse_index_csv(_data_path, "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()


# ────────────────────────────────────────────────────────────────────────
# Build Config 6 combiner with parameterized DMA
# ────────────────────────────────────────────────────────────────────────

def build_combiner_with_dma(dma_window: int) -> SignalCombiner:
    """Same as production make_combiner(), but DMA is parameterized.
    Both regime filter and PanicShortSignal use the SAME dma_window for a
    clean sensitivity test."""
    rf = RegimeFilter(window=dma_window)
    c = SignalCombiner(
        regime_filter=rf,
        rotate_to_gold_on_stress_flat=True,
        rotate_to_gold_on_panic_short=False,
        rotate_with_momentum=True,
    )
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    c.add_exit(SupplyShockSignal(window=10, oil_threshold=0.03,
                                 inr_threshold=0.01, vix_threshold=0.20))
    c.add_short(
        PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=dma_window),
        hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20,
    )
    return c


# ────────────────────────────────────────────────────────────────────────
# Run sensitivity grid
# ────────────────────────────────────────────────────────────────────────

dma_windows = [50, 75, 100, 125, 150, 200]
results = []

for dma in dma_windows:
    combiner = build_combiner_with_dma(dma)
    s = MacroStrategy(
        combiner,
        nifty_cost_bps=3, gold_cost_bps=5,
        long_target="NIFTYMOM30", long_cost_bps=6,
    )
    res = s.run(raw)
    res_is  = res.loc[IS_START:IS_END]
    res_oos = res.loc[OOS_START:]
    m = metrics(res_is["strategy_return"])
    oos_ret = (1 + res_oos["strategy_return"]).prod() - 1
    results.append({
        "dma":       dma,
        "cum":       m["total"],
        "cagr":      m["cagr"],
        "sharpe":    m["sharpe"],
        "calmar":    m["calmar"],
        "max_dd":    m["max_dd"],
        "oos_2026":  oos_ret,
    })


# ────────────────────────────────────────────────────────────────────────
# Print table
# ────────────────────────────────────────────────────────────────────────

print()
print("=" * 90)
print("  DMA SENSITIVITY — Config 6 (v1.3 production) with varying regime-filter DMA")
print("  Note: PanicShortSignal DMA also synced to match (avoids regime-vs-signal mismatch)")
print("  In-sample period: 2008-04-01 to 2025-12-31")
print("=" * 90)
print()
print(f"  {'DMA':>5}  {'Cumulative':>12}  {'CAGR':>9}  {'Sharpe':>9}  "
      f"{'Calmar':>9}  {'Max DD':>9}  {'2026 OOS':>10}")
print("  " + "-" * 80)
for r in results:
    marker = "  *" if r["dma"] == 100 else "   "
    print(f"  {r['dma']:>3d}{marker}  {r['cum']*100:>11.1f}%  {r['cagr']*100:>8.2f}%  "
          f"{r['sharpe']:>9.2f}  {r['calmar']:>9.2f}  {r['max_dd']*100:>+8.1f}%  "
          f"{r['oos_2026']*100:>+9.2f}%")
print("\n  (* = production value)")

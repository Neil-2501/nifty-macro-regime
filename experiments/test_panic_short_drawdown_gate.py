"""
test_panic_short_drawdown_gate.py — does a drawdown-depth gate on panic-short
fix the 2013-08-27 and 2022-02-24 false fires without breaking GFC / COVID?

Rule: panic-short can fire only if NIFTY's drawdown from its trailing 60-day
high exceeds X%. All other engines (slow-stress with Lock 5d, regime, gold,
V2) unchanged.

Pre-specified thresholds: 0% (= no gate, baseline), 8%, 10%, 12%, 15%, 20%, 25%.

Decisive checks:
  1. Does each threshold kill 2013-08-27?
  2. Does each threshold kill 2022-02-24?
  3. Are 2008 + 2020 panic-short fires PRESERVED at every threshold?

Reports headline metrics, year-by-year, full panic-short firing log per
threshold (with NIFTY DD at fire time), and plateau analysis. Does not tune
the threshold to specific years — only reports all six pre-specified values.

Original strategy.py NOT modified. Self-contained experiment.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

import strategy as s
from strategy import (
    MacroStrategy, RegimeFilter, SignalCombiner,
    USDINRSignal, IndiaVIXSignal, PanicShortSignal,
    SlowStressWithLockSignal,
)
from strategy_lab import _load_data


# ----------------------------------------------------------------------
# Gated panic-short
# ----------------------------------------------------------------------
class PanicShortWithDDGate(PanicShortSignal):
    """Panic-short with a NIFTY-drawdown depth gate. Fires only when the
    base panic-short conditions AND NIFTY's drawdown from its trailing
    `dd_lookback`-day high exceeds `dd_threshold`."""
    name = "panic_short_dd_gated"

    def __init__(self, dd_threshold=0.10, dd_lookback=60, **kwargs):
        super().__init__(**kwargs)
        self.dd_threshold = dd_threshold
        self.dd_lookback = dd_lookback

    def compute(self, data):
        raw = super().compute(data)
        nifty = data["^NSEI"].ffill()
        trailing_max = nifty.rolling(self.dd_lookback, min_periods=1).max()
        dd = 1.0 - nifty / trailing_max   # positive number = drawdown depth
        gate_passes = dd > self.dd_threshold
        firing = (raw < 0) & gate_passes
        out = pd.Series(0.0, index=raw.index, name=self.name)
        out[firing] = -1.0
        return out


# ----------------------------------------------------------------------
# Combiner builder + strategy runner
# ----------------------------------------------------------------------
def build_combiner(dd_threshold):
    rf = RegimeFilter(window=100)
    c = SignalCombiner(
        regime_filter=rf,
        rotate_to_gold_on_stress_flat=True,
        rotate_to_gold_on_panic_short=False,
        rotate_with_momentum=True,
        gold_gate_external=True,
    )
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    # Slow-stress with Lock 5d (v2.0 production)
    c.add_exit_no_cooldown(SlowStressWithLockSignal(
        lock_days=5,
        inr_window=20, inr_threshold=0.01,
        vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5,
    ))
    # Panic-short: gated when dd_threshold > 0, else baseline
    if dd_threshold > 0:
        panic = PanicShortWithDDGate(
            dd_threshold=dd_threshold, dd_lookback=60,
            vix_level=25, vix_spike=0.50, window=10, dma=100,
        )
    else:
        panic = PanicShortSignal(vix_level=25, vix_spike=0.50,
                                  window=10, dma=100)
    c.add_short(panic, hold=False, max_hold_days=60,
                exit_ma_fast=5, exit_ma_slow=20)
    return c, panic


def run_variant(raw, dd_threshold):
    combiner, panic = build_combiner(dd_threshold)
    strat = MacroStrategy(
        combiner,
        target="^NSEI", gold_target="GOLDBEES.NS",
        nifty_cost_bps=3, gold_cost_bps=5,
        long_target="NIFTYMOM30", long_cost_bps=6,
        apply_tax=True, tax_rate=0.15,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
    )
    df = strat.run(raw).loc["2008-04-01":"2025-12-31"]
    # Compute panic-short firing log
    fires = panic.compute(raw)
    firing_dates = fires[fires < 0].index
    nifty = raw["^NSEI"].ffill()
    trailing_max = nifty.rolling(60, min_periods=1).max()
    dd = 1.0 - nifty / trailing_max
    firing_log = [(d, float(dd.loc[d]), float(nifty.loc[d]))
                  for d in firing_dates if d >= pd.Timestamp("2008-04-01")
                  and d <= pd.Timestamp("2025-12-31")]
    return df, firing_log


def main():
    raw = _load_data()
    THRESHOLDS = [0.0, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25]

    print("Running 7 variants ...", file=sys.stderr)
    results = []
    for x in THRESHOLDS:
        label = "Baseline (no gate)" if x == 0 else f"DD ≥ {int(x*100)}%"
        print(f"  {label} ...", file=sys.stderr)
        df, log = run_variant(raw, x)
        results.append((x, label, df, log))

    out = []
    def p(text=""): print(text); out.append(text)

    p("\n" + "=" * 130)
    p("  PANIC-SHORT DRAWDOWN GATE TEST — v2.0 + DD gate on panic-short")
    p("=" * 130)
    p()
    p("  Rule: panic-short fires only if NIFTY DD from trailing 60d high exceeds X%.")
    p("  All other v2.0 engines (Slow-stress + Lock 5d, regime, gold, V2) unchanged.")
    p()

    # ---- Headline metrics ----
    p("=" * 130)
    p("  HEADLINE METRICS (post-tax, 2008-04-01 → 2025-12-31)")
    p("=" * 130)
    p(f"  {'Variant':<22} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} "
      f"{'Vol':>8} {'PS fires':>9} {'ΔCAGR':>9}")
    p("  " + "-"*22 + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " "
      + "-"*8 + " " + "-"*9 + " " + "-"*9)
    base_m = None
    for x, label, df, log in results:
        m = s.metrics(df["strategy_return"])
        if x == 0: base_m = m
        dc = m["cagr"] - base_m["cagr"]
        dc_str = "—" if x == 0 else f"{dc*100:+.2f}pp"
        p(f"  {label:<22} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} "
          f"{m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {m['vol']*100:>7.2f}% "
          f"{len(log):>9d} {dc_str:>9}")
    p()

    # ---- Year-by-year ----
    p("=" * 130)
    p("  YEAR-BY-YEAR (post-tax %)")
    p("=" * 130)
    hdr = f"  {'Year':<6}"
    for x, label, _, _ in results:
        short = "Base" if x == 0 else f"DD{int(x*100)}"
        hdr += f" {short:>9}"
    nifty_close = raw["^NSEI"].loc["2008-04-01":"2025-12-31"]
    hdr += f" {'NIFTY':>9}"
    p(hdr)
    p("  " + "-"*6 + (" " + "-"*9) * (len(results) + 1))
    for y in sorted(set(results[0][2].index.year)):
        row = f"  {y:<6}"
        for x, label, df, log in results:
            yr = float((1 + df["strategy_return"][df.index.year == y]).prod() - 1) * 100
            row += f" {yr:>+8.2f}%"
        ny = nifty_close[nifty_close.index.year == y]
        nv = float(ny.iloc[-1] / ny.iloc[0] - 1) * 100 if len(ny) > 1 else 0
        row += f" {nv:>+8.2f}%"
        p(row)
    p()

    # ---- Decisive 2013 / 2022 checks ----
    p("=" * 130)
    p("  DECISIVE CHECKS — does the gate kill 2013-08-27 and 2022-02-24?")
    p("=" * 130)
    test_dates = [pd.Timestamp("2013-08-27"), pd.Timestamp("2022-02-24")]
    p(f"  {'Variant':<22} {'2013-08-27 fired?':>20} {'2022-02-24 fired?':>20}  Note")
    p("  " + "-"*22 + " " + "-"*20 + " " + "-"*20 + "  " + "-"*30)
    for x, label, df, log in results:
        d2013 = "YES (false)" if any(d == test_dates[0] for d, _, _ in log) else "no (gated)"
        d2022 = "YES (false)" if any(d == test_dates[1] for d, _, _ in log) else "no (gated)"
        # NIFTY DD at those dates
        nifty = raw["^NSEI"].ffill()
        tmax = nifty.rolling(60, min_periods=1).max()
        dd = 1.0 - nifty / tmax
        dd_2013 = float(dd.loc[test_dates[0]]) * 100 if test_dates[0] in dd.index else float("nan")
        dd_2022 = float(dd.loc[test_dates[1]]) * 100 if test_dates[1] in dd.index else float("nan")
        note = (f"NIFTY DD: 2013={dd_2013:.1f}% / 2022={dd_2022:.1f}%"
                if x == 0 else "")
        p(f"  {label:<22} {d2013:>20} {d2022:>20}  {note}")
    p()

    # ---- 2008 + 2020 preservation check ----
    p("=" * 130)
    p("  PRESERVATION CHECK — are 2008 + 2020 panic-short fires PRESERVED at every threshold?")
    p("=" * 130)
    base_log = results[0][3]
    fires_2008 = [(d, dd_v, n) for d, dd_v, n in base_log if d.year == 2008]
    fires_2020 = [(d, dd_v, n) for d, dd_v, n in base_log if d.year == 2020]
    p(f"  Baseline panic-short fires in 2008 ({len(fires_2008)}):")
    for d, dd_v, n in fires_2008:
        p(f"    {d.strftime('%Y-%m-%d')}: NIFTY {n:.0f}, DD from 60d high = {dd_v*100:.1f}%")
    p(f"  Baseline panic-short fires in 2020 ({len(fires_2020)}):")
    for d, dd_v, n in fires_2020:
        p(f"    {d.strftime('%Y-%m-%d')}: NIFTY {n:.0f}, DD from 60d high = {dd_v*100:.1f}%")
    p()
    p(f"  {'Variant':<22} {'2008 fires kept':>17} {'2020 fires kept':>17}  Disqualified?")
    p("  " + "-"*22 + " " + "-"*17 + " " + "-"*17 + "  " + "-"*15)
    for x, label, df, log in results:
        kept_2008 = len([d for d, _, _ in log if d.year == 2008])
        kept_2020 = len([d for d, _, _ in log if d.year == 2020])
        n_2008 = len(fires_2008); n_2020 = len(fires_2020)
        disq = []
        if kept_2008 < n_2008: disq.append(f"2008 ({n_2008-kept_2008} lost)")
        if kept_2020 < n_2020: disq.append(f"2020 ({n_2020-kept_2020} lost)")
        verdict = "DISQ: " + ", ".join(disq) if disq else "PASS"
        p(f"  {label:<22} {kept_2008}/{n_2008:<14} {kept_2020}/{n_2020:<14}  {verdict}")
    p()

    # ---- Full firing log per variant ----
    p("=" * 130)
    p("  FULL PANIC-SHORT FIRING LOG (each variant)")
    p("=" * 130)
    for x, label, df, log in results:
        p()
        p(f"  --- {label} ({len(log)} fires) ---")
        if len(log) == 0:
            p("      (no fires)")
        for d, dd_v, n in log:
            p(f"    {d.strftime('%Y-%m-%d')}: NIFTY {n:.0f}, DD from 60d high = {dd_v*100:5.1f}%")
    p()

    # ---- Plateau check ----
    p("=" * 130)
    p("  PLATEAU CHECK — is CAGR roughly flat across X = 8 → 25?")
    p("=" * 130)
    p(f"  {'Threshold':<15} {'CAGR':>9} {'Sharpe':>8} {'MaxDD':>9} {'Δ CAGR vs base':>16}")
    p("  " + "-"*15 + " " + "-"*9 + " " + "-"*8 + " " + "-"*9 + " " + "-"*16)
    base_cagr = base_m["cagr"]
    cagrs = []
    for x, label, df, log in results:
        if x == 0: continue
        m = s.metrics(df["strategy_return"])
        cagrs.append(m["cagr"])
        p(f"  {label:<15} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} "
          f"{m['max_dd']*100:+8.2f}% {(m['cagr']-base_cagr)*100:>+14.2f}pp")
    p()
    if cagrs:
        cagr_arr = np.array(cagrs)
        spread = (cagr_arr.max() - cagr_arr.min()) * 100
        p(f"  Spread of CAGR across 8-25% thresholds: {spread:.2f}pp")
        if spread < 0.15:
            p("  → ROBUST PLATEAU (all thresholds produce essentially the same CAGR — rule is")
            p("    not fitted to any specific drawdown value; any threshold in this range works.)")
        elif spread < 0.30:
            p("  → MODERATE plateau — small variation, no sharp cliff. Probably robust.")
        else:
            p("  → NOT A PLATEAU — variation across thresholds suggests fragility. Treat skeptically.")
    p()

    # ---- Key-year focus ----
    p("=" * 130)
    p("  KEY-YEAR FOCUS — 2008, 2013, 2020, 2022")
    p("=" * 130)
    for y in [2008, 2013, 2020, 2022]:
        p(f"\n  --- {y} ---")
        for x, label, df, log in results:
            yr = float((1 + df["strategy_return"][df.index.year == y]).prod() - 1) * 100
            n_fires = len([d for d, _, _ in log if d.year == y])
            p(f"    {label:<22} return {yr:+7.2f}%   panic-short fires: {n_fires}")
    p()

    # Save
    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "test_panic_short_drawdown_gate.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()

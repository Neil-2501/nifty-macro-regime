"""
test_mom_nif_swap.py — TEST Option 1 from 2018-2019 deep-dive.

RULE (Option 1):
    At the moment of NON_LONG → long-stretch entry, check Mom30 trailing 60d
    return vs NIFTY trailing 60d return (computed from yesterday's data — no
    lookahead). If Mom30 - NIFTY < -X%, hold NIFTY 50 instead of Mom30 for
    that entire long stretch (until the next NON_LONG day). When swap is
    active, all recovery_allocation rules that would have used Mom30 use
    NIFTY 50 instead. V2 windows always use NIFTY anyway, so the swap is
    effectively pass-through during V2.

We test three thresholds (3% / 5% / 8%) on TWO base configs (C1 V2-only, and
C2 V2+T3 latch). Six variants total + their two baselines = 8 runs.

Output: headline metrics + year-by-year + 2018/2019/2022 breakouts +
        sanity check that swap rarely fires in good years (≤2 firings per
        good year vs ≥3 in 2018/2019).
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import yfinance as yf

from strategy_lab import (
    MacroStrategyLab, RegimeFilter, SignalCombiner,
    USDINRSignal, IndiaVIXSignal, SlowStressSignal, PanicShortSignal,
    _load_data, metrics, apply_annual_tax, build_rbi_repo_rate_series,
    load_nse_index_csv,
)


class MacroStrategyLabSwap(MacroStrategyLab):
    """Extends MacroStrategyLab with Mom30→NIFTY swap rule.

    At entry to each long stretch (state transition from NON_LONG → any long
    state), check whether Mom30 has been lagging NIFTY over the trailing
    `mom_lag_lookback` days by more than `mom_lag_threshold`. If yes, set
    a sticky swap flag for that entire long stretch; the flag resets when
    state returns to NON_LONG.
    """

    def __init__(self, *args, mom_lag_threshold=None, mom_lag_lookback=60, **kwargs):
        super().__init__(*args, **kwargs)
        self.mom_lag_threshold = mom_lag_threshold
        self.mom_lag_lookback = mom_lag_lookback

    def run(self, data):
        # Replicate parent setup
        nifty_returns = data[self.target].pct_change().fillna(0.0)
        if self.long_target in data.columns:
            long_returns = data[self.long_target].pct_change().fillna(0.0)
        else:
            long_returns = nifty_returns
        if self.gold_target in data.columns:
            gold_returns = data[self.gold_target].pct_change().fillna(0.0).clip(-0.5, 0.5)
            gold_available = data[self.gold_target].notna()
        else:
            gold_returns = pd.Series(0.0, index=data.index)
            gold_available = pd.Series(False, index=data.index)

        positions = self.combiner.compute_positions(data)
        nifty_pos = positions["nifty_position"]
        gold_pos = positions["gold_position"].where(gold_available, 0.0)
        is_index = data.index

        # Cash yield
        if self.use_cash_yield:
            repo_rate = build_rbi_repo_rate_series(is_index)
            haircut_repo = (repo_rate - self.cash_yield_haircut_bps / 10000).clip(lower=0)
            daily_cash_yield = haircut_repo / 252
        else:
            daily_cash_yield = pd.Series(0.0, index=is_index)

        # V2
        if self.enable_v2:
            v2_active, v2_flips = self._compute_v2_active(data, is_index)
        else:
            v2_active = pd.Series(False, index=is_index)
            v2_flips = []

        # Recovery latch precompute
        latch_enabled = self.recovery_latch is not None
        if latch_enabled:
            gate = self._g10_gate_series(data, is_index)
            latch_trigger = self._latch_trigger_series(data, is_index)
            sigma_m = (long_returns.rolling(self.vol_window).std() * np.sqrt(252)).shift(1)
            sigma_n = (nifty_returns.rolling(self.vol_window).std() * np.sqrt(252)).shift(1)
            sigma_g = (gold_returns.rolling(self.vol_window).std() * np.sqrt(252)).shift(1)
        else:
            gate = pd.Series(False, index=is_index)
            latch_trigger = pd.Series(False, index=is_index)
            sigma_m = pd.Series(np.nan, index=is_index)
            sigma_n = pd.Series(np.nan, index=is_index)
            sigma_g = pd.Series(np.nan, index=is_index)

        # Swap-rule precompute — use yesterday's data (shift 1) to avoid lookahead
        mom_lookback = data[self.long_target].pct_change(self.mom_lag_lookback).reindex(is_index).shift(1)
        nif_lookback = data[self.target].pct_change(self.mom_lag_lookback).reindex(is_index).shift(1)

        n = len(is_index)
        long_mask = (nifty_pos == 1.0)
        w_mom = np.zeros(n); w_nif = np.zeros(n)
        w_gold = np.zeros(n); w_cash = np.zeros(n)
        lab_state = np.empty(n, dtype=object)
        swap_history = np.zeros(n, dtype=bool)
        state = "NON_LONG"
        swap_active = False
        swap_firings = []  # (date, mom60, nif60, lag)

        for i in range(n):
            today_long = bool(long_mask.iloc[i])
            today_v2 = bool(v2_active.iloc[i]) and today_long
            prev_state = state

            # State transitions
            if not today_long:
                state = "NON_LONG"
            elif today_v2:
                if state == "NON_LONG":
                    state = "RECOVERY"
            else:
                if state == "NON_LONG":
                    state = "RECOVERY"
                if state == "RECOVERY" and latch_enabled and bool(latch_trigger.iloc[i]):
                    state = "ESTABLISHED"
                elif state == "RECOVERY" and not latch_enabled:
                    state = "ESTABLISHED"

            # Update swap flag
            if prev_state == "NON_LONG" and state != "NON_LONG":
                if self.mom_lag_threshold is not None:
                    m60 = mom_lookback.iloc[i]; n60 = nif_lookback.iloc[i]
                    if not (np.isnan(m60) or np.isnan(n60)):
                        swap_active = (m60 - n60) < -self.mom_lag_threshold
                        if swap_active:
                            swap_firings.append((is_index[i], m60, n60, m60 - n60))
                    else:
                        swap_active = False
                else:
                    swap_active = False
            elif state == "NON_LONG":
                swap_active = False
            swap_history[i] = swap_active

            lab_state[i] = state if today_long else "NON_LONG"

            # Weights
            if not today_long:
                if nifty_pos.iloc[i] == -1.0:
                    w_nif[i] = -1.0
                elif gold_pos.iloc[i] == 1.0:
                    w_gold[i] = 1.0
                else:
                    w_cash[i] = 1.0
            elif today_v2:
                w_nif[i] = 1.0
            elif state == "RECOVERY":
                alloc = self.recovery_allocation
                gold_avail_today = bool(gold_available.iloc[i]) if hasattr(gold_available, "iloc") else True
                sm = sigma_m.iloc[i]; sn = sigma_n.iloc[i]; sg = sigma_g.iloc[i]
                gate_on = bool(gate.iloc[i])

                # When swap is active, all Mom30 allocations become NIFTY
                if alloc == "mom_gold_blend":
                    if gate_on and not (np.isnan(sm) or np.isnan(sg) or sm <= 0 or sg <= 0):
                        if swap_active and not (np.isnan(sn) or sn <= 0):
                            inv_n, inv_g = 1.0/sn, 1.0/sg
                            s = inv_n + inv_g
                            w_nif[i] = inv_n / s
                            w_gold[i] = inv_g / s
                        else:
                            inv_m, inv_g = 1.0/sm, 1.0/sg
                            s = inv_m + inv_g
                            w_mom[i] = inv_m / s
                            w_gold[i] = inv_g / s
                    elif (self.vol_target_annual is not None) and (not np.isnan(sm)) and sm > 0:
                        scale = min(self.vol_target_annual / sm, 1.0)
                        if swap_active and not (np.isnan(sn)) and sn > 0:
                            scale_n = min(self.vol_target_annual / sn, 1.0)
                            w_nif[i] = scale_n
                            w_cash[i] = 1.0 - scale_n
                        else:
                            w_mom[i] = scale
                            w_cash[i] = 1.0 - scale
                    else:
                        if swap_active:
                            w_nif[i] = 1.0
                        else:
                            w_mom[i] = 1.0
                elif alloc == "gold_gated_mom":
                    if gate_on and gold_avail_today:
                        w_gold[i] = 1.0
                    else:
                        if swap_active: w_nif[i] = 1.0
                        else: w_mom[i] = 1.0
                elif alloc == "nif_only":
                    w_nif[i] = 1.0
                elif alloc == "gold_only":
                    if gold_avail_today: w_gold[i] = 1.0
                    else: w_cash[i] = 1.0
                elif alloc == "gold_gated_cash":
                    if gate_on and gold_avail_today: w_gold[i] = 1.0
                    else: w_cash[i] = 1.0
                elif alloc == "nif_gold_blend":
                    if gold_avail_today and not (np.isnan(sn) or np.isnan(sg) or sn <= 0 or sg <= 0):
                        inv_n, inv_g = 1.0/sn, 1.0/sg
                        s = inv_n + inv_g
                        w_nif[i] = inv_n / s
                        w_gold[i] = inv_g / s
                    else:
                        w_nif[i] = 1.0
                else:
                    if swap_active: w_nif[i] = 1.0
                    else: w_mom[i] = 1.0
            else:  # ESTABLISHED
                if swap_active:
                    w_nif[i] = 1.0
                else:
                    w_mom[i] = 1.0

        # Costs + PnL
        wdf = pd.DataFrame({"mom": w_mom, "nif": w_nif, "gold": w_gold, "cash": w_cash}, index=is_index)
        cost_mom = wdf["mom"].diff().abs().fillna(0) * (self.long_cost_bps / 10000)
        cost_nif = wdf["nif"].diff().abs().fillna(0) * (self.nifty_cost_bps / 10000)
        cost_gold = wdf["gold"].diff().abs().fillna(0) * (self.gold_cost_bps / 10000)
        cost_cash = wdf["cash"].diff().abs().fillna(0) * (self.cash_cost_bps / 10000)
        total_cost = cost_mom + cost_nif + cost_gold + cost_cash

        pnl_mom = wdf["mom"].shift(1).fillna(0) * long_returns
        pnl_nif = wdf["nif"].shift(1).fillna(0) * nifty_returns
        pnl_gold = wdf["gold"].shift(1).fillna(0) * gold_returns
        pnl_cash = wdf["cash"].shift(1).fillna(0) * daily_cash_yield
        pretax = (pnl_mom + pnl_nif + pnl_gold + pnl_cash - total_cost).rename("strategy_return_pretax")

        if self.apply_tax:
            posttax = apply_annual_tax(pretax.fillna(0.0), tax_rate=self.tax_rate).rename("strategy_return")
        else:
            posttax = pretax.rename("strategy_return")

        results = pd.DataFrame({
            "nifty_return": nifty_returns,
            "gold_return": gold_returns,
            "nifty_position": nifty_pos,
            "gold_position": gold_pos,
            "strategy_return": posttax,
            "strategy_return_pretax": pretax,
        })
        combined = nifty_pos.copy()
        combined[(nifty_pos == 0.0) & (gold_pos == 1.0)] = 2.0
        results["position"] = combined
        return results, {
            "lab_state": pd.Series(lab_state, index=is_index),
            "v2_active": v2_active,
            "swap_active": pd.Series(swap_history, index=is_index),
            "swap_firings": swap_firings,
            "weights": wdf,
        }


def run_variant(name, raw, start, end, *, enable_v2=True, latch=None,
                mom_lag_threshold=None, mom_lag_lookback=60):
    rf = RegimeFilter(window=100)
    combiner = SignalCombiner(regime_filter=rf,
                              rotate_to_gold_on_stress_flat=True,
                              rotate_to_gold_on_panic_short=False,
                              rotate_with_momentum=True,
                              gold_gate_external=True)
    combiner.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    combiner.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    combiner.add_exit_no_cooldown(SlowStressSignal(
        inr_window=20, inr_threshold=0.01,
        vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5))
    combiner.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                       hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)

    s = MacroStrategyLabSwap(
        combiner,
        target="^NSEI", gold_target="GOLDBEES.NS",
        long_target="NIFTYMOM30", long_cost_bps=6,
        nifty_cost_bps=3, gold_cost_bps=5,
        cash_yield_haircut_bps=100,
        apply_tax=True, tax_rate=0.15,
        enable_v2=enable_v2, v2_dd_threshold=0.15, v2_days=60,
        recovery_latch=latch,
        recovery_allocation="mom_gold_blend",
        vol_target_annual=0.15,  # default vol target (will be tightened from C1 later)
        vol_window=60,
        mom_lag_threshold=mom_lag_threshold,
        mom_lag_lookback=mom_lag_lookback,
    )
    df, diag = s.run(raw)
    return df.loc[start:end], diag


def main():
    START, END = "2008-04-01", "2025-12-31"
    raw = _load_data()

    # Get C1 base vol target — match strategy_lab.py convention
    base_df, _ = run_variant("C1_base", raw, START, END, enable_v2=True, latch=None,
                             mom_lag_threshold=None)
    target_vol = float(base_df["strategy_return_pretax"].std() * np.sqrt(252))

    print(f"\nTarget vol (C1 baseline realized): {target_vol*100:.2f}%", file=sys.stderr)

    variants = []
    # C1 family — V2 only, no latch
    variants.append(("C1",         "V2 only (no swap)",              dict(enable_v2=True, latch=None, mom_lag_threshold=None)))
    variants.append(("C1+S3",      "V2 + swap @ 3% Mom30/NIFTY 60d", dict(enable_v2=True, latch=None, mom_lag_threshold=0.03)))
    variants.append(("C1+S5",      "V2 + swap @ 5%",                 dict(enable_v2=True, latch=None, mom_lag_threshold=0.05)))
    variants.append(("C1+S8",      "V2 + swap @ 8%",                 dict(enable_v2=True, latch=None, mom_lag_threshold=0.08)))

    # C2 family — V2 + T3 latch
    LATCH = {"mode": "trend", "x": 0.03}
    variants.append(("C2",         "V2 + T3 (no swap)",              dict(enable_v2=True, latch=LATCH, mom_lag_threshold=None)))
    variants.append(("C2+S3",      "V2 + T3 + swap @ 3%",            dict(enable_v2=True, latch=LATCH, mom_lag_threshold=0.03)))
    variants.append(("C2+S5",      "V2 + T3 + swap @ 5%",            dict(enable_v2=True, latch=LATCH, mom_lag_threshold=0.05)))
    variants.append(("C2+S8",      "V2 + T3 + swap @ 8%",            dict(enable_v2=True, latch=LATCH, mom_lag_threshold=0.08)))

    runs = []
    for name, label, params in variants:
        print(f"Running {name} ...", file=sys.stderr)
        df, diag = run_variant(name, raw, START, END, **params)
        runs.append((name, label, df, diag))

    # Headline
    out = []
    def p(s=""): print(s); out.append(s)

    p("\n" + "=" * 140)
    p("  HEADLINE METRICS (post-tax, 2008-04-01 to 2025-12-31)")
    p("=" * 140)
    p(f"  {'Cfg':<8} {'Label':<38} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} {'ΔCAGR':>9} {'ΔSharpe':>9} {'Swap':>7}")
    p("  " + "-" * 8 + " " + "-" * 38 + " " + "-" * 9 + " " + "-" * 8 + " " + "-" * 8 + " " + "-" * 9 + " " + "-" * 9 + " " + "-" * 9 + " " + "-" * 7)

    c1_m = None; c2_m = None
    for name, label, df, diag in runs:
        m = metrics(df["strategy_return"])
        if name == "C1": c1_m = m
        if name == "C2": c2_m = m
        base_m = c2_m if name.startswith("C2") else c1_m
        n_swap_days = int(diag["swap_active"].loc[df.index].sum())
        n_swap_fires = len(diag["swap_firings"])
        if base_m is None or name in ("C1", "C2"):
            p(f"  {name:<8} {label:<38} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {'—':>9} {'—':>9} {n_swap_fires:>5}f")
        else:
            dc = m["cagr"] - base_m["cagr"]
            ds = m["sharpe"] - base_m["sharpe"]
            p(f"  {name:<8} {label:<38} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {dc*100:+8.2f}pp {ds:+9.3f} {n_swap_fires:>5}f")
    p()

    # Year-by-year
    p("=" * 140)
    p("  YEAR-BY-YEAR (post-tax, %)")
    p("=" * 140)
    years = sorted(set(runs[0][2].index.year))
    hdr = f"  {'Year':<6}"
    for name, label, df, diag in runs:
        hdr += f" {name:>9}"
    hdr += f" {'NIFTY':>9}"
    p(hdr)
    p("  " + "-" * 6 + (" " + "-" * 9) * (len(runs) + 1))

    nifty_close = raw["^NSEI"].loc[START:END]
    for y in years:
        row = f"  {y:<6}"
        for name, label, df, diag in runs:
            s = df["strategy_return"][df.index.year == y]
            yr = float((1 + s).prod() - 1) if len(s) else 0.0
            row += f" {yr*100:>+8.2f}%"
        nifty_yr = nifty_close[nifty_close.index.year == y]
        if len(nifty_yr) > 1:
            ny = float(nifty_yr.iloc[-1] / nifty_yr.iloc[0] - 1)
        else:
            ny = 0.0
        row += f" {ny*100:>+8.2f}%"
        p(row)
    p()

    # 2018-2019 vs NIFTY focus
    p("=" * 140)
    p("  KEY YEAR FOCUS — 2018, 2019, 2022 (vs NIFTY 50 B&H)")
    p("=" * 140)
    p(f"  {'Year':<6} {'NIFTY':>9} " + " ".join(f"{name:>10}" for name, *_ in runs))
    p(f"  {'':6} {'':>9} " + " ".join(f"{'(Δ vs NIFTY)':>10}" for _ in runs))
    p("  " + "-" * 6 + " " + "-" * 9 + " " + " ".join("-" * 10 for _ in runs))
    for y in [2018, 2019, 2022, 2008, 2009, 2014, 2017, 2020, 2021, 2023, 2024]:
        nifty_yr = nifty_close[nifty_close.index.year == y]
        if not len(nifty_yr): continue
        ny = float(nifty_yr.iloc[-1] / nifty_yr.iloc[0] - 1)
        row = f"  {y:<6} {ny*100:>+8.2f}%"
        for name, label, df, diag in runs:
            s = df["strategy_return"][df.index.year == y]
            yr = float((1 + s).prod() - 1) if len(s) else 0.0
            diff = yr - ny
            row += f" {yr*100:>+5.1f}/{diff*100:>+3.0f}"
        p(row)
    p()

    # Swap firings detail — for the most promising config(s)
    p("=" * 140)
    p("  SWAP FIRINGS DETAIL — C1+S3 (3% threshold)")
    p("=" * 140)
    p(f"  {'Date':<12} {'Mom30 60d':>11} {'NIFTY 60d':>11} {'Lag':>8}")
    p("  " + "-" * 12 + " " + "-" * 11 + " " + "-" * 11 + " " + "-" * 8)
    s_fires = [r for r in runs if r[0] == "C1+S3"][0][3]["swap_firings"]
    for date, m60, n60, lag in s_fires:
        p(f"  {date.strftime('%Y-%m-%d')} {m60*100:+10.2f}% {n60*100:+10.2f}% {lag*100:+7.2f}%")
    p()

    # Save
    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "test_mom_nif_swap.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()

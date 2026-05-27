"""
oracle_2018_2019_nifty_swap.py — ORACLE COUNTERFACTUAL.

Question: If we knew in advance that 2018 and 2019 were going to be bad Mom30
years and we just held NIFTY 50 instead of Mom30 during those two years
(keeping all current entry/exit timing identical), how much would 2018-2019
improve, and what would the full 2008-2025 numbers look like?

This is a HINDSIGHT-ONLY test — not a deployable rule. The point is to set
an upper bound on how much asset substitution could have helped, so we
know whether the bleed is "an unsolvable factor problem" or "a solvable
asset-choice problem we just haven't figured out the timing for."

Variants tested:
  C1            production (V2 only)
  C1_oracle1819 same as C1 but long_target = ^NSEI for all of 2018+2019
  C1_oracle18only         "                      "    for 2018 only
  C1_oracle19only         "                      "    for 2019 only
  C1_oracle_struct  long_target = ^NSEI for 2018+2019+2022+2025 (all 4 bad years)
  NIFTY_BH_1819 buy-and-hold NIFTY 50 for entire 2018+2019 (no strategy)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from strategy_lab import (
    MacroStrategyLab, RegimeFilter, SignalCombiner,
    USDINRSignal, IndiaVIXSignal, SlowStressSignal, PanicShortSignal,
    _load_data, metrics, apply_annual_tax, build_rbi_repo_rate_series,
)


class MacroStrategyLabOracle(MacroStrategyLab):
    """Extends MacroStrategyLab with an oracle hindsight rule:
    if today's date.year is in oracle_years, replace the long-side asset
    return with the NIFTY 50 return (i.e. hold NIFTY 50 instead of Mom30
    on every LONG day in those years). Costs are kept at long_cost_bps
    (3 bps to be fair to the underlying flow)."""

    def __init__(self, *args, oracle_years=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.oracle_years = set(oracle_years)

    def run(self, data):
        nifty_returns = data[self.target].pct_change().fillna(0.0)
        long_returns_native = data[self.long_target].pct_change().fillna(0.0)
        # Oracle swap: replace long_returns with NIFTY in oracle years
        long_returns = long_returns_native.copy()
        for y in self.oracle_years:
            mask = (long_returns.index.year == y)
            long_returns.loc[mask] = nifty_returns.loc[mask]

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

        if self.use_cash_yield:
            repo_rate = build_rbi_repo_rate_series(is_index)
            haircut_repo = (repo_rate - self.cash_yield_haircut_bps / 10000).clip(lower=0)
            daily_cash_yield = haircut_repo / 252
        else:
            daily_cash_yield = pd.Series(0.0, index=is_index)

        if self.enable_v2:
            v2_active, v2_flips = self._compute_v2_active(data, is_index)
        else:
            v2_active = pd.Series(False, index=is_index)
            v2_flips = []

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

        n = len(is_index)
        long_mask = (nifty_pos == 1.0)
        w_mom = np.zeros(n); w_nif = np.zeros(n)
        w_gold = np.zeros(n); w_cash = np.zeros(n)
        lab_state = np.empty(n, dtype=object)
        state = "NON_LONG"

        for i in range(n):
            today_long = bool(long_mask.iloc[i])
            today_v2 = bool(v2_active.iloc[i]) and today_long

            if not today_long:
                state = "NON_LONG"
            elif today_v2:
                if state == "NON_LONG": state = "RECOVERY"
            else:
                if state == "NON_LONG": state = "RECOVERY"
                if state == "RECOVERY" and latch_enabled and bool(latch_trigger.iloc[i]):
                    state = "ESTABLISHED"
                elif state == "RECOVERY" and not latch_enabled:
                    state = "ESTABLISHED"
            lab_state[i] = state if today_long else "NON_LONG"

            if not today_long:
                if nifty_pos.iloc[i] == -1.0: w_nif[i] = -1.0
                elif gold_pos.iloc[i] == 1.0: w_gold[i] = 1.0
                else: w_cash[i] = 1.0
            elif today_v2:
                w_nif[i] = 1.0
            elif state == "RECOVERY":
                sm = sigma_m.iloc[i]; sg = sigma_g.iloc[i]
                gate_on = bool(gate.iloc[i])
                if gate_on and not (np.isnan(sm) or np.isnan(sg) or sm <= 0 or sg <= 0):
                    inv_m, inv_g = 1.0/sm, 1.0/sg
                    s = inv_m + inv_g
                    w_mom[i] = inv_m / s
                    w_gold[i] = inv_g / s
                elif (self.vol_target_annual is not None) and (not np.isnan(sm)) and sm > 0:
                    scale = min(self.vol_target_annual / sm, 1.0)
                    w_mom[i] = scale
                    w_cash[i] = 1.0 - scale
                else:
                    w_mom[i] = 1.0
            else:
                w_mom[i] = 1.0

        wdf = pd.DataFrame({"mom": w_mom, "nif": w_nif, "gold": w_gold, "cash": w_cash}, index=is_index)
        cost_mom = wdf["mom"].diff().abs().fillna(0) * (self.long_cost_bps / 10000)
        cost_nif = wdf["nif"].diff().abs().fillna(0) * (self.nifty_cost_bps / 10000)
        cost_gold = wdf["gold"].diff().abs().fillna(0) * (self.gold_cost_bps / 10000)
        cost_cash = wdf["cash"].diff().abs().fillna(0) * (self.cash_cost_bps / 10000)
        total_cost = cost_mom + cost_nif + cost_gold + cost_cash

        # PnL uses long_returns (already swapped in oracle years)
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
        return results, {"lab_state": pd.Series(lab_state, index=is_index),
                         "v2_active": v2_active, "weights": wdf}


def run_oracle(name, raw, start, end, oracle_years=()):
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

    s = MacroStrategyLabOracle(
        combiner,
        target="^NSEI", gold_target="GOLDBEES.NS",
        long_target="NIFTYMOM30", long_cost_bps=6,
        nifty_cost_bps=3, gold_cost_bps=5,
        cash_yield_haircut_bps=100,
        apply_tax=True, tax_rate=0.15,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
        recovery_latch=None,
        recovery_allocation="mom_gold_blend",
        vol_target_annual=0.15,
        vol_window=60,
        oracle_years=oracle_years,
    )
    df, diag = s.run(raw)
    return df.loc[start:end], diag


def main():
    START, END = "2008-04-01", "2025-12-31"
    raw = _load_data()

    variants = [
        ("C1",               "Production (V2 only, no oracle)",        ()),
        ("C1_O18",           "Oracle swap 2018 only",                  (2018,)),
        ("C1_O19",           "Oracle swap 2019 only",                  (2019,)),
        ("C1_O1819",         "Oracle swap 2018+2019",                  (2018, 2019)),
        ("C1_OSTRUCT",       "Oracle swap 2018+19+22+25 (all bad)",   (2018, 2019, 2022, 2025)),
    ]

    runs = []
    for name, label, oy in variants:
        print(f"Running {name} ({label}) ...", file=sys.stderr)
        df, diag = run_oracle(name, raw, START, END, oracle_years=oy)
        runs.append((name, label, df, diag))

    # Also compute pure NIFTY B&H for 2018-2019 (replacement test)
    nifty_close = raw["^NSEI"].loc[START:END]
    nifty_ret = nifty_close.pct_change().fillna(0.0)

    out = []
    def p(s=""): print(s); out.append(s)

    p("\n" + "=" * 140)
    p("  ORACLE COUNTERFACTUAL — what's the UPPER BOUND on 2018-2019 improvement?")
    p("=" * 140)
    p()
    p("  Rule: keep all C1 entry/exit timing identical, but on every LONG day in")
    p("        oracle years, hold NIFTY 50 instead of Mom30. (Hindsight only —")
    p("        not deployable.) Costs identical to base.")
    p()

    p("=" * 140)
    p("  HEADLINE METRICS (post-tax, full sample 2008-04-01 → 2025-12-31)")
    p("=" * 140)
    p(f"  {'Cfg':<14} {'Label':<42} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} {'ΔCAGR vs C1':>12}")
    p("  " + "-"*14 + " " + "-"*42 + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " + "-"*12)
    c1_m = None
    for name, label, df, diag in runs:
        m = metrics(df["strategy_return"])
        if name == "C1": c1_m = m
        if c1_m is None or name == "C1":
            p(f"  {name:<14} {label:<42} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {'—':>12}")
        else:
            dc = m["cagr"] - c1_m["cagr"]
            p(f"  {name:<14} {label:<42} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {dc*100:+11.2f}pp")
    p()

    p("=" * 140)
    p("  YEAR-BY-YEAR (post-tax, %) — focus on 2018, 2019, 2022, 2025")
    p("=" * 140)
    years = sorted(set(runs[0][2].index.year))
    hdr = f"  {'Year':<6}"
    for name, *_ in runs: hdr += f" {name:>12}"
    hdr += f" {'NIFTY BH':>10}"
    p(hdr)
    p("  " + "-"*6 + (" " + "-"*12) * len(runs) + " " + "-"*10)
    for y in years:
        row = f"  {y:<6}"
        for name, label, df, diag in runs:
            s = df["strategy_return"][df.index.year == y]
            yr = float((1 + s).prod() - 1) if len(s) else 0.0
            row += f" {yr*100:>+11.2f}%"
        nifty_yr = nifty_close[nifty_close.index.year == y]
        if len(nifty_yr) > 1:
            ny = float(nifty_yr.iloc[-1] / nifty_yr.iloc[0] - 1)
        else:
            ny = 0.0
        row += f" {ny*100:>+9.2f}%"
        p(row)
    p()

    # Drill into 2018-2019 specifically
    p("=" * 140)
    p("  2018-2019 ISOLATED IMPACT (compound return of just those two years)")
    p("=" * 140)
    p(f"  {'Variant':<14} {'Label':<42} {'2018+19 cum':>14} {'vs C1':>10}")
    p("  " + "-"*14 + " " + "-"*42 + " " + "-"*14 + " " + "-"*10)
    c1_cum = None
    for name, label, df, diag in runs:
        s = df["strategy_return"][df.index.year.isin([2018, 2019])]
        cum = float((1 + s).prod() - 1)
        if name == "C1": c1_cum = cum
        if c1_cum is None or name == "C1":
            p(f"  {name:<14} {label:<42} {cum*100:>+13.2f}% {'—':>10}")
        else:
            d = cum - c1_cum
            p(f"  {name:<14} {label:<42} {cum*100:>+13.2f}% {d*100:>+9.2f}pp")
    # NIFTY 2-yr cum
    n_2yr = nifty_ret[nifty_ret.index.year.isin([2018, 2019])]
    n_cum = float((1 + n_2yr).prod() - 1)
    p(f"  {'NIFTY B&H':<14} {'NIFTY 50 buy-and-hold for 2018+2019':<42} {n_cum*100:>+13.2f}% {(n_cum-c1_cum)*100:>+9.2f}pp")
    p()

    # Long days in 2018-2019 — where the oracle actually substituted
    p("=" * 140)
    p("  HOW MANY DAYS the oracle actually substituted")
    p("=" * 140)
    base_df, base_diag = runs[0][2], runs[0][3]
    for y in [2018, 2019, 2022, 2025]:
        days_y = base_df.index[base_df.index.year == y]
        long_d = int((base_df.loc[days_y, "nifty_position"] == 1.0).sum())
        flat_d = int((base_df.loc[days_y, "nifty_position"] == 0.0).sum())
        # Compute pure asset return for those LONG days
        mom_y = raw["NIFTYMOM30"].pct_change().fillna(0.0).reindex(days_y)
        nif_y = raw["^NSEI"].pct_change().fillna(0.0).reindex(days_y)
        long_mask = (base_df.loc[days_y, "nifty_position"] == 1.0)
        mom_long_cum = float((1 + mom_y[long_mask]).prod() - 1)
        nif_long_cum = float((1 + nif_y[long_mask]).prod() - 1)
        diff = nif_long_cum - mom_long_cum
        p(f"  {y}: {long_d} LONG days  →  Mom30-only cum on LONG days: {mom_long_cum*100:+6.2f}%   "
          f"NIFTY-only cum on LONG days: {nif_long_cum*100:+6.2f}%   diff: {diff*100:+5.2f}pp")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "oracle_2018_2019.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()

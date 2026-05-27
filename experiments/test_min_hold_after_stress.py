"""
test_min_hold_after_stress.py — minimum-hold rule after re-entering long
post slow-stress, extended with R3/R4/escalation override variants.

Base rule (Lock Nd): After slow-stress fires, suppress subsequent slow-stress
firings for the next N trading days. Once the lock window expires,
slow-stress can fire again normally. Effect: after a stress-flat ends and
the strategy re-enters long, it cannot be re-flatted by slow-stress for N
days. Other exit signals (bear regime, panic-short) still work normally.

Extension variants on top of Lock 5d:
  L5 + R3:  on stress-fire days (not suppressed by L5), if NIFTY > 100-DMA
            hold NIFTY 50 instead of cash. If bear regime, cash as today.
  L5 + R4:  intensity-scaled de-risk on stress-fire days. De-risk fraction
            = clip((VIX 90d z − 1.5) / 2.0, 0, 1). At z=1.5 → 0% flat (stay
            long), at z=3.5 → full flat. De-risked portion → cash.
  L5 + esc: escalation override on top of L5. A raw fire within the lock
            window is allowed if its z exceeds the prior unsuppressed
            fire's z by ≥ 0.5.
  L5 + R3 + esc: combines L5+R3 with the escalation override.

Pre-specified parameters (no tuning to 2013/2019/2022). Disqualification
criteria: any variant that gives back > 1pp in 2008, September 2018, 2020,
or 2021 vs C1 baseline is flagged.

Original strategy.py is NOT modified. Self-contained experiment.
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


# ============================================================================
# SIGNAL CLASSES — lock + optional escalation override
# ============================================================================

class SlowStressWithLockSignal(SlowStressSignal):
    """SlowStress with N-day lock after each firing event (no escalation).

    After a fire, suppress subsequent raw fires for the next `lock_days`
    trading days. Continuous runs (active fires) are not suppressed.
    """
    name = "slow_stress_locked"

    def __init__(self, lock_days=10, **kwargs):
        super().__init__(**kwargs)
        self.lock_days = lock_days

    def compute(self, data):
        raw = super().compute(data)
        raw_fire = (raw < 0).values
        n = len(raw)
        out = np.zeros(n)
        last_unsuppressed_fire = -10**9
        in_active_run = False
        for i in range(n):
            if raw_fire[i]:
                if in_active_run or (i - last_unsuppressed_fire > self.lock_days):
                    out[i] = -1.0
                    last_unsuppressed_fire = i
                    in_active_run = True
            else:
                if in_active_run:
                    in_active_run = False
        return pd.Series(out, index=raw.index, name=self.name)


class SlowStressWithLockAndEscalation(SlowStressSignal):
    """SlowStress with N-day lock + optional escalation override.

    Standard lock: after each unsuppressed firing event, suppress subsequent
    raw fires for the next `lock_days` trading days.

    Escalation override: if `escalation_z_delta` is set, a raw fire within
    the lock window is allowed if its current z-score is ≥ (prior unsuppressed
    fire's z-score + escalation_z_delta).
    """
    name = "slow_stress_lock_esc"

    def __init__(self, lock_days=5, escalation_z_delta=None, **kwargs):
        super().__init__(**kwargs)
        self.lock_days = lock_days
        self.escalation_z_delta = escalation_z_delta

    def compute(self, data):
        inr_w = data["INR=X"].pct_change(self.inr_window) > self.inr_threshold
        vix = data["^INDIAVIX"]
        z_series = (vix - vix.rolling(self.vix_z_window).mean()) / vix.rolling(self.vix_z_window).std()
        vix_mom = vix - vix.shift(self.vix_mom_window)
        raw_fires = (inr_w & (z_series > self.vix_z_threshold) & (vix_mom > 0)).fillna(False)

        n = len(data)
        out = np.zeros(n)
        raw_fire_vals = raw_fires.values
        z_vals = z_series.values

        last_unsuppressed_fire = -10**9
        last_fire_z = None
        in_active_run = False

        for i in range(n):
            if raw_fire_vals[i]:
                current_z = z_vals[i]
                allow = False
                if in_active_run:
                    allow = True
                elif i - last_unsuppressed_fire > self.lock_days:
                    allow = True
                elif self.escalation_z_delta is not None and last_fire_z is not None:
                    if not np.isnan(current_z) and current_z >= last_fire_z + self.escalation_z_delta:
                        allow = True

                if allow:
                    out[i] = -1.0
                    last_unsuppressed_fire = i
                    if not np.isnan(current_z):
                        last_fire_z = current_z
                    in_active_run = True
            else:
                if in_active_run:
                    in_active_run = False

        return pd.Series(out, index=data.index, name=self.name)


# ============================================================================
# STRATEGY CLASS — supports R3 (NIFTY-on-stress-flat) and R4 (intensity)
# ============================================================================

class MacroStrategyLabRules(MacroStrategyLab):
    """Lab strategy with R3/R4 overrides on stress-fire days.

    R3 (r3_uptrend_nifty): on stress-fire days with NIFTY > 100-DMA, hold
        NIFTY 50 instead of going to cash. If bear regime, cash as default.

    R4 (r4_intensity_scaled): on stress-fire days, de-risk fraction is
        clip((vix_z − r4_z_floor) / (r4_z_ceiling − r4_z_floor), 0, 1).
        Apply to long-side asset (Mom30); de-risked portion → cash.
    """

    def __init__(self, *args,
                 stress_fires_series=None,
                 vix_z_series=None,
                 bull_mask_series=None,
                 r3_uptrend_nifty=False,
                 r4_intensity_scaled=False,
                 r4_z_floor=1.5,
                 r4_z_ceiling=3.5,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.stress_fires_series = stress_fires_series
        self.vix_z_series = vix_z_series
        self.bull_mask_series = bull_mask_series
        self.r3_uptrend_nifty = r3_uptrend_nifty
        self.r4_intensity_scaled = r4_intensity_scaled
        self.r4_z_floor = r4_z_floor
        self.r4_z_ceiling = r4_z_ceiling

    def run(self, data):
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

        n = len(is_index)
        long_mask = (nifty_pos == 1.0)
        w_mom = np.zeros(n); w_nif = np.zeros(n)
        w_gold = np.zeros(n); w_cash = np.zeros(n)
        lab_state = np.empty(n, dtype=object)
        state = "NON_LONG"

        # Pre-align overlay series
        if self.stress_fires_series is not None:
            sf = self.stress_fires_series.reindex(is_index, fill_value=0.0)
            stress_mask = (sf < 0).values
        else:
            stress_mask = np.zeros(n, dtype=bool)

        if self.vix_z_series is not None:
            z_vals = self.vix_z_series.reindex(is_index).values
        else:
            z_vals = np.full(n, np.nan)

        if self.bull_mask_series is not None:
            bull_vals = self.bull_mask_series.reindex(is_index, fill_value=False).values
        else:
            bull_vals = np.zeros(n, dtype=bool)

        for i in range(n):
            today_long = bool(long_mask.iloc[i])
            today_v2 = bool(v2_active.iloc[i]) and today_long

            if not today_long:
                state = "NON_LONG"
            elif today_v2:
                if state == "NON_LONG":
                    state = "RECOVERY"
            else:
                if state == "NON_LONG":
                    state = "RECOVERY"
                state = "ESTABLISHED"
            lab_state[i] = state if today_long else "NON_LONG"

            if not today_long:
                if nifty_pos.iloc[i] == -1.0:
                    w_nif[i] = -1.0
                elif gold_pos.iloc[i] == 1.0:
                    w_gold[i] = 1.0
                else:
                    # cash slot — check for R3/R4 overrides on stress-fire days
                    is_stress = stress_mask[i]
                    if is_stress and self.r3_uptrend_nifty and bull_vals[i]:
                        w_nif[i] = 1.0
                    elif is_stress and self.r4_intensity_scaled:
                        z_today = z_vals[i]
                        if np.isnan(z_today):
                            de_risk = 1.0
                        else:
                            denom = (self.r4_z_ceiling - self.r4_z_floor)
                            de_risk = float(np.clip((z_today - self.r4_z_floor) / denom, 0, 1))
                        w_mom[i] = 1.0 - de_risk
                        w_cash[i] = de_risk
                    else:
                        w_cash[i] = 1.0
            elif today_v2:
                w_nif[i] = 1.0
            else:
                w_mom[i] = 1.0

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
        return results


# ============================================================================
# RUNNERS
# ============================================================================

def build_combiner(slow_stress_signal):
    rf = RegimeFilter(window=100)
    c = SignalCombiner(regime_filter=rf,
                       rotate_to_gold_on_stress_flat=True,
                       rotate_to_gold_on_panic_short=False,
                       rotate_with_momentum=True,
                       gold_gate_external=True)
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    c.add_exit_no_cooldown(slow_stress_signal)
    c.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)
    return c


def run(slow_stress, raw, start, end):
    """Legacy plain runner (no R3/R4)."""
    combiner = build_combiner(slow_stress)
    s = MacroStrategyLab(
        combiner,
        target="^NSEI", gold_target="GOLDBEES.NS",
        long_target="NIFTYMOM30", long_cost_bps=6,
        nifty_cost_bps=3, gold_cost_bps=5,
        cash_yield_haircut_bps=100,
        apply_tax=True, tax_rate=0.15,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
        recovery_latch=None, recovery_allocation="mom_gold_blend",
        vol_target_annual=0.15, vol_window=60,
    )
    result = s.run(raw)
    df, diag = result if isinstance(result, tuple) else (result, {})
    return df.loc[start:end], diag


def run_with_rules(raw, start, end, *, lock_days=5, escalation_z_delta=None,
                   r3=False, r4=False):
    """Run a variant with optional lock/escalation/R3/R4."""
    slow_stress = SlowStressWithLockAndEscalation(
        lock_days=lock_days, escalation_z_delta=escalation_z_delta,
        inr_window=20, inr_threshold=0.01,
        vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)

    # Pre-compute fires (lock-aware), vix z-score, bull mask
    fires = slow_stress.compute(raw)
    vix = raw["^INDIAVIX"]
    vix_z = (vix - vix.rolling(90).mean()) / vix.rolling(90).std()
    nifty = raw["^NSEI"].ffill()
    bull_mask = nifty > nifty.rolling(100).mean()

    combiner = build_combiner(slow_stress)
    s = MacroStrategyLabRules(
        combiner,
        target="^NSEI", gold_target="GOLDBEES.NS",
        long_target="NIFTYMOM30", long_cost_bps=6,
        nifty_cost_bps=3, gold_cost_bps=5,
        cash_yield_haircut_bps=100,
        apply_tax=True, tax_rate=0.15,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
        recovery_latch=None, recovery_allocation="mom_gold_blend",
        vol_target_annual=0.15, vol_window=60,
        stress_fires_series=fires,
        vix_z_series=vix_z,
        bull_mask_series=bull_mask,
        r3_uptrend_nifty=r3,
        r4_intensity_scaled=r4,
    )
    df = s.run(raw)
    n_fires = int((fires.loc[start:end] < 0).sum())
    return df.loc[start:end], n_fires


def main():
    START, END = "2008-04-01", "2025-12-31"
    raw = _load_data()

    # ----- Existing baseline + lock variants (kept) ---------------------
    print("Running baseline + lock-only variants ...", file=sys.stderr)
    base_ss = SlowStressSignal(inr_window=20, inr_threshold=0.01,
                                vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
    df_base, _ = run(base_ss, raw, START, END)
    n_fires_base = int((base_ss.compute(raw).loc[START:END] < 0).sum())

    df_l5, n_l5 = run_with_rules(raw, START, END, lock_days=5)
    df_l10, n_l10 = run_with_rules(raw, START, END, lock_days=10)
    df_l20, n_l20 = run_with_rules(raw, START, END, lock_days=20)

    # ----- New variants on top of L5 ------------------------------------
    print("Running L5 + R3 ...", file=sys.stderr)
    df_l5_r3, n_l5_r3 = run_with_rules(raw, START, END, lock_days=5, r3=True)
    print("Running L5 + R4 ...", file=sys.stderr)
    df_l5_r4, n_l5_r4 = run_with_rules(raw, START, END, lock_days=5, r4=True)
    print("Running L5 + escalation override ...", file=sys.stderr)
    df_l5_esc, n_l5_esc = run_with_rules(raw, START, END, lock_days=5, escalation_z_delta=0.5)
    print("Running L5 + R3 + escalation override ...", file=sys.stderr)
    df_l5_r3_esc, n_l5_r3_esc = run_with_rules(raw, START, END, lock_days=5,
                                                escalation_z_delta=0.5, r3=True)

    variants = [
        ("C1 baseline",   df_base,        n_fires_base),
        ("Lock 5d",       df_l5,          n_l5),
        ("Lock 10d",      df_l10,         n_l10),
        ("Lock 20d",      df_l20,         n_l20),
        ("L5 + R3",       df_l5_r3,       n_l5_r3),
        ("L5 + R4",       df_l5_r4,       n_l5_r4),
        ("L5 + esc",      df_l5_esc,      n_l5_esc),
        ("L5 + R3 + esc", df_l5_r3_esc,   n_l5_r3_esc),
    ]

    out = []
    def p(s=""): print(s); out.append(s)

    p("\n" + "=" * 150)
    p("  EXTENDED VARIANTS — L5 baseline + R3 / R4 / escalation override")
    p("=" * 150)
    p()
    p("  Rules (all pre-specified — no tuning to 2013/2019/2022):")
    p("    Lock Nd:  after each unsuppressed slow-stress fire, suppress next N trading days of raw fires.")
    p("    R3:       on stress-fire days with NIFTY > 100-DMA, hold NIFTY 50 instead of cash.")
    p("              If NIFTY < 100-DMA (bear), full cash as today.")
    p("    R4:       de-risk fraction = clip((vix_z - 1.5) / 2.0, 0, 1) on stress-fire days.")
    p("              Long-side asset is scaled down by this fraction; de-risked portion → cash.")
    p("    esc:      escalation override — allow a fire within lock window if its z exceeds the")
    p("              prior unsuppressed fire's z by ≥ 0.5.")
    p()

    p("=" * 150)
    p("  HEADLINE METRICS (post-tax, full sample 2008-04-01 → 2025-12-31)")
    p("=" * 150)
    p(f"  {'Variant':<18} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} {'Vol':>8} {'SS fires':>9} "
      f"{'ΔCAGR vs C1':>13} {'ΔCAGR vs L5':>13}")
    p("  " + "-"*18 + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " + "-"*8 + " " + "-"*9 + " "
      + "-"*13 + " " + "-"*13)
    base_m = metrics(df_base["strategy_return"])
    l5_m = metrics(df_l5["strategy_return"])
    for name, df, n_fires in variants:
        m = metrics(df["strategy_return"])
        dc1 = m["cagr"] - base_m["cagr"]
        dl5 = m["cagr"] - l5_m["cagr"]
        c1_str = "—" if name == "C1 baseline" else f"{dc1*100:+10.2f}pp"
        l5_str = "—" if name == "Lock 5d" else f"{dl5*100:+10.2f}pp"
        p(f"  {name:<18} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% "
          f"{m['vol']*100:>7.2f}% {n_fires:>9d} {c1_str:>13} {l5_str:>13}")
    p()

    # Year-by-year for all variants
    p("=" * 150)
    p("  YEAR-BY-YEAR (post-tax %)")
    p("=" * 150)
    nifty_close = raw["^NSEI"].loc[START:END]
    hdr = f"  {'Year':<6}"
    for name, _, _ in variants:
        hdr += f" {name:>14}"
    hdr += f" {'NIFTY':>9}"
    p(hdr)
    p("  " + "-"*6 + (" " + "-"*14) * len(variants) + " " + "-"*9)
    for y in sorted(set(df_base.index.year)):
        row = f"  {y:<6}"
        for name, df, _ in variants:
            s = df["strategy_return"][df.index.year == y]
            yr = float((1+s).prod()-1)*100 if len(s) else 0
            row += f" {yr:>+12.2f}%"
        ny = nifty_close[nifty_close.index.year == y]
        nv = float(ny.iloc[-1]/ny.iloc[0]-1)*100 if len(ny)>1 else 0
        row += f" {nv:>+7.2f}%"
        p(row)
    p()

    # Δ vs L5 year-by-year (focus)
    p("=" * 150)
    p("  Δ vs LOCK 5d (year-by-year, pp) — positive = variant outperformed L5 that year")
    p("=" * 150)
    extension_variants = [(n, d) for n, d, _ in variants if n.startswith("L5 ")]
    hdr = f"  {'Year':<6}"
    for name, _ in extension_variants:
        hdr += f" {name:>14}"
    p(hdr)
    p("  " + "-"*6 + (" " + "-"*14) * len(extension_variants))
    for y in sorted(set(df_base.index.year)):
        l5_yr = float((1+df_l5["strategy_return"][df_l5.index.year == y]).prod()-1)*100
        row = f"  {y:<6}"
        for name, df in extension_variants:
            v_yr = float((1+df["strategy_return"][df.index.year == y]).prod()-1)*100
            row += f" {(v_yr-l5_yr):>+12.2f}pp"
        p(row)
    p()

    # Disqualification check
    p("=" * 150)
    p("  DISQUALIFICATION CHECK — give-back > 1pp in {2008, 2018-Sep, 2020, 2021} vs C1 baseline")
    p("=" * 150)
    p()

    def period_return(df, year=None, month=None):
        if month is None:
            mask = (df.index.year == year)
        else:
            mask = (df.index.year == year) & (df.index.month == month)
        s = df["strategy_return"][mask]
        return float((1+s).prod() - 1) * 100 if len(s) else 0.0

    check_periods = [
        ("2008",       lambda d: period_return(d, year=2008)),
        ("2018-Sep",   lambda d: period_return(d, year=2018, month=9)),
        ("2020",       lambda d: period_return(d, year=2020)),
        ("2021",       lambda d: period_return(d, year=2021)),
    ]

    p(f"  {'Variant':<18} " + " ".join(f"{lbl:>13}" for lbl, _ in check_periods) + "    Verdict")
    p("  " + "-"*18 + " " + " ".join("-"*13 for _ in check_periods) + "    " + "-"*30)
    base_vals = {lbl: fn(df_base) for lbl, fn in check_periods}
    for name, df, _ in variants:
        if name == "C1 baseline":
            row_vals = "  ".join(f"{base_vals[lbl]:>+11.2f}%" for lbl, _ in check_periods)
            p(f"  {name:<18} {row_vals}    BASELINE")
            continue
        deltas = []
        disqualifying = []
        for lbl, fn in check_periods:
            v = fn(df)
            d = v - base_vals[lbl]
            deltas.append((lbl, v, d))
            if d < -1.0:  # gave back > 1pp
                disqualifying.append(f"{lbl} ({d:+.2f}pp)")
        row_vals = "  ".join(f"{v:>+5.2f} ({d:+5.2f})" for lbl, v, d in deltas)
        verdict = "DISQUALIFIED: " + ", ".join(disqualifying) if disqualifying else "PASS"
        p(f"  {name:<18} {row_vals}    {verdict}")
    p()
    p("  (Each cell shows: variant_return (Δ_vs_C1_baseline). Disqualification threshold: Δ < -1.0pp.)")
    p()

    # Specific hypotheses check
    p("=" * 150)
    p("  HYPOTHESIS CHECKS")
    p("=" * 150)
    p()
    p("  H1 (escalation override): does it shrink the 2013 / 2022 cost vs L5?")
    for y in [2013, 2022]:
        l5_yr = period_return(df_l5, year=y)
        esc_yr = period_return(df_l5_esc, year=y)
        r3esc_yr = period_return(df_l5_r3_esc, year=y)
        p(f"    {y}: L5={l5_yr:+6.2f}%   L5+esc={esc_yr:+6.2f}% (Δ {(esc_yr-l5_yr):+5.2f}pp)   "
          f"L5+R3+esc={r3esc_yr:+6.2f}% (Δ {(r3esc_yr-l5_yr):+5.2f}pp)")
    p()
    p("  H2 (R3 NIFTY-uptrend): does it grow the 2019 save vs L5?")
    y19_l5 = period_return(df_l5, year=2019)
    y19_r3 = period_return(df_l5_r3, year=2019)
    y19_r3esc = period_return(df_l5_r3_esc, year=2019)
    p(f"    2019: L5={y19_l5:+6.2f}%   L5+R3={y19_r3:+6.2f}% (Δ {(y19_r3-y19_l5):+5.2f}pp)   "
      f"L5+R3+esc={y19_r3esc:+6.2f}% (Δ {(y19_r3esc-y19_l5):+5.2f}pp)")
    p()
    p("  H3 (R4 intensity scaling): does it improve 2019 with less cost on other years?")
    y19_r4 = period_return(df_l5_r4, year=2019)
    cum_full = lambda d: ((1+d["strategy_return"]).prod() - 1) * 100
    full_l5 = metrics(df_l5["strategy_return"])["cagr"]*100
    full_r4 = metrics(df_l5_r4["strategy_return"])["cagr"]*100
    p(f"    2019: L5={y19_l5:+6.2f}%   L5+R4={y19_r4:+6.2f}% (Δ {(y19_r4-y19_l5):+5.2f}pp)")
    p(f"    Full-sample CAGR: L5={full_l5:.2f}%   L5+R4={full_r4:.2f}% (Δ {(full_r4-full_l5):+.2f}pp)")
    p()

    # Cumulative growth
    p("=" * 150)
    p("  CUMULATIVE GROWTH OF ₹1 (post-tax)")
    p("=" * 150)
    for name, df, _ in variants:
        cum = (1+df["strategy_return"]).cumprod().iloc[-1]
        p(f"  {name:<18}  ₹1 → ₹{cum:.2f}   ({(cum-1)*100:+.0f}%)")
    nifty_cum = nifty_close.iloc[-1]/nifty_close.iloc[0]
    p(f"  {'NIFTY 50 B&H':<18}  ₹1 → ₹{nifty_cum:.2f}   ({(nifty_cum-1)*100:+.0f}%)")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "test_min_hold_after_stress.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()

"""
strategy_lab.py — DEBUGGABLE STRATEGY TESTBED

Single self-contained file. Copy of strategy.py with extensions for V2 overlay
and the recovery-latch state machine. Run via:

    python experiments/strategy_lab.py

The original strategy.py is UNCHANGED. This file is for testing variants in
one place where they can be read and stepped through. Each config below
corresponds to one strategy variant; main() runs all of them on the same data
and reports comparable post-tax metrics.

CONFIGS (all the same v1.5 base, varied by overlay):
  C0  production v1.5 — sanity baseline. Should reproduce strategy.py
        exactly (CAGR ~15.64%, Sharpe ~0.786, MaxDD ~-14.67%).
  C1  + V2 overlay — hold NIFTY 50 for 60 trading days after each bear→bull
        flip where the preceding bear-regime DD ≥ 15%. Otherwise = C0.
  C2  + V2 + recovery latch, trend-only, X = 3%.
  C3  + V2 + recovery latch, trend-only, X = 5%.
  C4  + V2 + recovery latch, trend-only, X = 8%.
  C5  + V2 + recovery latch, trend + macro, X = 3%
        (macro: India VIX 90d z-score < 0 AND USDINR 20d return ≥ 0).
  C6  + V2 + recovery latch, trend + macro, X = 5%.
  C7  + V2 + recovery latch, trend + macro, X = 8%.

RECOVERY LATCH MECHANICS (state machine over long-state days only):
  NON_LONG       — strategy is flat/short/gold. No latch logic.
  RECOVERY       — strategy just went long after stress (or V2 just ended).
                   Allocation: inverse-vol Mom30 + gold (if G10 gate ON), else
                   vol-targeted Mom30 + cash (gate OFF). No NIFTY.
  ESTABLISHED    — latch fired (Mom30 ≥ X% above its own 100-DMA, plus macro
                   confirm in TM variants). Allocation: 100% Mom30. One-way
                   door — no flip back to RECOVERY without a fresh non-long.

V2 takes precedence: if a V2 window is active, that day uses 100% NIFTY 50
regardless of recovery state. State is preserved across V2 so when V2 ends,
allocation resumes appropriately.

DEBUGGING:
  Each non-C0 config writes a per-day log to
  results/strategy_lab_<config>_log.csv with columns
  [date, base_pos_today, base_pos_yest, in_v2, lab_state, w_mom, w_nif,
  w_gold, w_cash, ret_mom, ret_nif, ret_gold, ret_cash, day_pnl_pretax].
  You can grep these files for any date to see exactly what the strategy did.

The signal classes, RegimeFilter, SignalCombiner, helpers and
build_rbi_repo_rate_series are UNCHANGED from strategy.py. Only
MacroStrategyLab and main() differ.
"""

import sys
import pandas as pd
import numpy as np
import yfinance as yf

# ---------------------------------------------------------------------------
# Signal classes — replicated from strategy.py (no logic changes)
# ---------------------------------------------------------------------------

class MacroSignal:
    name = "base"
    def compute(self, data): raise NotImplementedError

class SupplyShockSignal(MacroSignal):
    name = "supply_shock"
    def __init__(self, window=10, oil_threshold=0.03, inr_threshold=0.01, vix_threshold=0.20):
        self.window = window; self.oil_threshold = oil_threshold
        self.inr_threshold = inr_threshold; self.vix_threshold = vix_threshold
    def compute(self, data):
        oil = data["CL=F"].pct_change(self.window) > self.oil_threshold
        inr = data["INR=X"].pct_change(self.window) > self.inr_threshold
        vix = data["^INDIAVIX"].pct_change(self.window) > self.vix_threshold
        s = pd.Series(0.0, index=data.index, name=self.name)
        s[oil & inr & vix] = -1.0
        return s

class PanicShortSignal(MacroSignal):
    name = "panic_short"
    def __init__(self, vix_level=25.0, vix_spike=0.50, window=10, dma=100):
        self.vix_level = vix_level; self.vix_spike = vix_spike
        self.window = window; self.dma = dma
    def compute(self, data):
        vix = data["^INDIAVIX"]
        panic = ((vix >= self.vix_level)
                 & (vix.pct_change(self.window) > self.vix_spike)
                 & (data["^NSEI"].ffill() < data["^NSEI"].ffill().rolling(self.dma).mean()))
        s = pd.Series(0.0, index=data.index, name=self.name)
        s[panic] = -1.0
        return s

class USDINRSignal(MacroSignal):
    name = "usdinr"
    def __init__(self, window=10, threshold=0.01):
        self.window = window; self.threshold = threshold
    def compute(self, data):
        s = pd.Series(0.0, index=data.index, name=self.name)
        s[data["INR=X"].pct_change(self.window) < -self.threshold] = 1.0
        return s

class IndiaVIXSignal(MacroSignal):
    name = "india_vix"
    def __init__(self, window=10, threshold=0.20):
        self.window = window; self.threshold = threshold
    def compute(self, data):
        s = pd.Series(0.0, index=data.index, name=self.name)
        s[data["^INDIAVIX"].pct_change(self.window) < -self.threshold] = 1.0
        return s

class SlowStressSignal(MacroSignal):
    """v1.4 slow-stress signal — replaces SupplyShockSignal as the default
    stress-flat trigger. Detects sustained EM stress regimes that the
    10d-acute supply-shock composite misses (notably 2013 taper, 2018 NBFC).

    Fires when ALL three conditions hold simultaneously:
      - USDINR pct_change(inr_window) > inr_threshold
            (sustained rupee weakening — capital flight proxy)
      - VIX 90d rolling z-score > vix_z_threshold
            (vol elevated relative to recent regime, not absolute)
      - VIX - VIX.shift(vix_mom_window) > 0
            (vol still rising — kills the signal during recoveries)

    Returns -1 on firing days (matches SupplyShockSignal convention for
    force-flat overrides). Cross-country validated on US data 1995-2025
    using DXY as the INR analog (9/9 known stress events caught,
    3.84% overall fire rate)."""
    name = "slow_stress"
    def __init__(self, inr_window=20, inr_threshold=0.01,
                 vix_z_window=90, vix_z_threshold=1.5,
                 vix_mom_window=5):
        self.inr_window      = inr_window
        self.inr_threshold   = inr_threshold
        self.vix_z_window    = vix_z_window
        self.vix_z_threshold = vix_z_threshold
        self.vix_mom_window  = vix_mom_window
    def compute(self, data):
        inr_w = data["INR=X"].pct_change(self.inr_window) > self.inr_threshold
        vix   = data["^INDIAVIX"]
        z     = (vix - vix.rolling(self.vix_z_window).mean()) / vix.rolling(self.vix_z_window).std()
        mom   = vix - vix.shift(self.vix_mom_window)
        fires = inr_w & (z > self.vix_z_threshold) & (mom > 0)
        s = pd.Series(0.0, index=data.index, name=self.name)
        s[fires.fillna(False)] = -1.0
        return s

class RegimeFilter:
    def __init__(self, window=200, target="^NSEI"):
        self.window = window; self.target = target
    def bull_mask(self, data):
        price = data[self.target].ffill()
        return (price > price.rolling(self.window).mean()).rename(f"bull_{self.window}dma")


# ---------------------------------------------------------------------------
# SignalCombiner v1.1 — emits nifty_position AND gold_position
# ---------------------------------------------------------------------------

class SignalCombiner:
    """
    v1.1: positions DataFrame with two columns: nifty_position, gold_position.
    Gold rotation is opt-in via two flags (default both False = v1 behavior).
    """

    def __init__(self, regime_filter=None, reentry_momentum_threshold=0.005,
                 rotate_to_gold_on_stress_flat=False,
                 rotate_to_gold_on_panic_short=False,
                 rotate_with_momentum=False,
                 gold_momentum_window=10,
                 gold_target="GOLDBEES.NS",
                 gold_gate_external=True,
                 gold_gate_upper_cap=0.10,
                 gold_gate_inr_threshold=0.005,
                 gold_gate_us10y_threshold=0.0,
                 gold_require_bear=True):
        self.entry_signals = []
        self.exit_signals = []
        # v1.4: signals that force-flat ONLY on the day they fire (no cooldown
        # extension via NIFTY-momentum recovery gate). Used for SlowStressSignal
        # which fires on slow rolling windows — extending via cooldown would
        # double-count the time horizon.
        self.exit_signals_no_cooldown = []
        self.short_signals = []
        self.regime_filter = regime_filter
        self.reentry_momentum_threshold = reentry_momentum_threshold
        self.rotate_to_gold_on_stress_flat = rotate_to_gold_on_stress_flat
        self.rotate_to_gold_on_panic_short = rotate_to_gold_on_panic_short
        # v1.2 momentum-gated gold rotation:
        # When True, gold is held within a stress-flat latch only while gold
        # 10-day momentum is positive. Once exited mid-latch, stays in cash for
        # the rest of that latch. Re-entry only allowed in a NEW latch.
        self.rotate_with_momentum = rotate_with_momentum
        self.gold_momentum_window = gold_momentum_window
        self.gold_target = gold_target
        # v1.4 G10 gold gate — adds three structural improvements vs the
        # original `gold_10d > 0` entry rule:
        #   1. Upper momentum cap (gold_gate_upper_cap, default 10%) prevents
        #      blow-off-top entries (e.g., 2026-01-29 entered at +24% gold 10d,
        #      crashed -19% within days under legacy gate).
        #   2. INR confirmation (gold_gate_inr_threshold) — gold priced in
        #      USD; weakening INR mechanically lifts INR-priced gold.
        #   3. US10Y direction (gold_gate_us10y_threshold) — falling US yields
        #      lift gold (real-yield channel).
        # Requires data["INR=X"] and data["^TNX"] columns when active. Set
        # gold_gate_external=False to revert to legacy `gold_10d > 0` only.
        self.gold_gate_external = gold_gate_external
        self.gold_gate_upper_cap = gold_gate_upper_cap
        self.gold_gate_inr_threshold = gold_gate_inr_threshold
        self.gold_gate_us10y_threshold = gold_gate_us10y_threshold
        # v1.5 simple fix for 2019 gold-in-bull anomaly:
        # When True (default), gold rotation entry requires bear regime
        # (NIFTY < 100 DMA) as a fourth condition on top of G10 gate. Also
        # exits gold mid-latch if regime flips from bear to bull. Addresses
        # the 3-day May 2019 anomaly where slow-stress fired in bull regime
        # and gold rotation entered, costing -4.34pp. Set False to recover
        # v1.4 behavior (gold rotation gated only on G10 conditions).
        self.gold_require_bear = gold_require_bear

    def add_entry(self, signal, weight=1.0):
        self.entry_signals.append((signal, weight)); return self
    def add_exit(self, signal):
        self.exit_signals.append(signal); return self
    def add_exit_no_cooldown(self, signal):
        """Like add_exit but force-flats ONLY on firing days; no cooldown
        extension. Used by SlowStressSignal in v1.4."""
        self.exit_signals_no_cooldown.append(signal); return self
    def add_short(self, signal, hold=True, max_hold_days=60,
                  exit_ma_fast=None, exit_ma_slow=None):
        self.short_signals.append((signal, hold, max_hold_days, exit_ma_fast, exit_ma_slow))
        return self

    def compute_positions(self, data):
        """
        Returns DataFrame with columns: nifty_position, gold_position.
        Also tracks the source state of each day for diagnostics.
        """
        n = len(data)
        idx = data.index

        # Lane 1: entry → long/flat with hold
        if self.entry_signals:
            total_weight = sum(w for _, w in self.entry_signals)
            score = pd.Series(0.0, index=idx)
            for signal, weight in self.entry_signals:
                score += signal.compute(data) * (weight / total_weight)
            position = pd.Series(0.0, index=idx)
            position[score > 0] = 1.0
        else:
            position = pd.Series(1.0, index=idx)

        position = position.replace(0.0, np.nan).ffill().fillna(1.0)

        # Re-entry momentum gate
        nifty_mom = data["^NSEI"].ffill().pct_change(5)
        nifty_recovering = nifty_mom > self.reentry_momentum_threshold

        # Track which days are "stress flat" (supply shock latch or post-short flat)
        # so we can rotate to gold if requested.
        stress_flat_mask = pd.Series(False, index=idx)

        # Lane 2: exit signals → flat with momentum-gated re-entry
        for signal in self.exit_signals:
            firing = signal.compute(data) < 0
            firing_vals = firing.values
            recover_vals = nifty_recovering.values
            in_exit = False
            exit_flat = [False] * n
            for i in range(n):
                if firing_vals[i]:
                    in_exit = True; exit_flat[i] = True
                elif in_exit:
                    if recover_vals[i]:
                        in_exit = False
                    else:
                        exit_flat[i] = True
            ef_series = pd.Series(exit_flat, index=idx)
            position[ef_series] = 0.0
            stress_flat_mask = stress_flat_mask | ef_series

        # Lane 2b: no-cooldown exit signals — force flat ONLY on firing days.
        # v1.4: SlowStressSignal uses this lane; its 90d/20d windows are
        # already slow, so extending via NIFTY-momentum cooldown would
        # double-count the time horizon and over-extend cash days.
        for signal in self.exit_signals_no_cooldown:
            firing = signal.compute(data) < 0
            position[firing] = 0.0
            stress_flat_mask = stress_flat_mask | firing

        # Lane 3: short signals → -1 when firing.
        # If rotate_to_gold_on_panic_short=True, this overrides to flat
        # (gold rotation handled separately below).
        panic_short_mask = pd.Series(False, index=idx)  # days panic-short fired
        for signal, hold, max_hold_days, exit_ma_fast, exit_ma_slow in self.short_signals:
            raw = signal.compute(data) < 0
            if hold and max_hold_days > 0:
                held = raw.astype(float).rolling(window=max_hold_days, min_periods=1).max()
                if exit_ma_fast and exit_ma_slow:
                    nifty = data["^NSEI"].ffill()
                    ma_bullish = nifty.rolling(exit_ma_fast).mean() > nifty.rolling(exit_ma_slow).mean()
                    short_active = (held == 1.0) & ~ma_bullish
                else:
                    short_active = (held == 1.0)
            else:
                short_active = raw
            panic_short_mask = panic_short_mask | short_active
            position[short_active] = -1.0

        # Post-short flat: stay flat after short ends until momentum recovers
        if self.short_signals:
            is_short = (position == -1.0).values
            is_fresh = nifty_recovering.values
            in_cd = False; psf = [False] * n
            for i in range(1, n):
                if is_short[i-1] and not is_short[i]: in_cd = True
                if in_cd and is_fresh[i]: in_cd = False
                if in_cd and not is_fresh[i] and not is_short[i]: psf[i] = True
            psf_series = pd.Series(psf, index=idx)
            position[psf_series] = 0.0
            stress_flat_mask = stress_flat_mask | psf_series

        # Regime filter: kill longs in bear, shorts in bull
        regime_killed_short = pd.Series(False, index=idx)
        if self.regime_filter:
            bull = self.regime_filter.bull_mask(data)
            position[(position > 0) & ~bull] = 0.0
            killed_mask = (position < 0) & bull
            regime_killed_short = killed_mask
            position[killed_mask] = 0.0

        # ── Build dual-asset positions ──────────────────────────────────────
        nifty_position = position.copy()
        gold_position  = pd.Series(0.0, index=idx)

        # Config 2 leg: gold during stress flat
        if self.rotate_to_gold_on_stress_flat:
            if self.rotate_with_momentum:
                # ── v1.2 momentum-gated rotation ──────────────────────────
                # Per-latch state machine:
                #   - on latch start: enter gold ONLY if gold 10d return > 0
                #   - within latch: exit gold if gold 10d return turns negative
                #   - once exited mid-latch: stay in cash until latch ends
                #   - latch end → reset state, no gold
                if self.gold_target in data.columns:
                    gold_10d = data[self.gold_target].pct_change(self.gold_momentum_window)
                else:
                    gold_10d = pd.Series(np.nan, index=idx)

                # v1.4 G10 gate inputs — INR 10d and US10Y 20d series. Only
                # used when gold_gate_external=True AND the required columns
                # exist; otherwise gate falls back to legacy `gold_10d > 0`.
                inr_10d_vals = None
                us10y_20d_vals = None
                if self.gold_gate_external:
                    if "INR=X" in data.columns:
                        inr_10d_vals = data["INR=X"].pct_change(10).values
                    if "^TNX" in data.columns:
                        us10y_20d_vals = data["^TNX"].pct_change(20).values

                # v1.5 fix: bull mask for the bear-regime gate condition.
                # Required when gold_require_bear=True (default).
                bull_vals = None
                if self.gold_require_bear and self.regime_filter is not None:
                    bull_vals = self.regime_filter.bull_mask(data).values

                stress_vals  = stress_flat_mask.values
                nifty_vals   = nifty_position.values
                gold_10d_vals = gold_10d.values
                gp = np.zeros(n)

                in_latch = False
                in_gold = False
                exited_gold_this_latch = False

                def entry_gate_passes(i, g10):
                    """G10 gate: gold_10d in (0, cap] AND INR weakening AND
                    US10Y falling. Falls back to legacy `g10 > 0` when external
                    indicators unavailable."""
                    if np.isnan(g10) or g10 <= 0:
                        return False
                    if not self.gold_gate_external:
                        return True   # legacy gate
                    if g10 > self.gold_gate_upper_cap:
                        return False  # blow-off-top guard
                    if inr_10d_vals is not None:
                        inr_v = inr_10d_vals[i]
                        if np.isnan(inr_v) or inr_v <= self.gold_gate_inr_threshold:
                            return False
                    if us10y_20d_vals is not None:
                        us_v = us10y_20d_vals[i]
                        if np.isnan(us_v) or us_v >= self.gold_gate_us10y_threshold:
                            return False
                    return True

                for i in range(n):
                    is_stress_flat_day = stress_vals[i] and (nifty_vals[i] == 0.0)
                    if is_stress_flat_day:
                        if not in_latch:
                            # Latch starting — entry decision
                            in_latch = True
                            exited_gold_this_latch = False
                            g10 = gold_10d_vals[i]
                            is_bull = bull_vals is not None and bull_vals[i]
                            if entry_gate_passes(i, g10) and not is_bull:
                                in_gold = True
                                gp[i] = 1.0
                            else:
                                in_gold = False
                                # gp[i] stays 0
                        else:
                            # Continuing latch — exit rules:
                            # (1) gold 10d turning negative (one-way door)
                            # (2) regime flipping to bull mid-latch (v1.5 fix)
                            if in_gold:
                                g10 = gold_10d_vals[i]
                                if not np.isnan(g10) and g10 < 0:
                                    in_gold = False
                                    exited_gold_this_latch = True
                                elif bull_vals is not None and bull_vals[i]:
                                    in_gold = False
                                    exited_gold_this_latch = True
                            if in_gold:
                                gp[i] = 1.0
                            # else: gp[i] stays 0 (in cash for rest of latch)
                    elif not stress_vals[i]:
                        # Latch ending — reset state
                        if in_latch:
                            in_latch = False
                            in_gold = False
                            exited_gold_this_latch = False
                        # gp[i] stays 0
                    # else: stress_flat_mask=True but nifty_pos != 0 (panic short
                    #   inside latch). Preserve state, no gold (already 0).

                gold_position = pd.Series(gp, index=idx)
            else:
                # Original Config 2 logic — gold throughout entire latch
                rotate_mask = stress_flat_mask & (nifty_position == 0.0)
                gold_position[rotate_mask] = 1.0

        # Config 3 leg: gold replaces panic short
        if self.rotate_to_gold_on_panic_short:
            # Wherever panic-short fired AND survived regime filter (i.e. nifty=-1)
            # flip to flat NIFTY + long gold
            panic_short_active = (nifty_position == -1.0)
            nifty_position[panic_short_active] = 0.0
            gold_position[panic_short_active] = 1.0

        return pd.DataFrame({
            "nifty_position": nifty_position.rename(None),
            "gold_position":  gold_position.rename(None),
        }, index=idx)


# ---------------------------------------------------------------------------
# RBI Repo Rate Step Function (sourced from RBI MPC press releases)
# Used to credit cash yield on fully-flat days. Each tuple is (effective_date, rate%).
# Forward-filled per day — repo rate stays constant between MPC announcements.
# ---------------------------------------------------------------------------

RBI_REPO_RATE_HISTORY = [
    ("2008-04-01", 7.75), ("2008-06-12", 8.00), ("2008-06-25", 8.50), ("2008-07-30", 9.00),
    ("2008-10-20", 8.00), ("2008-11-03", 7.50), ("2008-12-08", 6.50),
    ("2009-01-05", 5.50), ("2009-03-05", 5.00), ("2009-04-21", 4.75),
    ("2010-03-19", 5.00), ("2010-04-20", 5.25), ("2010-07-02", 5.50), ("2010-07-27", 5.75),
    ("2010-09-16", 6.00), ("2010-11-02", 6.25),
    ("2011-01-25", 6.50), ("2011-03-17", 6.75), ("2011-05-03", 7.25), ("2011-06-16", 7.50),
    ("2011-07-26", 8.00), ("2011-09-16", 8.25), ("2011-10-25", 8.50),
    ("2012-04-17", 8.00),
    ("2013-01-29", 7.75), ("2013-03-19", 7.50), ("2013-05-03", 7.25),
    ("2013-09-20", 7.50), ("2013-10-29", 7.75),
    ("2014-01-28", 8.00),
    ("2015-01-15", 7.75), ("2015-03-04", 7.50), ("2015-06-02", 7.25), ("2015-09-29", 6.75),
    ("2016-04-05", 6.50), ("2016-10-04", 6.25),
    ("2017-08-02", 6.00),
    ("2018-06-06", 6.25), ("2018-08-01", 6.50),
    ("2019-02-07", 6.25), ("2019-04-04", 6.00), ("2019-06-06", 5.75),
    ("2019-08-07", 5.40), ("2019-10-04", 5.15),
    ("2020-03-27", 4.40), ("2020-05-22", 4.00),
    ("2022-05-04", 4.40), ("2022-06-08", 4.90), ("2022-08-05", 5.40),
    ("2022-09-30", 5.90), ("2022-12-07", 6.25),
    ("2023-02-08", 6.50),
    ("2025-02-07", 6.25), ("2025-04-09", 6.00), ("2025-06-06", 5.50),
]


def build_rbi_repo_rate_series(target_index: pd.DatetimeIndex) -> pd.Series:
    """
    Returns a Series indexed by target_index with the active RBI repo rate (as
    decimal, e.g. 0.06 = 6%) on each day, forward-filled from the most recent
    rate change on or before that date.
    """
    df = pd.DataFrame(RBI_REPO_RATE_HISTORY, columns=["date", "rate"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")
    # Step function: ffill across calendar days, then reindex to target trading days
    full_daily = df.reindex(pd.date_range(df.index.min(), target_index.max(), freq="D"),
                            method="ffill")
    aligned = full_daily.reindex(target_index, method="ffill")
    return (aligned["rate"] / 100.0).rename("repo_rate")


# ---------------------------------------------------------------------------
# MacroStrategy v1.1 — applies dual positions with per-asset costs +
# time-varying cash yield on fully-flat days
# ---------------------------------------------------------------------------

class MacroStrategy:
    """v1.1: dual-asset PnL with per-asset transaction costs and RBI repo
    rate cash yield on fully-flat days."""

    def __init__(self, combiner, target="^NSEI", gold_target="GOLDBEES.NS",
                 nifty_cost_bps=3, gold_cost_bps=5,
                 cash_cost_bps=0,
                 use_cash_yield=True,
                 cash_yield_haircut_bps=100,
                 long_target="^NSEI",
                 long_cost_bps=3,
                 apply_tax=True, tax_rate=0.15):
        self.combiner = combiner
        self.target = target          # ^NSEI — used for signals, regime filter, SHORT positions
        self.gold_target = gold_target
        self.nifty_cost_bps = nifty_cost_bps   # cost for short-side (^NSEI futures)
        self.gold_cost_bps  = gold_cost_bps
        self.cash_cost_bps  = cash_cost_bps    # bps to enter/exit cash sweep (default 0)
        self.use_cash_yield = use_cash_yield
        self.cash_yield_haircut_bps = cash_yield_haircut_bps
        # v1.3: asset held when long. Defaults to ^NSEI (backward-compatible with
        # v1.1 / v1.2). Configs 5/6 override with NIFTYMIDCAP150 / NIFTYMOM30
        # to capture higher-alpha index exposure on the long side. SHORT positions
        # still use ^NSEI (more liquid for futures-based shorting in practice).
        self.long_target = long_target
        self.long_cost_bps = long_cost_bps
        # v1.4: tax model. apply_tax=True (default) returns post-tax daily
        # returns in strategy_return. The original pre-tax series is also
        # exposed as strategy_return_pretax for diagnostics. Set apply_tax=False
        # to disable (recovers v1.3 behavior).
        self.apply_tax = apply_tax
        self.tax_rate = tax_rate

    def run(self, data):
        # Benchmark/short-side return: always ^NSEI
        nifty_returns = data[self.target].pct_change().rename("nifty_return")
        # Long-side return: the asset HELD when long (defaults to ^NSEI; v1.3
        # Configs 5/6 override to higher-alpha indices).
        if self.long_target in data.columns:
            long_returns = data[self.long_target].pct_change().fillna(0.0)
        else:
            long_returns = nifty_returns.fillna(0.0)

        # Gold returns: zero where data is missing (pre-2009 for GOLDBEES.NS)
        if self.gold_target in data.columns:
            gold_raw = data[self.gold_target]
            gold_returns = gold_raw.pct_change()
            # Force gold_position to 0 where gold price is NaN (no data → can't trade)
            gold_available = gold_raw.notna()
        else:
            gold_returns = pd.Series(0.0, index=data.index)
            gold_available = pd.Series(False, index=data.index)
        gold_returns = gold_returns.fillna(0.0).rename("gold_return")

        positions = self.combiner.compute_positions(data)
        nifty_pos = positions["nifty_position"]
        gold_pos  = positions["gold_position"]

        # Mask out gold position when no data available (forced flat)
        gold_pos = gold_pos.where(gold_available, 0.0)

        # v1.3: separate long and short accounting so they can use different
        # underlying assets (long_target vs ^NSEI) and different cost rates.
        long_pos  = (nifty_pos ==  1.0).astype(float)
        short_pos = (nifty_pos == -1.0).astype(float)

        long_cost  = long_pos.diff().abs()  * (self.long_cost_bps  / 10000)
        short_cost = short_pos.diff().abs() * (self.nifty_cost_bps / 10000)
        gold_cost  = gold_pos.diff().abs()  * (self.gold_cost_bps  / 10000)

        long_pnl  =  long_pos.shift(1)  * long_returns
        short_pnl = -short_pos.shift(1) * nifty_returns   # short uses ^NSEI
        nifty_pnl = long_pnl + short_pnl - long_cost - short_cost
        gold_pnl  = gold_pos.shift(1) * gold_returns - gold_cost

        # Cash yield on fully-flat days (no NIFTY exposure, no gold exposure)
        # Yield rate = RBI repo rate minus haircut (time-varying daily step function).
        # Default haircut 100bps models liquid-fund spread + TER + sweep frictions.
        cash_position = ((nifty_pos == 0.0) & (gold_pos == 0.0)).astype(float)
        if self.use_cash_yield:
            repo_rate = build_rbi_repo_rate_series(data.index)
            haircut_repo = (repo_rate - self.cash_yield_haircut_bps / 10000).clip(lower=0)
            daily_cash_yield = haircut_repo / 252
            cash_pnl = cash_position.shift(1) * daily_cash_yield
        else:
            cash_pnl = pd.Series(0.0, index=data.index)
        # Cost to enter/exit cash sweep (default 0 — institutional auto-sweep is free)
        cash_cost = cash_position.diff().abs() * (self.cash_cost_bps / 10000)

        strategy_returns_pretax = (nifty_pnl + gold_pnl + cash_pnl - cash_cost).rename("strategy_return_pretax")
        if self.apply_tax:
            strategy_returns = apply_annual_tax(
                strategy_returns_pretax.fillna(0.0), tax_rate=self.tax_rate
            ).rename("strategy_return")
        else:
            strategy_returns = strategy_returns_pretax.rename("strategy_return")

        results = pd.DataFrame({
            "nifty_return":            nifty_returns,
            "gold_return":             gold_returns,
            "nifty_position":          nifty_pos,
            "gold_position":           gold_pos,
            "strategy_return":         strategy_returns,
            "strategy_return_pretax":  strategy_returns_pretax,
        })
        # Backward-compat: combined "position" column for diagnostic display.
        # +1 = long NIFTY, -1 = short NIFTY, +2 = long gold, 0 = flat (cash)
        combined = nifty_pos.copy()
        combined[(nifty_pos == 0.0) & (gold_pos == 1.0)] = 2.0
        results["position"] = combined
        return results


# ---------------------------------------------------------------------------
# LAB MODIFICATION: MacroStrategyLab
# ---------------------------------------------------------------------------
# Adds two orthogonal overlays on top of base v1.5 (combiner):
#   1. V2 overlay (enable_v2=True):
#      Detect bear→bull flips where the preceding bear-regime peak-to-trough
#      DD ≥ v2_dd_threshold. For v2_days trading days after each qualifying
#      flip, swap the long-side asset from Mom30 to NIFTY 50.
#   2. Recovery latch (recovery_latch dict not None):
#      State machine over long-state days. RECOVERY = just re-entered long;
#      ESTABLISHED = latch fired (Mom30 ≥ X% above own 100-DMA, plus optional
#      macro confirm). In RECOVERY, hold inverse-vol Mom30/gold (if G10 gate
#      ON) or vol-targeted Mom30 + cash (gate OFF). In ESTABLISHED, hold
#      100% Mom30. One-way door — no flip back to RECOVERY without a fresh
#      non-long episode. V2 takes precedence over recovery allocation.
#
# Computes daily PnL from per-day asset weights (w_mom, w_nif, w_gold, w_cash)
# and per-asset transaction costs on weight changes.
# ---------------------------------------------------------------------------

class MacroStrategyLab(MacroStrategy):
    """Extends MacroStrategy with V2 overlay and recovery-latch state machine.
    Set enable_v2=False and recovery_latch=None to get exactly MacroStrategy
    behavior (sanity-checked: C0 vs strategy.py default produces identical
    headline numbers)."""

    G10_INR_THR    = 0.005   # USDINR 10d return > 0.5% (rupee weakening)
    G10_US10Y_THR  = 0.0     # US 10y 20d return < 0
    G10_GOLD_CAP   = 0.10    # gold 10d return ≤ 10%

    def __init__(self, *args,
                 enable_v2=False, v2_dd_threshold=0.15, v2_days=60,
                 recovery_latch=None,        # None or {"mode":"trend"|"trend_macro", "x":float}
                 recovery_allocation="mom_gold_blend",  # see RECOVERY_ALLOCATIONS below
                 vol_target_annual=None,     # None → no vol target (full Mom30 in cash-blend); else annualized
                 vol_window=60,
                 log_path=None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.enable_v2 = enable_v2
        self.v2_dd_threshold = v2_dd_threshold
        self.v2_days = v2_days
        self.recovery_latch = recovery_latch
        # recovery_allocation options (what to hold during RECOVERY state):
        #   "mom_gold_blend" — inv-vol Mom30+Gold if G10 gate on, else vol-target Mom30+cash (C2 original)
        #   "nif_gold_blend" — inv-vol NIFTY+Gold unconditional, NIFTY-only if no gold data (C8)
        #   "gold_only"      — 100% Gold (cash if no gold data) (C9)
        #   "nif_only"       — 100% NIFTY 50 (C10)
        self.recovery_allocation = recovery_allocation
        self.vol_target_annual = vol_target_annual
        self.vol_window = vol_window
        self.log_path = log_path

    # ----- V2 helpers ----------------------------------------------------
    def _compute_v2_active(self, data, is_index):
        rf_full = RegimeFilter(window=100)
        bull_full = rf_full.bull_mask(data)
        bull = bull_full.reindex(is_index).fillna(False)
        prev = bull.shift(1, fill_value=False)
        flip = bull & (~prev)
        # Skip first day if it was already bull in the warmup
        if flip.iloc[0]:
            p = bull_full.index.get_loc(is_index[0])
            if p > 0 and bool(bull_full.iloc[p - 1]):
                flip.iloc[0] = False
        flips = is_index[flip.values]
        # Preceding-bear DD per flip
        nifty = data[self.target]
        def prev_bear_dd(d):
            p = bull_full.index.get_loc(d)
            if p == 0: return 0.0
            end = p - 1; s = end
            while s > 0 and not bool(bull_full.iloc[s - 1]):
                s -= 1
            w = nifty.iloc[s:end + 1]
            if len(w) == 0: return 0.0
            return abs(float((w / w.cummax() - 1.0).min()))
        qualifying = [d for d in flips if prev_bear_dd(d) >= self.v2_dd_threshold]
        v2 = pd.Series(False, index=is_index)
        for d in qualifying:
            i = is_index.get_loc(d)
            v2.iloc[i:min(i + self.v2_days, len(is_index))] = True
        return v2, qualifying

    # ----- Recovery-latch helpers ----------------------------------------
    def _g10_gate_series(self, data, is_index):
        gold_10d  = data[self.gold_target].pct_change(10).reindex(is_index)
        inr_10d   = data["INR=X"].pct_change(10).reindex(is_index)
        us10y_20d = data["^TNX"].pct_change(20).reindex(is_index)
        gold_avail = data[self.gold_target].reindex(is_index).notna()
        gate = (
            (gold_10d > 0) & (gold_10d <= self.G10_GOLD_CAP) &
            (inr_10d > self.G10_INR_THR) &
            (us10y_20d < self.G10_US10Y_THR) &
            gold_avail
        ).fillna(False)
        return gate

    def _latch_trigger_series(self, data, is_index):
        mom_close = data[self.long_target].reindex(is_index).ffill()
        mom_100dma = mom_close.rolling(100, min_periods=1).mean()
        dist = mom_close / mom_100dma - 1.0
        x = self.recovery_latch["x"]
        trigger = dist >= x
        if self.recovery_latch["mode"] == "trend_macro":
            vix = data["^INDIAVIX"].reindex(is_index).ffill()
            vix_90z = (vix - vix.rolling(90).mean()) / vix.rolling(90).std()
            inr = data["INR=X"].reindex(is_index).ffill()
            inr_20d = inr.pct_change(20)
            macro = (vix_90z < 0) & (inr_20d >= 0)
            trigger = trigger & macro
        return trigger.fillna(False)

    # ----- Main run ------------------------------------------------------
    def run(self, data):
        # ----- Identical to MacroStrategy: derive asset returns + positions -----
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
        gold_pos  = positions["gold_position"].where(gold_available, 0.0)
        is_index  = data.index

        # ----- Cash yield series (per-day) -------------------------------
        if self.use_cash_yield:
            repo_rate = build_rbi_repo_rate_series(is_index)
            haircut_repo = (repo_rate - self.cash_yield_haircut_bps / 10000).clip(lower=0)
            daily_cash_yield = haircut_repo / 252
        else:
            daily_cash_yield = pd.Series(0.0, index=is_index)

        # ----- V2 overlay -----------------------------------------------
        if self.enable_v2:
            v2_active, v2_flips = self._compute_v2_active(data, is_index)
        else:
            v2_active = pd.Series(False, index=is_index)
            v2_flips = []

        # ----- Recovery latch precomputation ----------------------------
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

        # ----- State machine + weight construction -----------------------
        n = len(is_index)
        long_mask = (nifty_pos == 1.0)
        w_mom  = np.zeros(n); w_nif = np.zeros(n)
        w_gold = np.zeros(n); w_cash = np.zeros(n)
        lab_state = np.empty(n, dtype=object)
        state = "NON_LONG"
        for i in range(n):
            today_long = bool(long_mask.iloc[i])
            today_v2   = bool(v2_active.iloc[i]) and today_long
            # State transitions ------------------------------------------
            if not today_long:
                state = "NON_LONG"
            elif today_v2:
                # V2 takes over allocation but state is preserved.
                if state == "NON_LONG":
                    state = "RECOVERY"
                # Latch is NOT checked while V2 active.
            else:
                if state == "NON_LONG":
                    state = "RECOVERY"
                if state == "RECOVERY" and latch_enabled and bool(latch_trigger.iloc[i]):
                    state = "ESTABLISHED"
                elif state == "RECOVERY" and not latch_enabled:
                    # No latch defined → stay 100% Mom30 like base
                    state = "ESTABLISHED"
            lab_state[i] = state if today_long else "NON_LONG"

            # Weights ----------------------------------------------------
            if not today_long:
                # Non-long: mirror base positions (short / gold / flat)
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

                if alloc == "mom_gold_blend":
                    # Original C2: inv-vol Mom30+Gold if G10 ON, else vol-target Mom30+cash
                    if gate_on and not (np.isnan(sm) or np.isnan(sg) or sm <= 0 or sg <= 0):
                        inv_m, inv_g = 1.0/sm, 1.0/sg
                        s = inv_m + inv_g
                        w_mom[i]  = inv_m / s
                        w_gold[i] = inv_g / s
                    elif (self.vol_target_annual is not None) and (not np.isnan(sm)) and sm > 0:
                        scale = min(self.vol_target_annual / sm, 1.0)
                        w_mom[i]  = scale
                        w_cash[i] = 1.0 - scale
                    else:
                        w_mom[i] = 1.0
                elif alloc == "nif_gold_blend":
                    # C8: inv-vol NIFTY+Gold, unconditional (no G10 gate).
                    # Falls back to 100% NIFTY if no gold data (pre-2009).
                    if gold_avail_today and not (np.isnan(sn) or np.isnan(sg) or sn <= 0 or sg <= 0):
                        inv_n, inv_g = 1.0/sn, 1.0/sg
                        s = inv_n + inv_g
                        w_nif[i]  = inv_n / s
                        w_gold[i] = inv_g / s
                    else:
                        w_nif[i] = 1.0
                elif alloc == "gold_only":
                    # C9: 100% gold unconditional (cash if no gold data)
                    if gold_avail_today:
                        w_gold[i] = 1.0
                    else:
                        w_cash[i] = 1.0
                elif alloc == "gold_gated_cash":
                    # C11: G10 gate ON → 100% gold; gate OFF → cash
                    if gate_on and gold_avail_today:
                        w_gold[i] = 1.0
                    else:
                        w_cash[i] = 1.0
                elif alloc == "gold_gated_mom":
                    # C12: G10 gate ON → 100% gold; gate OFF → 100% Mom30
                    if gate_on and gold_avail_today:
                        w_gold[i] = 1.0
                    else:
                        w_mom[i] = 1.0
                elif alloc == "nif_only":
                    # C10: 100% NIFTY 50
                    w_nif[i] = 1.0
                else:
                    w_mom[i] = 1.0
            else:  # ESTABLISHED
                w_mom[i] = 1.0

        # ----- Costs (on weight changes, per asset) ---------------------
        wdf = pd.DataFrame({"mom": w_mom, "nif": w_nif, "gold": w_gold, "cash": w_cash}, index=is_index)
        cost_mom  = wdf["mom"].diff().abs().fillna(0)  * (self.long_cost_bps  / 10000)
        cost_nif  = wdf["nif"].diff().abs().fillna(0)  * (self.nifty_cost_bps / 10000)
        cost_gold = wdf["gold"].diff().abs().fillna(0) * (self.gold_cost_bps  / 10000)
        cost_cash = wdf["cash"].diff().abs().fillna(0) * (self.cash_cost_bps  / 10000)
        total_cost = cost_mom + cost_nif + cost_gold + cost_cash

        # ----- PnL from yesterday's weights × today's returns -----------
        pnl_mom  = wdf["mom"].shift(1).fillna(0)  * long_returns
        pnl_nif  = wdf["nif"].shift(1).fillna(0)  * nifty_returns
        pnl_gold = wdf["gold"].shift(1).fillna(0) * gold_returns
        pnl_cash = wdf["cash"].shift(1).fillna(0) * daily_cash_yield
        pretax = (pnl_mom + pnl_nif + pnl_gold + pnl_cash - total_cost).rename("strategy_return_pretax")

        if self.apply_tax:
            posttax = apply_annual_tax(pretax.fillna(0.0), tax_rate=self.tax_rate).rename("strategy_return")
        else:
            posttax = pretax.rename("strategy_return")

        # ----- Per-day log (for debugging) ------------------------------
        if self.log_path is not None:
            os = __import__("os")
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            log = pd.DataFrame({
                "base_pos":   nifty_pos,
                "gold_pos":   gold_pos,
                "in_v2":      v2_active,
                "lab_state":  pd.Series(lab_state, index=is_index),
                "latch_trig": latch_trigger if latch_enabled else False,
                "gate":       gate if latch_enabled else False,
                "sigma_m":    sigma_m,
                "w_mom":      wdf["mom"],
                "w_nif":      wdf["nif"],
                "w_gold":     wdf["gold"],
                "w_cash":     wdf["cash"],
                "ret_mom":    long_returns,
                "ret_nif":    nifty_returns,
                "ret_gold":   gold_returns,
                "ret_cash":   daily_cash_yield,
                "cost":       total_cost,
                "pretax":     pretax,
                "posttax":    posttax,
            })
            log.to_csv(self.log_path)

        results = pd.DataFrame({
            "nifty_return":            nifty_returns,
            "gold_return":             gold_returns,
            "nifty_position":          nifty_pos,
            "gold_position":           gold_pos,
            "strategy_return":         posttax,
            "strategy_return_pretax":  pretax,
        })
        combined = nifty_pos.copy()
        combined[(nifty_pos == 0.0) & (gold_pos == 1.0)] = 2.0
        results["position"] = combined
        return results, {"v2_flips": v2_flips, "lab_state": pd.Series(lab_state, index=is_index),
                          "weights": wdf, "v2_active": v2_active}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RF = 0.06

def load_nse_index_csv(path, col_name):
    """Load NSE Indices historical CSV (from niftyindices.com export).
    Returns a Series of CLOSE_INDEX_VAL indexed by trading date.
    Format: INDEX_NAME, OPEN_INDEX_VAL, HIGH_INDEX_VAL, CLOSE_INDEX_VAL, ..., TIMESTAMP."""
    df = pd.read_csv(path)
    df["TIMESTAMP"] = pd.to_datetime(df["TIMESTAMP"])
    df = df.set_index("TIMESTAMP").sort_index()
    return df["CLOSE_INDEX_VAL"].astype(float).rename(col_name)


def metrics(ret_series):
    r = ret_series.dropna()
    cum = (1 + r).cumprod()
    n_years = len(r) / 252
    total = cum.iloc[-1] - 1
    cagr = (1 + total) ** (1 / n_years) - 1
    vol = r.std() * np.sqrt(252)
    excess = r - RF / 252
    sharpe = (excess.mean() / excess.std()) * np.sqrt(252)
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = (cagr - RF) / downside if downside > 0 else np.nan
    dd = ((cum - cum.cummax()) / cum.cummax()).min()
    calmar = cagr / abs(dd) if dd != 0 else np.nan
    return dict(total=total, cagr=cagr, vol=vol, sharpe=sharpe,
                sortino=sortino, max_dd=dd, calmar=calmar)


def apply_annual_tax(daily_returns, tax_rate=0.15):
    """Indian short-term capital gains tax approximation.

    Scales each tax year's daily returns by (1 - tax_rate) when the year
    compounds to a net positive return. Loss years are unaffected (implicit
    intra-year loss offset). The linear scaling is an approximation of the
    true per-trade realized-gain tax — accurate enough for deployability
    analysis on daily-rebalanced strategies where most gains are short-term.

    For pre-tax analysis use the strategy_return column directly, or pass
    apply_tax=False to MacroStrategy."""
    out = daily_returns.copy()
    yrs = daily_returns.index.year
    annual = (1 + daily_returns).groupby(yrs).prod() - 1
    for y in annual.index:
        if annual[y] > 0:
            mask = (daily_returns.index.year == y)
            out.loc[mask] = daily_returns.loc[mask] * (1.0 - tax_rate)
    return out


def position_breakdown(res):
    """Counts of position states. Mutually exclusive — must sum to total days."""
    np_ = res["nifty_position"]; gp_ = res["gold_position"]
    long_n  = ((np_ ==  1.0)).sum()
    short_n = ((np_ == -1.0)).sum()
    long_g  = ((np_ ==  0.0) & (gp_ == 1.0)).sum()
    flat    = ((np_ ==  0.0) & (gp_ == 0.0)).sum()
    return {"long_nifty": int(long_n), "short_nifty": int(short_n),
            "long_gold": int(long_g), "flat": int(flat),
            "total": int(long_n + short_n + long_g + flat)}


def make_combiner(rotate_stress=False, rotate_panic=False, use_momentum_gold=False,
                  use_supply_shock=False, gold_gate_external=True):
    """v1.4 default combiner: SlowStressSignal replaces SupplyShockSignal
    as the stress-flat trigger, G10 gold gate (external macro confirmation +
    upper momentum cap) replaces legacy `gold_10d > 0` gate.

    For v1.3 backward compatibility:
        make_combiner(use_supply_shock=True, gold_gate_external=False)
    """
    rf = RegimeFilter(window=100)
    c = SignalCombiner(regime_filter=rf,
                       rotate_to_gold_on_stress_flat=rotate_stress,
                       rotate_to_gold_on_panic_short=rotate_panic,
                       rotate_with_momentum=use_momentum_gold,
                       gold_gate_external=gold_gate_external)
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    if use_supply_shock:
        # Legacy v1.3 supply-shock — acute 10d multi-asset AND composite.
        # Uses add_exit (with NIFTY-momentum cooldown extension) for v1.3
        # backward-compat.
        c.add_exit(SupplyShockSignal(window=10, oil_threshold=0.03,
                                     inr_threshold=0.01, vix_threshold=0.20))
    else:
        # v1.4 default — slow-stress signal catches 2013 taper, 2018 NBFC
        # style sustained EM stress that supply-shock missed. Uses
        # add_exit_no_cooldown because its windows (20d INR, 90d VIX-z) are
        # already slow — additional cooldown extension would over-extend
        # flat days and crush CAGR.
        c.add_exit_no_cooldown(SlowStressSignal(inr_window=20, inr_threshold=0.01,
                                                vix_z_window=90, vix_z_threshold=1.5,
                                                vix_mom_window=5))
    c.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)
    return c


# ---------------------------------------------------------------------------
# Main — LAB CONFIG RUNNER
# ---------------------------------------------------------------------------

import os as _os

def _load_data():
    """Load raw market data, using local _yf_cache.pkl if present (faster + offline)."""
    WARMUP = "2006-01-01"
    TICKERS = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS", "^TNX"]
    cache = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                          "_yf_cache.pkl")
    if _os.path.exists(cache):
        print(f"Loading cached market data from {cache} ...", file=sys.stderr)
        raw = pd.read_pickle(cache)
    else:
        print("Downloading market data ...", file=sys.stderr)
        raw = yf.download(TICKERS, start=WARMUP, end="2026-05-12",
                          auto_adjust=True, progress=False)["Close"]
        raw.dropna(how="all", inplace=True)
        raw.to_pickle(cache)
    for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
        if col in raw.columns:
            raw[col] = raw[col].ffill()
    if "GOLDBEES.NS" in raw.columns:
        fv = raw["GOLDBEES.NS"].first_valid_index()
        if fv is not None:
            raw.loc[raw.index >= fv, "GOLDBEES.NS"] = \
                raw.loc[raw.index >= fv, "GOLDBEES.NS"].ffill()
    # Load NSE CSV for Mom30
    parent = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    raw["NIFTYMOM30"] = load_nse_index_csv(
        _os.path.join(parent, "data", "momentum30_history.csv"),
        "NIFTYMOM30").reindex(raw.index).ffill()
    return raw


# ---------------------------------------------------------------------------
# Config catalog. Each config is a dict consumed by main(). The base
# combiner is the same v1.5 production for all configs; only the
# MacroStrategyLab kwargs change between configs.
# ---------------------------------------------------------------------------
CONFIG_CATALOG = {
    "C0": {
        "label": "C0 production v1.5 (baseline)",
        "enable_v2": False, "recovery_latch": None,
    },
    "C1": {
        "label": "C1 + V2 overlay",
        "enable_v2": True,  "recovery_latch": None,
    },
    "C2": {
        "label": "C2 + V2 + latch trend ≥3%",
        "enable_v2": True,  "recovery_latch": {"mode": "trend",       "x": 0.03},
    },
    "C3": {
        "label": "C3 + V2 + latch trend ≥5%",
        "enable_v2": True,  "recovery_latch": {"mode": "trend",       "x": 0.05},
    },
    "C4": {
        "label": "C4 + V2 + latch trend ≥8%",
        "enable_v2": True,  "recovery_latch": {"mode": "trend",       "x": 0.08},
    },
    "C5": {
        "label": "C5 + V2 + latch trend+macro ≥3%",
        "enable_v2": True,  "recovery_latch": {"mode": "trend_macro", "x": 0.03},
    },
    "C6": {
        "label": "C6 + V2 + latch trend+macro ≥5%",
        "enable_v2": True,  "recovery_latch": {"mode": "trend_macro", "x": 0.05},
    },
    "C7": {
        "label": "C7 + V2 + latch trend+macro ≥8%",
        "enable_v2": True,  "recovery_latch": {"mode": "trend_macro", "x": 0.08},
    },
    # NEW VARIANTS — all use latch T3 (Mom30 ≥3% above own 100-DMA) but
    # change WHAT IS HELD during the RECOVERY state.
    "C8": {
        "label": "C8 + V2 + T3, NIFTY+Gold inv-vol blend",
        "enable_v2": True,  "recovery_latch": {"mode": "trend", "x": 0.03},
        "recovery_allocation": "nif_gold_blend",
    },
    "C9": {
        "label": "C9 + V2 + T3, 100% Gold during recovery",
        "enable_v2": True,  "recovery_latch": {"mode": "trend", "x": 0.03},
        "recovery_allocation": "gold_only",
    },
    "C10": {
        "label": "C10 + V2 + T3, 100% NIFTY 50 during recovery",
        "enable_v2": True,  "recovery_latch": {"mode": "trend", "x": 0.03},
        "recovery_allocation": "nif_only",
    },
    "C11": {
        "label": "C11 + V2 + T3, gold (G10-gated) → cash",
        "enable_v2": True,  "recovery_latch": {"mode": "trend", "x": 0.03},
        "recovery_allocation": "gold_gated_cash",
    },
    "C12": {
        "label": "C12 + V2 + T3, gold (G10-gated) → Mom30",
        "enable_v2": True,  "recovery_latch": {"mode": "trend", "x": 0.03},
        "recovery_allocation": "gold_gated_mom",
    },
}


def run_config(name, cfg, raw, start, end, vol_target_annual):
    """Run a single config and return (post-tax daily series, diagnostics dict)."""
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

    log_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                            "results")
    log_path = _os.path.join(log_dir, f"strategy_lab_{name}_log.csv") if name != "C0" else None
    s = MacroStrategyLab(
        combiner,
        target="^NSEI", gold_target="GOLDBEES.NS",
        long_target="NIFTYMOM30", long_cost_bps=6,
        nifty_cost_bps=3, gold_cost_bps=5,
        cash_yield_haircut_bps=100,
        apply_tax=True, tax_rate=0.15,
        enable_v2=cfg["enable_v2"], v2_dd_threshold=0.15, v2_days=60,
        recovery_latch=cfg["recovery_latch"],
        recovery_allocation=cfg.get("recovery_allocation", "mom_gold_blend"),
        vol_target_annual=vol_target_annual,
        vol_window=60,
        log_path=log_path,
    )
    result = s.run(raw)
    if isinstance(result, tuple):
        df, diag = result
    else:
        df = result; diag = {}
    df = df.loc[start:end]
    return df, diag


def main():
    START, END = "2008-04-01", "2025-12-31"
    raw = _load_data()

    # ── Run C0 first to establish target vol (used by latch configs) ──
    print("\nRunning C0 (production v1.5 baseline) ...", file=sys.stderr)
    c0_cfg = CONFIG_CATALOG["C0"]
    df0, _ = run_config("C0", c0_cfg, raw, START, END, vol_target_annual=None)
    # Pre-tax vol of base — used as vol target for the recovery blends
    target_vol = float(df0["strategy_return_pretax"].std() * np.sqrt(252))
    print(f"Target vol (C0 full-sample pre-tax realized): {target_vol*100:.2f}%", file=sys.stderr)

    # ── Run all configs ──
    runs = [("C0", c0_cfg["label"], df0, {})]
    for name in ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12"]:
        cfg = CONFIG_CATALOG[name]
        print(f"Running {name} ({cfg['label']}) ...", file=sys.stderr)
        df, diag = run_config(name, cfg, raw, START, END, vol_target_annual=target_vol)
        runs.append((name, cfg["label"], df, diag))

    # ── Sanity check: C0 should reproduce strategy.py headline numbers ──
    print("\n" + "=" * 110)
    print("  SANITY: C0 reproduction check (should match strategy.py default)")
    print("=" * 110)
    m0 = metrics(df0["strategy_return"])
    print(f"  C0 post-tax CAGR:   {m0['cagr']*100:+.4f}%   (expected ~15.64%)")
    print(f"  C0 post-tax Sharpe: {m0['sharpe']:.4f}        (expected ~0.786)")
    print(f"  C0 post-tax MaxDD:  {m0['max_dd']*100:+.4f}% (expected ~-14.67%)")

    # ── Headline comparison ──
    print("\n" + "=" * 130)
    print("  HEADLINE METRICS (post-tax)")
    print("=" * 130)
    print(f"  {'Cfg':<4} {'Label':<38} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} "
          f"{'MaxDD':>9} {'ΔCAGR':>9} {'ΔSharpe':>9}")
    print("  " + "-" * 4 + " " + "-" * 38 + " " + "-" * 9 + " " + "-" * 8 + " "
          + "-" * 8 + " " + "-" * 9 + " " + "-" * 9 + " " + "-" * 9)
    base_m = None
    for name, label, df, diag in runs:
        m = metrics(df["strategy_return"])
        if name == "C1": base_m = m  # base for Δ comparisons
        if base_m is None or name in ("C0", "C1"):
            print(f"  {name:<4} {label:<38} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} "
                  f"{m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% "
                  f"{'—':>9} {'—':>9}")
        else:
            dc = m["cagr"] - base_m["cagr"]
            ds = m["sharpe"] - base_m["sharpe"]
            print(f"  {name:<4} {label:<38} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} "
                  f"{m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% "
                  f"{dc*100:+8.2f}pp {ds:+9.3f}")
    print()

    # ── Year-by-year ──
    print("=" * 130)
    print("  YEAR-BY-YEAR (post-tax)")
    print("=" * 130)
    years = sorted(set(df0.index.year))
    hdr = f"  {'Year':<6}"
    for name, label, df, diag in runs:
        hdr += f" {name:>9}"
    print(hdr)
    print("  " + "-" * 6 + (" " + "-" * 9) * len(runs))
    for y in years:
        row = f"  {y:<6}"
        for name, label, df, diag in runs:
            s = df["strategy_return"][df.index.year == y]
            yr = float((1 + s).prod() - 1) if len(s) else 0.0
            row += f" {yr*100:>+8.2f}%"
        print(row)
    print()

    # ── State breakdown for latch configs ──
    print("=" * 130)
    print("  RECOVERY STATE BREAKDOWN — days in each state per config")
    print("=" * 130)
    print(f"  {'Cfg':<4} {'NON_LONG':>10} {'RECOVERY':>10} {'ESTABLISHED':>13} "
          f"{'V2 active':>10}")
    print("  " + "-" * 4 + " " + "-" * 10 + " " + "-" * 10 + " " + "-" * 13 + " " + "-" * 10)
    for name, label, df, diag in runs:
        if not diag or "lab_state" not in diag:
            print(f"  {name:<4}    (no state machine — C0 baseline)")
            continue
        state = diag["lab_state"].reindex(df.index)
        v2 = diag["v2_active"].reindex(df.index)
        n_nl  = int((state == "NON_LONG").sum())
        n_rec = int((state == "RECOVERY").sum())
        n_est = int((state == "ESTABLISHED").sum())
        n_v2  = int(v2.sum())
        print(f"  {name:<4} {n_nl:>10d} {n_rec:>10d} {n_est:>13d} {n_v2:>10d}")
    print()

    # ── Where to find per-day logs ──
    log_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                            "results")
    print(f"  Per-day logs written to: {log_dir}/strategy_lab_<C1-C7>_log.csv")
    print(f"  (grep any date to see the state + weights + pnl that day)")
    print()


if __name__ == "__main__":
    main()

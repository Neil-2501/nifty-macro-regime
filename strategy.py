"""
Modular Macro Strategy Framework — Indian Markets (canonical, v2.2)

Production config: Config 7 (v2.1 core) + defensive quality basket overlay
(v2.2 addition, ON BY DEFAULT). Composition:
  - Bull long-side asset: NIFTYMOM30 index
  - Post-bear NIFTY 50 recovery window (V2 overlay)
  - 5-day slow-stress cooldown
  - 15% drawdown gate on panic-short
  - Defensive quality basket on stress-flat days after 40-day persistence gate
    (50% basket + 50% cash blend, 30 bps/side, STCG 15%/20%). REPLACES the
    Config 7 G10 gold rotation on stress-flat days (see "superseded" note below).

Superseded (kept as opt-in research code):
  - v2.1 G10 momentum-gated gold rotation on stress-flat days. Replaced in v2.2
    by the defensive quality basket. Gold code is retained in the combiner and
    fires internally; its output is zeroed at the strategy layer when
    enable_defensive_basket=True. Set enable_defensive_basket=False to
    reproduce v2.1's gold rotation byte-for-byte.

Canonical numbers (post-tax, 2008-04-01 → 2026-05-11, 2026 partial ~4.5 months;
Sharpe = rf-adjusted using RBI repo rate):
  Config 7 baseline (defensive OFF, gold ON):  16.52% CAGR / Sharpe 0.81 / MaxDD -12.78%
  R1 production   (defensive ON, gold OFF):    16.85% CAGR / Sharpe 0.83 / MaxDD -13.92%
  Defensive-basket delta:            +0.33pp CAGR, +0.02 Sharpe, -1.13pp MaxDD (FULL)
                                     +0.15pp CAGR, +0.01 Sharpe, +1.90pp MaxDD (OOS 2017+)
  Framing: marginal, ~Sharpe-neutral change; not a slam-dunk improvement.

Seven configs (1-7) shipped for production / backward compat:
  Config 1 — no gold rotation (cash on every flat day, panic-short retained)
  Config 2 — gold throughout entire stress-flat latch (v1.1.1 production)
  Config 3 — gold replaces panic short (rotation instead of active short)
  Config 4 — gold momentum-gated, panic-short retained (v1.2 production)
  Config 5 — Config 4 + NIFTYMIDCAP150 long-side asset (v1.3)
  Config 6 — Config 4 + NIFTYMOM30 long-side asset (v1.5 production)
  Config 7 — Config 6 + V2 overlay + 5-day slow-stress lock +
             15% drawdown gate on panic-short (v2.1 core)

v2.2 production = Config 7 + defensive quality basket overlay
                  (enable_defensive_basket=True by default in MacroStrategy).
  Set enable_defensive_basket=False to reproduce Config 7 baseline exactly.

EXPERIMENTAL / INACTIVE — CompositionSwapOverlay (composition swap on Mom30 → NIFTY 50)
was tested as v4/v5 research; on the corrected NIFTY Midcap 150 data no
parameterization reliably beat Config 7. Code is retained but disabled by
default (enable_composition_swap=False). NOT part of production.

Key v2.1 changes vs v2.0:
  - Panic-short DD gate: panic-short fires only when NIFTY's drawdown from
    its trailing 60-day high exceeds 15%. Confirmation requirement: the VIX
    spike alone doesn't trigger a short; price must have already shown ≥15%
    damage. Suppresses 2 historically false fires (2013-08-27 taper, 2022-02-24
    Ukraine reaction). Preserves all 4 of the 2008 GFC panic-shorts. Cost:
    2 of 16 COVID-2020 fires are suppressed at the early DD<15% stage, but
    subsequent fires within the run still catch the move. Net effect:
    flat CAGR (-0.03pp), Sharpe 0.830 → 0.841, MaxDD -13.38% → -12.78%.

Key v2.0 changes vs v1.5:
  - V2 overlay: after each NIFTY bear→bull regime flip where the preceding
    bear-regime peak-to-trough drawdown was ≥15%, hold NIFTY 50 (not Mom30)
    for the next 60 trading days on every LONG day. Mom30 underperforms
    large-caps in V-recovery windows; NIFTY 50 captures the broad recovery.
    +1.00pp CAGR contribution vs Config 6.
  - 5-day slow-stress lock: after each unsuppressed slow-stress firing event,
    suppress raw slow-stress fires for the next 5 trading days. Continuous
    runs (consecutive firing days) are not suppressed. Prevents the
    whipsaw re-fire pattern that caused the 2019 bleed. +0.14pp CAGR + 1.29pp
    shallower MaxDD vs Config 6+V2.

Key v1.2 changes vs v1.1.1:
  - Gold rotation now uses a per-latch momentum state machine (Config 4):
    enter gold at latch start only if gold 10d momentum > 0; exit if
    momentum turns negative; once exited mid-latch, stay in cash for the
    rest of the latch. Addresses the 2026 OOS failure where gold was held
    through an 11% decline because Config 2 had no exit-side risk control.
  - Cash yield assumes a 100 bps haircut on RBI repo rate by default.
    Models liquid-fund spread (~50 bps) + TER (~10-25 bps) + auto-sweep
    frictions. Set cash_yield_haircut_bps=0 to recover v1.1.1 "full repo".

Architecture:
  - Three-lane signal combiner (entry / exit / short) with regime-filter gate
  - Dual-asset positions: nifty_position + gold_position emitted by combiner
  - V2 overlay (optional): bear→bull flip detection with prior-DD threshold,
    asset swap from Mom30 to NIFTY 50 for the next 60 trading days
  - Per-asset transaction costs (NIFTY 3 bps, Mom30 6 bps, gold 5 bps,
    cash sweep 0 bps)
  - Time-varying RBI repo rate (minus 100bps haircut) credited on fully-flat
    days (sourced from RBI MPC press releases, hardcoded as
    RBI_REPO_RATE_HISTORY step function)
  - Gold instrument: GOLDBEES.NS (NSE-listed gold ETF, INR-denominated).
    Series begins 2009-01-02; pre-2009 stress-flat days remain in cash.

v1.0 (no gold, no cash yield) preserved in git history at commit c2860fc.
v1.1.1 (Config 2, full repo) preserved at commit 078878a.
v1.5 (Mom30 + gold-in-bull fix) preserved at commit 4e0fefe.
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


class PanicShortWithDDGate(PanicShortSignal):
    """v2.1 panic-short with drawdown-depth confirmation gate.

    Fires only when the base panic-short conditions hold AND NIFTY's
    drawdown from its trailing `dd_lookback`-day high exceeds `dd_threshold`.

    Rationale: VIX-spike-based panic-short signals can fire on isolated
    intraday vol events that don't represent real downside. Requiring
    confirmed price damage (DD ≥ 15% from rolling high) filters these out.
    Historically suppresses 2013-08-27 taper false fire and 2022-02-24
    Ukraine-reaction false fire. All 4 of the 2008 GFC panic-shorts (DD
    16-32%) are preserved.

    Backward compat: dd_threshold=0 reproduces vanilla PanicShortSignal."""
    name = "panic_short_dd_gated"

    def __init__(self, dd_threshold=0.15, dd_lookback=60, **kwargs):
        super().__init__(**kwargs)
        self.dd_threshold = dd_threshold
        self.dd_lookback = dd_lookback

    def compute(self, data):
        raw = super().compute(data)
        if self.dd_threshold <= 0:
            return raw
        nifty = data["^NSEI"].ffill()
        trailing_max = nifty.rolling(self.dd_lookback, min_periods=1).max()
        dd = 1.0 - nifty / trailing_max
        gate_passes = dd > self.dd_threshold
        firing = (raw < 0) & gate_passes
        out = pd.Series(0.0, index=raw.index, name=self.name)
        out[firing] = -1.0
        return out

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

class SlowStressWithLockSignal(SlowStressSignal):
    """v2.0 wrap around SlowStressSignal — adds an N-day post-firing lock.

    After each unsuppressed firing event, suppress raw slow-stress fires for
    the next `lock_days` trading days. Continuous runs (consecutive raw
    firing days) are NOT suppressed — once a run starts, all its days are
    allowed. Effect: after the strategy re-enters long following a stress
    flat, it cannot be re-flatted by slow-stress for `lock_days` days.

    Rationale: the 2019 bleed (and similar episodes in 2013, 2022) came from
    slow-stress firing on a 1-day spike, forcing flat, then re-firing again
    2-5 days later as conditions chopped around the threshold. The lock
    prevents this whipsaw without interfering with persistent stress (COVID,
    GFC, 2018 NBFC) where runs are continuous through their lifetime.

    Backward compat: lock_days=0 reproduces vanilla SlowStressSignal behavior."""
    name = "slow_stress_locked"

    def __init__(self, lock_days=5, **kwargs):
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
                # else: suppressed (within lock window from previous run)
            else:
                if in_active_run:
                    in_active_run = False
        return pd.Series(out, index=raw.index, name=self.name)


class CompositionSwapOverlay:
    """v2.2 — symmetric composition-conditional Mom30 → NIFTY 50 swap overlay.

    SYMMETRIC FRAMEWORK
    For each cap segment X ∈ {mid, small}, the entry trigger fires when:
        β_X > beta_threshold  AND  segment X < its own DMA-window MA
    where β values come from a no-intercept rolling 60-day OLS:
        Mom30_ret = β_large × NIFTY50_ret + β_mid × Midcap150_ret + β_small × Smallcap250_ret
    (anchored at t−1 to prevent look-ahead).

    β_large is structurally excluded — swapping NIFTY 50 into itself is meaningless.

    HISTORICAL REALITY
    Only the MID arm has ever fired. β_small never crosses 0.75 (max ever 0.619
    in 2020) because Mom30 picks stocks from NIFTY 200, which excludes the
    Smallcap 250 universe by definition. The SMALL arm is included for
    completeness — it extends automatically if Mom30 ever drifts into
    smallcap-tracked exposure.

    ENTRY: ANY arm fires AND baseline is in long_mom_default state.
    HOLD: full swap from Mom30 → NIFTY 50 on the long leg.
    YIELD: baseline transitions out of long_mom_default → swap drops immediately
    (slow-stress, panic-short, gold rotation, V2 overlay all take priority).
    AND-EXIT: for each arm that fired at entry, β_X < threshold AND segment X
    > DMA must hold for `persistence_days`, AND Mom30 `recovery_lookback`-day
    return ≥ NIFTY 50 `recovery_lookback`-day return for the same window.
    TIME CAP: `max_hold_days` (safety; has never bound historically).

    Data requirements: NIFTYMOM30, ^NSEI, NIFTYMIDCAP150, NIFTYSMALLCAP250
    must all be present in the data DataFrame. If any is missing, the overlay
    returns an all-False signal and the strategy reverts to v2.1 behavior.
    """

    def __init__(self, beta_threshold=0.75, segment_dma=100,
                 persistence_days=5, max_hold_days=252,
                 recovery_lookback=60, window=60,
                 betas_csv=None):
        self.beta_threshold = beta_threshold
        self.segment_dma = segment_dma
        self.persistence_days = persistence_days
        self.max_hold_days = max_hold_days
        self.recovery_lookback = recovery_lookback
        self.window = window
        # If `betas_csv` is provided, load pre-computed β values from disk and
        # use them instead of re-computing inline. Production usage points this
        # at `data/composition_betas_unconstrained.csv` — which is generated by
        # `experiments/composition_regression.py`. The inline regression path
        # remains as a fallback when no CSV is provided; note that it depends
        # on the exact price series loaded into `data` and can drift from the
        # research-CSV path when Midcap/Smallcap data sources differ.
        self.betas_csv = betas_csv
        self._betas_cache = None
        if betas_csv is not None:
            try:
                _df = pd.read_csv(betas_csv)
                _df = _df.rename(columns={_df.columns[0]: "date"})
                _df["date"] = pd.to_datetime(_df["date"])
                _df = _df.set_index("date")
                self._betas_cache = (_df["beta_mid"], _df["beta_small"])
            except (FileNotFoundError, KeyError) as _e:
                print(f"WARNING: composition betas CSV unreadable "
                      f"({betas_csv}): {_e}. Falling back to inline regression.",
                      file=sys.stderr)
                self._betas_cache = None

    def _rolling_betas(self, data):
        """Resolve β_mid and β_small series, reindexed to data.index.

        Preferred path: use pre-computed β values from `betas_csv` (matches
        the research reference exactly, since the CSV was produced by the
        canonical composition_regression.py with consistent data sources).

        Fallback path: rolling no-intercept OLS computed inline from
        Mom30 / NIFTY 50 / Midcap 150 / Smallcap 250 returns. Returns drift
        from the CSV path when input price series differ in scale/base.
        """
        if self._betas_cache is not None:
            bm_csv, bs_csv = self._betas_cache
            return (bm_csv.reindex(data.index), bs_csv.reindex(data.index))

        needed = ["NIFTYMOM30", "^NSEI", "NIFTYMIDCAP150", "NIFTYSMALLCAP250"]
        if not all(c in data.columns for c in needed):
            return None, None

        def _native_returns(series):
            price_changed = series != series.shift(1)
            return series.pct_change().where(price_changed)

        mom_ret = _native_returns(data["NIFTYMOM30"])
        nif_ret = _native_returns(data["^NSEI"])
        mid_ret = _native_returns(data["NIFTYMIDCAP150"])
        sml_ret = _native_returns(data["NIFTYSMALLCAP250"])
        df = pd.DataFrame({"mom": mom_ret, "large": nif_ret,
                           "mid": mid_ret, "small": sml_ret}).dropna()
        n = len(df)
        bm = np.full(n, np.nan)
        bs = np.full(n, np.nan)
        y_arr = df["mom"].values
        X_arr = df[["large", "mid", "small"]].values
        w = self.window
        for t in range(w, n):
            y_w = y_arr[t - w:t]
            X_w = X_arr[t - w:t]
            try:
                b, *_ = np.linalg.lstsq(X_w, y_w, rcond=None)
                bm[t] = b[1]
                bs[t] = b[2]
            except np.linalg.LinAlgError:
                continue
        # β at index t is computed from y[t-w:t], X[t-w:t] — i.e., returns
        # through t-1. Already anchored at t-1; no additional shift required.
        bm_ser = pd.Series(bm, index=df.index, name="beta_mid").reindex(data.index)
        bs_ser = pd.Series(bs, index=df.index, name="beta_small").reindex(data.index)
        return bm_ser, bs_ser

    def compute_swap_active(self, data, long_mom_default):
        """State machine. Returns a boolean Series aligned to data.index — True
        on days the long leg should hold NIFTY 50 instead of Mom30."""
        idx = data.index
        beta_mid, beta_small = self._rolling_betas(data)
        if beta_mid is None:
            return pd.Series(False, index=idx, name="composition_swap_active")

        mid = data["NIFTYMIDCAP150"]
        sml = data["NIFTYSMALLCAP250"]
        mid_dma = mid.rolling(self.segment_dma, min_periods=50).mean()
        sml_dma = sml.rolling(self.segment_dma, min_periods=50).mean()
        # Match the v4 reference state machine: segment-weak flags use
        # current-day close vs current-day DMA (no shift). The β series above
        # is already t-1 anchored, which is the dominant look-ahead control.
        mid_weak = (mid < mid_dma).fillna(False)
        sml_weak = (sml < sml_dma).fillna(False)

        mom_p = data["NIFTYMOM30"]
        nif_p = data["^NSEI"]
        mom_lb = mom_p / mom_p.shift(self.recovery_lookback) - 1.0
        nif_lb = nif_p / nif_p.shift(self.recovery_lookback) - 1.0
        recovery_ok = (mom_lb >= nif_lb).fillna(False)

        n = len(idx)
        swap = np.zeros(n, dtype=bool)
        arr_bm = beta_mid.values
        arr_bs = beta_small.values
        arr_mw = mid_weak.values
        arr_sw = sml_weak.values
        arr_rec = recovery_ok.values
        arr_blm = long_mom_default.reindex(idx, fill_value=False).astype(bool).values

        is_active = False
        entry_pos = None
        entry_mid = False
        entry_small = False
        streak_ab = 0
        streak_c = 0

        for i in range(n):
            bm_i, bs_i = arr_bm[i], arr_bs[i]
            mw_i, sw_i = bool(arr_mw[i]), bool(arr_sw[i])
            blm_i = bool(arr_blm[i])
            recov_i = bool(arr_rec[i])

            trig_mid = (not pd.isna(bm_i)) and bm_i > self.beta_threshold and mw_i
            trig_small = (not pd.isna(bs_i)) and bs_i > self.beta_threshold and sw_i

            if not is_active:
                if (trig_mid or trig_small) and blm_i:
                    is_active = True
                    entry_pos = i
                    entry_mid = trig_mid
                    entry_small = trig_small
                    streak_ab = 0
                    streak_c = 0
            else:
                if not blm_i:
                    is_active = False
                    entry_pos = None
                    entry_mid = entry_small = False
                    streak_ab = streak_c = 0
                else:
                    # Per-arm clear: arm fired at entry → β below thresh AND segment above DMA
                    mid_clear = (not entry_mid) or (
                        (not pd.isna(bm_i)) and bm_i < self.beta_threshold and not mw_i)
                    sml_clear = (not entry_small) or (
                        (not pd.isna(bs_i)) and bs_i < self.beta_threshold and not sw_i)
                    ab_ok = mid_clear and sml_clear
                    streak_ab = streak_ab + 1 if ab_ok else 0
                    streak_c = streak_c + 1 if recov_i else 0
                    days_held = i - entry_pos
                    and_exit = (streak_ab >= self.persistence_days
                                and streak_c >= self.persistence_days)
                    time_cap = days_held >= self.max_hold_days
                    if and_exit or time_cap:
                        is_active = False
                        entry_pos = None
                        entry_mid = entry_small = False
                        streak_ab = streak_c = 0

            swap[i] = is_active

        return pd.Series(swap, index=idx, name="composition_swap_active")


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
    """v2.0: dual-asset PnL with per-asset transaction costs, RBI repo rate
    cash yield on fully-flat days, optional V2 post-bear-recovery NIFTY 50
    overlay."""

    def __init__(self, combiner, target="^NSEI", gold_target="GOLDBEES.NS",
                 nifty_cost_bps=3, gold_cost_bps=5,
                 cash_cost_bps=0,
                 use_cash_yield=True,
                 cash_yield_haircut_bps=100,
                 long_target="^NSEI",
                 long_cost_bps=3,
                 apply_tax=True, tax_rate=0.15,
                 enable_v2=False, v2_dd_threshold=0.15, v2_days=60,
                 v2_regime_window=100,
                 enable_composition_swap=False,
                 composition_beta_threshold=0.75,
                 composition_segment_dma=100,
                 composition_persistence_days=5,
                 composition_max_hold_days=252,
                 composition_recovery_lookback=60,
                 composition_betas_csv=None,
                 enable_defensive_basket=True,
                 defensive_basket_overlay=None):
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
        # v2.0: V2 overlay parameters. When enable_v2=True, after each NIFTY
        # bear→bull regime flip (price crosses above v2_regime_window-DMA)
        # where the preceding bear-regime peak-to-trough drawdown was ≥
        # v2_dd_threshold, hold NIFTY 50 (not long_target) for the next
        # v2_days trading days on every LONG day. Disabled by default for
        # backward compat with Configs 1-6.
        self.enable_v2 = enable_v2
        self.v2_dd_threshold = v2_dd_threshold
        self.v2_days = v2_days
        self.v2_regime_window = v2_regime_window
        # v2.2: composition swap overlay. When enable_composition_swap=True,
        # on long_mom_default days where the symmetric composition signal fires
        # (β_mid > threshold + Midcap weak, OR β_small > threshold + Smallcap weak),
        # hold NIFTY 50 instead of long_target until conditions clear. V2 and
        # other overlays take priority; composition swap only acts on days
        # baseline would otherwise default to Mom30.
        self.enable_composition_swap = enable_composition_swap
        if enable_composition_swap:
            self.composition_overlay = CompositionSwapOverlay(
                beta_threshold=composition_beta_threshold,
                segment_dma=composition_segment_dma,
                persistence_days=composition_persistence_days,
                max_hold_days=composition_max_hold_days,
                recovery_lookback=composition_recovery_lookback,
                betas_csv=composition_betas_csv)
        else:
            self.composition_overlay = None
        # v2.2: defensive quality basket overlay — ON by default in production.
        # Set enable_defensive_basket=False to reproduce Config 7 baseline exactly.
        # Overlay is post-processing on strategy_return (see defensive_basket.py).
        self.enable_defensive_basket = enable_defensive_basket
        self._defensive_basket_overlay = defensive_basket_overlay

    def _compute_v2_active(self, data):
        """V2 overlay: returns Series of bool — True on days within an active
        V2 NIFTY 50 hold window. A window opens on each bear→bull regime flip
        where the preceding bear-regime peak-to-trough drawdown was ≥
        self.v2_dd_threshold, and persists for self.v2_days trading days."""
        idx = data.index
        nifty = data[self.target].ffill()
        bull = (nifty > nifty.rolling(self.v2_regime_window, min_periods=1).mean())
        prev_bull = bull.shift(1, fill_value=False)
        flip = bull & (~prev_bull)
        flips = idx[flip.values]
        v2 = pd.Series(False, index=idx)
        for d in flips:
            p = idx.get_loc(d)
            if p == 0:
                continue
            # Walk back to find the start of the preceding bear window
            end = p - 1
            s = end
            while s > 0 and not bool(bull.iloc[s - 1]):
                s -= 1
            window = nifty.iloc[s:end + 1]
            if len(window) == 0:
                continue
            bear_dd = abs(float((window / window.cummax() - 1.0).min()))
            if bear_dd >= self.v2_dd_threshold:
                end_idx = min(p + self.v2_days, len(v2))
                v2.iloc[p:end_idx] = True
        return v2

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

        # v2.2: when the defensive quality basket is enabled, it REPLACES the
        # stress-flat allocation (gold/cash blend of Config 7). Force gold_pos
        # to 0 so gold rotation and defensive basket don't double-up on the
        # same stress-flat latch. The G10 gold-rotation code path in the
        # combiner still runs (positions computed above) — its output is just
        # zeroed at the strategy layer. Set enable_defensive_basket=False to
        # reproduce v2.1's gold-rotation behavior byte-for-byte.
        if self.enable_defensive_basket:
            gold_pos = pd.Series(0.0, index=gold_pos.index, name=gold_pos.name)

        # v2.0: V2 overlay — on LONG days inside a V2 window, hold NIFTY 50
        # instead of long_target. Otherwise behaves identically to v1.5.
        if self.enable_v2:
            v2_active = self._compute_v2_active(data)
        else:
            v2_active = pd.Series(False, index=data.index)

        long_mask = (nifty_pos == 1.0)
        # Default split: Mom30-bucket on long-not-V2 days, NIFTY-bucket on V2-active days
        long_mom_default = long_mask & ~v2_active
        long_v2_active   = long_mask &  v2_active

        # v2.2: composition swap overlay. On long_mom_default days where the
        # symmetric composition signal fires, divert from Mom30 → NIFTY 50.
        if self.enable_composition_swap and self.composition_overlay is not None:
            composition_swap_active = self.composition_overlay.compute_swap_active(
                data, long_mom_default)
        else:
            composition_swap_active = pd.Series(False, index=data.index)
        swap_on_long_mom = composition_swap_active & long_mom_default

        w_long_mom = (long_mom_default & ~swap_on_long_mom).astype(float)
        w_long_nif = (long_v2_active | swap_on_long_mom).astype(float)
        w_short    = (nifty_pos == -1.0).astype(float)

        # Per-asset costs (count transitions in each weight separately)
        cost_long_mom = w_long_mom.diff().abs() * (self.long_cost_bps  / 10000)
        cost_long_nif = w_long_nif.diff().abs() * (self.nifty_cost_bps / 10000)
        cost_short    = w_short.diff().abs()    * (self.nifty_cost_bps / 10000)
        cost_gold     = gold_pos.diff().abs()   * (self.gold_cost_bps  / 10000)

        # Per-asset PnL (yesterday's weight × today's return)
        pnl_long_mom = w_long_mom.shift(1) * long_returns
        pnl_long_nif = w_long_nif.shift(1) * nifty_returns
        pnl_short    = -w_short.shift(1)   * nifty_returns
        pnl_gold     = gold_pos.shift(1)   * gold_returns

        nifty_pnl = (pnl_long_mom + pnl_long_nif + pnl_short
                     - cost_long_mom - cost_long_nif - cost_short)
        gold_pnl  = pnl_gold - cost_gold

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

        # v2.2: defensive quality basket overlay — applied on stress-flat days
        # after 40-day persistence gate. Disable by setting enable_defensive_basket=False.
        defensive_basket_active = pd.Series(False, index=data.index, name="defensive_basket_active")
        if self.enable_defensive_basket:
            overlay = self._defensive_basket_overlay
            if overlay is None:
                from defensive_basket import DefensiveBasketOverlay
                overlay = DefensiveBasketOverlay()
                self._defensive_basket_overlay = overlay
            strategy_returns_overlaid = overlay.apply(strategy_returns, nifty_pos)
            # Track which days the overlay was active (for diagnostics)
            _, day_in_latch, is_flat = overlay._identify_latches(nifty_pos)
            defensive_basket_active = pd.Series(
                is_flat & (day_in_latch > overlay.persistence_days),
                index=data.index, name="defensive_basket_active")
            strategy_returns = strategy_returns_overlaid.rename("strategy_return")

        results = pd.DataFrame({
            "nifty_return":            nifty_returns,
            "gold_return":             gold_returns,
            "nifty_position":          nifty_pos,
            "gold_position":           gold_pos,
            "v2_active":               v2_active,
            "long_mom_default":        long_mom_default,
            "composition_swap_active": composition_swap_active,
            "defensive_basket_active": defensive_basket_active,
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
                  use_supply_shock=False, gold_gate_external=True,
                  slow_stress_lock_days=0,
                  panic_short_dd_threshold=0.0):
    """v1.4 default combiner: SlowStressSignal replaces SupplyShockSignal
    as the stress-flat trigger, G10 gold gate (external macro confirmation +
    upper momentum cap) replaces legacy `gold_10d > 0` gate.

    For v1.3 backward compatibility:
        make_combiner(use_supply_shock=True, gold_gate_external=False)

    v2.0 addition: set slow_stress_lock_days > 0 to wrap SlowStressSignal
    with the post-firing lock (used by Config 7). Default 0 = no lock
    (vanilla v1.4 behavior, preserved for Configs 1-6).

    v2.1 addition: set panic_short_dd_threshold > 0 to gate panic-short on
    NIFTY drawdown from trailing 60-day high. Used by Config 7. Default 0 =
    no gate (vanilla panic-short, preserved for Configs 1-6).
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
        # v2.0: optionally wrap with N-day post-firing lock (Config 7).
        if slow_stress_lock_days > 0:
            ss_signal = SlowStressWithLockSignal(
                lock_days=slow_stress_lock_days,
                inr_window=20, inr_threshold=0.01,
                vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
        else:
            ss_signal = SlowStressSignal(
                inr_window=20, inr_threshold=0.01,
                vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
        c.add_exit_no_cooldown(ss_signal)
    # v2.1: optionally wrap panic-short with NIFTY-DD confirmation gate
    if panic_short_dd_threshold > 0:
        panic_signal = PanicShortWithDDGate(
            dd_threshold=panic_short_dd_threshold, dd_lookback=60,
            vix_level=25, vix_spike=0.50, window=10, dma=100)
    else:
        panic_signal = PanicShortSignal(vix_level=25, vix_spike=0.50,
                                         window=10, dma=100)
    c.add_short(panic_signal, hold=False, max_hold_days=60,
                exit_ma_fast=5, exit_ma_slow=20)
    return c


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    WARMUP = "2006-01-01"
    START  = "2008-04-01"
    END    = "2025-12-31"
    # v1.4: ^TNX (US 10Y yield) added — required by G10 gold gate
    TICKERS = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS", "^TNX"]

    print("Downloading data ...", file=sys.stderr)
    raw = yf.download(TICKERS, start=WARMUP, end="2026-05-12",
                      auto_adjust=True, progress=False)["Close"]
    raw.dropna(how="all", inplace=True)
    # NOTE: do NOT ffill GOLDBEES.NS pre-2010 (no data → gold position must stay flat)
    # ffill the others (NSE/oil/INR/VIX/US10Y) for cross-market holiday alignment
    for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
        if col in raw.columns:
            raw[col] = raw[col].ffill()
    # GOLDBEES.NS: ffill ONLY after its first valid date (so intra-series holiday gaps
    # are filled, but pre-2010 stays NaN)
    if "GOLDBEES.NS" in raw.columns:
        first_valid = raw["GOLDBEES.NS"].first_valid_index()
        if first_valid is not None:
            mask = raw.index >= first_valid
            raw.loc[mask, "GOLDBEES.NS"] = raw.loc[mask, "GOLDBEES.NS"].ffill()
        gold_first = raw["GOLDBEES.NS"].first_valid_index()
        print(f"\nGOLDBEES.NS data starts: {gold_first.date() if gold_first else 'NONE'}",
              file=sys.stderr)

    # v1.3: load NSE CSV data for higher-alpha index substitution
    # v2.2: Smallcap 250 added — required by composition swap β regression
    try:
        midcap150   = load_nse_index_csv("data/midcap150_history.csv", "NIFTYMIDCAP150")
        mom30       = load_nse_index_csv("data/momentum30_history.csv", "NIFTYMOM30")
        smallcap250 = load_nse_index_csv("data/smallcap250_history.csv", "NIFTYSMALLCAP250")
        raw["NIFTYMIDCAP150"]   = midcap150.reindex(raw.index).ffill()
        raw["NIFTYMOM30"]       = mom30.reindex(raw.index).ffill()
        raw["NIFTYSMALLCAP250"] = smallcap250.reindex(raw.index).ffill()
        print(f"NIFTYMIDCAP150 first valid:   {raw['NIFTYMIDCAP150'].first_valid_index().date()}",
              file=sys.stderr)
        print(f"NIFTYMOM30 first valid:       {raw['NIFTYMOM30'].first_valid_index().date()}",
              file=sys.stderr)
        print(f"NIFTYSMALLCAP250 first valid: {raw['NIFTYSMALLCAP250'].first_valid_index().date()}",
              file=sys.stderr)
    except FileNotFoundError as e:
        print(f"WARNING: NSE CSV missing — Configs 5/6/7/8 may be affected. ({e})", file=sys.stderr)

    # v1.3: configs list with optional MacroStrategy kwargs as 3rd tuple element.
    # Configs 1-4 use defaults (long_target="^NSEI", long_cost_bps=3) — backward compatible.
    # Configs 5-6 substitute the long-side asset to capture higher-alpha bull-regime exposure.
    configs = [
        ("Config 1 (no gold)",                make_combiner(False, False),                          {}),
        ("Config 2 (gold flat)",              make_combiner(True,  False),                          {}),
        ("Config 3 (gold all)",               make_combiner(True,  True),                           {}),
        ("Config 4 (gold momentum)",          make_combiner(True,  False, use_momentum_gold=True),  {}),
        ("Config 5 (v1.3 Midcap 150)",        make_combiner(True,  False, use_momentum_gold=True),
            {"long_target": "NIFTYMIDCAP150", "long_cost_bps": 6}),
        ("Config 6 (v1.5 Momentum 30)",       make_combiner(True,  False, use_momentum_gold=True),
            {"long_target": "NIFTYMOM30",     "long_cost_bps": 6}),
        # v2.1 production: Config 6 + V2 overlay + 5-day slow-stress lock +
        #                  15% DD gate on panic-short
        ("Config 7 (v2.1 PROD: Mom30+V2+L5+DD15)",
            make_combiner(True, False, use_momentum_gold=True,
                          slow_stress_lock_days=5,
                          panic_short_dd_threshold=0.15),
            {"long_target": "NIFTYMOM30",     "long_cost_bps": 6,
             "enable_v2": True, "v2_dd_threshold": 0.15, "v2_days": 60}),
        # NOTE: the composition swap overlay (CompositionSwapOverlay class)
        # is implemented and available via enable_composition_swap=True, but
        # no Config 8 is wired up because it does not beat Config 7 on the
        # corrected NIFTY Midcap 150 data. Retain for future testing only.
    ]

    runs = []
    for label, combiner, kwargs in configs:
        s = MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5, **kwargs)
        r = s.run(raw).loc[START:END].copy()
        runs.append((label, r))

    # ── Verification checks ───────────────────────────────────────────────
    print("\nVERIFICATION CHECKS")
    print("=" * 60)
    for label, r in runs:
        bd = position_breakdown(r)
        check = "OK" if bd["total"] == len(r) else f"FAIL (sum {bd['total']} != {len(r)})"
        print(f"  {label}: {bd}  [days sum: {check}]")

    # Specific assertions — Configs 4/5/6 share the same signals so long-day
    # counts should be identical (only the underlying asset held differs).
    bd4 = position_breakdown(runs[3][1])
    bd5 = position_breakdown(runs[4][1]) if len(runs) > 4 else None
    bd6 = position_breakdown(runs[5][1]) if len(runs) > 5 else None
    print()
    print(f"  Cfg4 long days (^NSEI):      {bd4['long_nifty']}")
    print(f"  Cfg5 long days (Midcap 150): {bd5['long_nifty'] if bd5 else 'N/A'}")
    print(f"  Cfg6 long days (Momentum 30): {bd6['long_nifty'] if bd6 else 'N/A'}")
    match = bd5 and bd6 and bd4['long_nifty'] == bd5['long_nifty'] == bd6['long_nifty']
    print(f"  Long-day counts match across Cfg 4/5/6: {match}")

    # ── Comparison Table ──────────────────────────────────────────────────
    print(f"\n\nCONFIGURATION COMPARISON — 2008-2025, base costs (NIFTY 3 bps, gold 5 bps, "
          f"Midcap/Mom30 6 bps)")
    print("=" * 130)
    m = [metrics(r["strategy_return"]) for _, r in runs]
    bds = [position_breakdown(r) for _, r in runs]

    nifty_only = runs[0][1]["nifty_return"]
    m_nifty = metrics(nifty_only)

    n = len(runs)
    rows = [
        ("Cumulative return",   [f"{x['total']*100:>7.1f}%" for x in m]),
        ("CAGR",                [f"{x['cagr']*100:>7.2f}%"  for x in m]),
        ("Sharpe",              [f"{x['sharpe']:>8.2f}"     for x in m]),
        ("Sortino",             [f"{x['sortino']:>8.2f}"    for x in m]),
        ("Calmar",              [f"{x['calmar']:>8.2f}"     for x in m]),
        ("Max drawdown",        [f"{x['max_dd']*100:>7.1f}%" for x in m]),
        ("Annualized vol",      [f"{x['vol']*100:>7.2f}%"   for x in m]),
        ("Days long",           [f"{b['long_nifty']:>8d}"   for b in bds]),
        ("Days short",          [f"{b['short_nifty']:>8d}"  for b in bds]),
        ("Days long gold",      [f"{b['long_gold']:>8d}"    for b in bds]),
        ("Days flat",           [f"{b['flat']:>8d}"         for b in bds]),
    ]
    headers = ["Cfg1", "Cfg2", "Cfg3", "Cfg4", "Cfg5", "Cfg6", "Cfg7"][:n]
    subs    = ["(no gold)", "(gold flat)", "(gold all)", "(momentum)",
               "(Midcap150)", "(Mom30)", "(v2.0)"][:n]
    hdr = f"  {'Metric':<20}" + "".join(f" | {h:>10}" for h in headers)
    sub = f"  {'':<20}"        + "".join(f" | {s:>10}" for s in subs)
    print(hdr)
    print(sub)
    print("  " + "-" * 20 + ("+" + "-" * 12) * n)
    for label, vals in rows:
        print(f"  {label:<20}" + "".join(f" | {v:>10}" for v in vals))
    print(f"\n  (Reference) NIFTY B&H Sharpe={m_nifty['sharpe']:.2f}, "
          f"CAGR={m_nifty['cagr']*100:.2f}%, MaxDD={m_nifty['max_dd']*100:.1f}%")

    # ── Year-by-year ──────────────────────────────────────────────────────
    print("\n\nYEAR-BY-YEAR RETURNS (%)")
    yhdr = "  Year |   NIFTY" + "".join(f" | {h:>7}" for h in headers)
    print(yhdr)
    print("  -----+---------" + ("+---------" * n))
    annual_n = (1 + nifty_only).resample("YE").prod() - 1
    annuals = [(1 + r["strategy_return"]).resample("YE").prod() - 1 for _, r in runs]
    for ts in annual_n.index:
        yr = ts.year
        nv = annual_n.loc[ts] * 100
        vals = [a.loc[ts] * 100 for a in annuals]
        print(f"  {yr} | {nv:>+6.1f}%" + "".join(f" | {v:>+6.1f}%" for v in vals))

    # ── Crisis windows ────────────────────────────────────────────────────
    print("\n\nCRISIS WINDOWS")
    print("  Crisis        | Window           |   NIFTY" + "".join(f" | {h:>7}" for h in headers))
    print("  --------------+------------------+---------" + ("+---------" * n))
    crises = [
        ("GFC",            "2008-09-01", "2009-03-31"),
        ("Euro debt 2011", "2011-07-01", "2011-12-31"),
        ("Taper 2013",     "2013-05-01", "2013-09-30"),
        ("NBFC 2018",      "2018-09-01", "2019-02-28"),
        ("COVID 2020",     "2020-02-01", "2020-12-31"),
    ]
    for name, s, e in crises:
        nv = (1 + nifty_only.loc[s:e]).prod() - 1
        rs = [(1 + r["strategy_return"].loc[s:e]).prod() - 1 for _, r in runs]
        line = f"  {name:<13} | {s} to {e[:7]} | {nv*100:>+6.1f}%"
        line += "".join(f" | {v*100:>+6.1f}%" for v in rs)
        print(line)

    print()


if __name__ == "__main__":
    main()

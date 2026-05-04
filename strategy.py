"""
Modular Macro Strategy Framework — Indian Markets (canonical, v1.1)

Production config: Config 2 — gold rotation during stress flat, panic-short
retained for COVID-style regimes, RBI repo rate cash yield on fully-flat days.

Two other configs are run for comparison:
  Config 1 — no gold rotation (cash on every flat day, panic-short retained)
  Config 3 — gold replaces panic short (rotation instead of active short)

Architecture:
  - Three-lane signal combiner (entry / exit / short) with regime-filter gate
  - Dual-asset positions: nifty_position + gold_position emitted by combiner
  - Per-asset transaction costs (NIFTY 3 bps, gold 5 bps, cash sweep 0 bps)
  - Time-varying RBI repo rate credited on fully-flat days (sourced from
    RBI MPC press releases, hardcoded as RBI_REPO_RATE_HISTORY step function)
  - Gold instrument: GOLDBEES.NS (NSE-listed gold ETF, INR-denominated).
    Series begins 2009-01-02; pre-2009 stress-flat days remain in cash.

v1.0 (no gold, no cash yield) is preserved in git history at commit c2860fc.
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
                 rotate_to_gold_on_panic_short=False):
        self.entry_signals = []
        self.exit_signals = []
        self.short_signals = []
        self.regime_filter = regime_filter
        self.reentry_momentum_threshold = reentry_momentum_threshold
        self.rotate_to_gold_on_stress_flat = rotate_to_gold_on_stress_flat
        self.rotate_to_gold_on_panic_short = rotate_to_gold_on_panic_short

    def add_entry(self, signal, weight=1.0):
        self.entry_signals.append((signal, weight)); return self
    def add_exit(self, signal):
        self.exit_signals.append(signal); return self
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
                 use_cash_yield=True):
        self.combiner = combiner
        self.target = target
        self.gold_target = gold_target
        self.nifty_cost_bps = nifty_cost_bps
        self.gold_cost_bps  = gold_cost_bps
        self.cash_cost_bps  = cash_cost_bps   # bps to enter/exit cash sweep (default 0)
        self.use_cash_yield = use_cash_yield  # toggle cash yield on/off for sensitivity

    def run(self, data):
        nifty_returns = data[self.target].pct_change().rename("nifty_return")
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

        # Per-asset costs
        nifty_cost = nifty_pos.diff().abs() * (self.nifty_cost_bps / 10000)
        gold_cost  = gold_pos.diff().abs()  * (self.gold_cost_bps  / 10000)

        nifty_pnl = nifty_pos.shift(1) * nifty_returns - nifty_cost
        gold_pnl  = gold_pos.shift(1)  * gold_returns  - gold_cost

        # Cash yield on fully-flat days (no NIFTY exposure, no gold exposure)
        # Yield rate = RBI repo rate (time-varying, daily step function)
        cash_position = ((nifty_pos == 0.0) & (gold_pos == 0.0)).astype(float)
        if self.use_cash_yield:
            repo_rate = build_rbi_repo_rate_series(data.index)
            daily_cash_yield = repo_rate / 252
            cash_pnl = cash_position.shift(1) * daily_cash_yield
        else:
            cash_pnl = pd.Series(0.0, index=data.index)
        # Cost to enter/exit cash sweep (default 0 — institutional auto-sweep is free)
        cash_cost = cash_position.diff().abs() * (self.cash_cost_bps / 10000)

        strategy_returns = (nifty_pnl + gold_pnl + cash_pnl - cash_cost).rename("strategy_return")

        results = pd.DataFrame({
            "nifty_return":    nifty_returns,
            "gold_return":     gold_returns,
            "nifty_position":  nifty_pos,
            "gold_position":   gold_pos,
            "strategy_return": strategy_returns,
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


def make_combiner(rotate_stress=False, rotate_panic=False):
    rf = RegimeFilter(window=100)
    c = SignalCombiner(regime_filter=rf,
                       rotate_to_gold_on_stress_flat=rotate_stress,
                       rotate_to_gold_on_panic_short=rotate_panic)
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    c.add_exit(SupplyShockSignal(window=10, oil_threshold=0.03,
                                 inr_threshold=0.01, vix_threshold=0.20))
    c.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)
    return c


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    WARMUP = "2006-01-01"
    START  = "2008-04-01"
    END    = "2025-12-31"
    TICKERS = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS"]

    print("Downloading data ...", file=sys.stderr)
    raw = yf.download(TICKERS, start=WARMUP, end="2026-01-01",
                      auto_adjust=True, progress=False)["Close"]
    raw.dropna(how="all", inplace=True)
    # NOTE: do NOT ffill GOLDBEES.NS pre-2010 (no data → gold position must stay flat)
    # ffill the others (NSE/oil/INR/VIX) for cross-market holiday alignment
    for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX"]:
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

    # Run all three configs
    configs = [
        ("Config 1 (no gold)",       make_combiner(False, False)),
        ("Config 2 (gold flat)",     make_combiner(True,  False)),
        ("Config 3 (gold all)",      make_combiner(True,  True)),
    ]

    runs = []
    for label, combiner in configs:
        s = MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5)
        r = s.run(raw).loc[START:END].copy()
        runs.append((label, r))

    # ── Verification checks ───────────────────────────────────────────────
    print("\nVERIFICATION CHECKS")
    print("=" * 60)
    for label, r in runs:
        bd = position_breakdown(r)
        check = "OK" if bd["total"] == len(r) else f"FAIL (sum {bd['total']} != {len(r)})"
        print(f"  {label}: {bd}  [days sum: {check}]")

    # Specific assertions
    bd1 = position_breakdown(runs[0][1])
    bd2 = position_breakdown(runs[1][1])
    bd3 = position_breakdown(runs[2][1])
    print()
    print(f"  Days long gold > 0 in Config 2:  {bd2['long_gold'] > 0}  ({bd2['long_gold']})")
    print(f"  Days short NIFTY = 0 in Config 3: {bd3['short_nifty'] == 0}  ({bd3['short_nifty']})")
    print(f"  Days short NIFTY > 0 in Config 1: {bd1['short_nifty'] > 0}  ({bd1['short_nifty']})")
    print(f"  Days short NIFTY > 0 in Config 2: {bd2['short_nifty'] > 0}  ({bd2['short_nifty']})")

    # ── Comparison Table ──────────────────────────────────────────────────
    print("\n\nCONFIGURATION COMPARISON — 2008-2025, base costs (NIFTY 3 bps, gold 5 bps)")
    print("=" * 76)
    m = [metrics(r["strategy_return"]) for _, r in runs]
    bds = [position_breakdown(r) for _, r in runs]

    # NIFTY benchmark for reference
    nifty_only = runs[0][1]["nifty_return"]
    m_nifty = metrics(nifty_only)

    rows = [
        ("Cumulative return",   [f"{x['total']*100:>7.1f}%" for x in m]),
        ("CAGR",                [f"{x['cagr']*100:>7.2f}%"  for x in m]),
        ("Sharpe",              [f"{x['sharpe']:>8.2f}"     for x in m]),
        ("Sortino",             [f"{x['sortino']:>8.2f}"    for x in m]),
        ("Calmar",              [f"{x['calmar']:>8.2f}"     for x in m]),
        ("Max drawdown",        [f"{x['max_dd']*100:>7.1f}%" for x in m]),
        ("Annualized vol",      [f"{x['vol']*100:>7.2f}%"   for x in m]),
        ("Days long NIFTY",     [f"{b['long_nifty']:>8d}"   for b in bds]),
        ("Days short NIFTY",    [f"{b['short_nifty']:>8d}"  for b in bds]),
        ("Days long gold",      [f"{b['long_gold']:>8d}"    for b in bds]),
        ("Days flat",           [f"{b['flat']:>8d}"         for b in bds]),
    ]
    hdr = f"  {'Metric':<20}| {'Config 1':>10} | {'Config 2':>10} | {'Config 3':>10}"
    sub = f"  {'':<20}| {'(no gold)':>10} | {'(gold flat)':>10} | {'(gold all)':>10}"
    print(hdr)
    print(sub)
    print("  " + "-" * 20 + "+" + "-" * 12 + "+" + "-" * 12 + "+" + "-" * 11)
    for label, vals in rows:
        print(f"  {label:<20}| {vals[0]:>10} | {vals[1]:>10} | {vals[2]:>10}")
    print(f"\n  (Reference) NIFTY B&H Sharpe={m_nifty['sharpe']:.2f}, "
          f"CAGR={m_nifty['cagr']*100:.2f}%, MaxDD={m_nifty['max_dd']*100:.1f}%")

    # ── Year-by-year ──────────────────────────────────────────────────────
    print("\n\nYEAR-BY-YEAR RETURNS (%)")
    print("  Year |   NIFTY | Config 1 | Config 2 | Config 3")
    print("  -----+---------+----------+----------+---------")
    annual_n = (1 + nifty_only).resample("YE").prod() - 1
    annuals = [(1 + r["strategy_return"]).resample("YE").prod() - 1 for _, r in runs]
    for ts in annual_n.index:
        yr = ts.year
        nv = annual_n.loc[ts] * 100
        c1 = annuals[0].loc[ts] * 100
        c2 = annuals[1].loc[ts] * 100
        c3 = annuals[2].loc[ts] * 100
        print(f"  {yr} | {nv:>+6.1f}% | {c1:>+7.1f}% | {c2:>+7.1f}% | {c3:>+7.1f}%")

    # ── Crisis windows ────────────────────────────────────────────────────
    print("\n\nCRISIS WINDOWS")
    print("  Crisis    | Window           |   NIFTY | Config 1 | Config 2 | Config 3")
    print("  ----------+------------------+---------+----------+----------+---------")
    crises = [
        ("GFC",      "2008-09-01", "2009-03-31"),
        ("Taper",    "2013-05-01", "2013-09-30"),
        ("NBFC",     "2018-09-01", "2019-02-28"),
        ("COVID",    "2020-02-01", "2020-12-31"),
    ]
    for name, s, e in crises:
        nv = (1 + nifty_only.loc[s:e]).prod() - 1
        rs = [(1 + r["strategy_return"].loc[s:e]).prod() - 1 for _, r in runs]
        print(f"  {name:<9} | {s} to {e[:7]} | {nv*100:>+6.1f}% | "
              f"{rs[0]*100:>+7.1f}% | {rs[1]*100:>+7.1f}% | {rs[2]*100:>+7.1f}%")

    print()


if __name__ == "__main__":
    main()

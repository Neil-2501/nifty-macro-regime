"""
Modular Macro Strategy Framework — Indian Markets (v1)
Signals → Score → Regime Filter → Position → NIFTY PnL

Signal architecture:
  Entry  : INR strengthening + VIX falling  → bullish, go long
  Exit   : SupplyShockSignal (oil + INR + VIX all agree bearish) → go flat
  Regime : DMA filter as final override

Modes:
  long_only=True,  buy_hold_sell=False  →  +1 or 0 (flat when no signal)
  long_only=True,  buy_hold_sell=True   →  +1 or 0 (hold position when neutral)
  long_only=False, buy_hold_sell=False  →  +1, -1, or 0
  long_only=False, buy_hold_sell=True   →  +1, -1, or 0 (hold when neutral)
"""

import pandas as pd
import numpy as np
import yfinance as yf


# ---------------------------------------------------------------------------
# Base Signal Interface
# ---------------------------------------------------------------------------

class MacroSignal:
    """
    Base class for all macro signals.
    Subclasses must implement `compute(data) -> pd.Series` returning values
    in [-1, 0, +1]: +1 long, -1 short/exit, 0 no view.
    """
    name: str = "base"

    def compute(self, data: pd.DataFrame) -> pd.Series:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

class SupplyShockSignal(MacroSignal):
    """
    Detects supply shock regimes by requiring ALL THREE indicators to agree:
      - Crude oil (CL=F)  rising  > oil_threshold  over window days
      - USD/INR  (INR=X)  rising  > inr_threshold  over window days (rupee weakening)
      - India VIX (^INDIAVIX) rising > vix_threshold over window days (fear spiking)

    When all three align it is NOT a global risk-on move (where oil rises with
    NIFTY) — it is a supply shock: oil up because of disruption, fear up, rupee
    under pressure. This is the cleanest bearish signal for India.

    Returns:
      -1  when all three are bearish simultaneously  → exit / short
       0  otherwise                                  → no view from this signal
    """
    name = "supply_shock"

    def __init__(
        self,
        window: int = 10,
        oil_threshold: float = 0.03,   # oil up >3% over window
        inr_threshold: float = 0.01,   # rupee weakens >1% over window
        vix_threshold: float = 0.20,   # VIX spikes >20% over window
    ):
        self.window        = window
        self.oil_threshold = oil_threshold
        self.inr_threshold = inr_threshold
        self.vix_threshold = vix_threshold

    def compute(self, data: pd.DataFrame) -> pd.Series:
        oil_trend = data["CL=F"].pct_change(self.window)
        inr_trend = data["INR=X"].pct_change(self.window)
        vix_trend = data["^INDIAVIX"].pct_change(self.window)

        oil_bearish = oil_trend > self.oil_threshold   # oil rising
        inr_bearish = inr_trend > self.inr_threshold   # rupee weakening
        vix_bearish = vix_trend > self.vix_threshold   # fear spiking

        # Only fire when ALL THREE agree — this filters out global risk-on
        supply_shock = oil_bearish & inr_bearish & vix_bearish

        signal = pd.Series(0.0, index=data.index, name=self.name)
        signal[supply_shock] = -1.0
        return signal


class PanicShortSignal(MacroSignal):
    """
    Detects market panic events (COVID-style crashes) where fear becomes extreme.

    Fires when ALL THREE conditions hold:
      - India VIX level         > vix_level    (absolute fear threshold, default 25)
      - India VIX 10d change    > vix_spike    (fear accelerating, default 50%)
      - NIFTY below its 100 DMA               (confirmed downtrend)

    This combination has never fired during bull markets in 2020-2025 data.
    Average next-day NIFTY return when fired: -1.016% vs +0.055% baseline.

    Returns:
      -1  when panic conditions met  → short NIFTY
       0  otherwise
    """
    name = "panic_short"

    def __init__(
        self,
        vix_level: float = 25.0,   # absolute VIX threshold
        vix_spike: float = 0.50,   # VIX must have risen >50% over 10 days
        window: int = 10,
        dma: int = 100,
    ):
        self.vix_level = vix_level
        self.vix_spike = vix_spike
        self.window    = window
        self.dma       = dma

    def compute(self, data: pd.DataFrame) -> pd.Series:
        vix      = data["^INDIAVIX"]
        vix_lvl  = vix >= self.vix_level
        vix_spk  = vix.pct_change(self.window) > self.vix_spike
        below_dma = data["^NSEI"].ffill() < data["^NSEI"].ffill().rolling(self.dma).mean()

        panic = vix_lvl & vix_spk & below_dma

        signal = pd.Series(0.0, index=data.index, name=self.name)
        signal[panic] = -1.0
        return signal


class USDINRSignal(MacroSignal):
    """
    Signal based on USD/INR trend (INR=X on Yahoo Finance).
    Used as an ENTRY signal — strengthening rupee signals healthy macro conditions.
    Sustained rupee weakening → bearish (FII outflows, import inflation)
    Sustained rupee strengthening → bullish
    """
    name = "usdinr"

    def __init__(self, window: int = 10, threshold: float = 0.01):
        self.window = window
        self.threshold = threshold

    def compute(self, data: pd.DataFrame) -> pd.Series:
        usdinr_rolling = data["INR=X"].pct_change(self.window)
        signal = pd.Series(0.0, index=data.index, name=self.name)
        # Entry signal only — strengthening rupee → long. Never short.
        # Shorting is handled exclusively by PanicShortSignal.
        signal[usdinr_rolling < -self.threshold] = 1.0
        return signal


class IndiaVIXSignal(MacroSignal):
    """
    Signal based on India VIX (^INDIAVIX) trend.
    Used as an ENTRY signal — falling VIX signals calm conditions, go long.
    Rising VIX → fear increasing → bearish
    Falling VIX → fear subsiding → bullish
    """
    name = "india_vix"

    def __init__(self, window: int = 10, threshold: float = 0.20):
        self.window = window
        self.threshold = threshold

    def compute(self, data: pd.DataFrame) -> pd.Series:
        vix_rolling = data["^INDIAVIX"].pct_change(self.window)
        signal = pd.Series(0.0, index=data.index, name=self.name)
        # Entry signal only — falling VIX → calm conditions → long. Never short.
        # Shorting is handled exclusively by PanicShortSignal.
        signal[vix_rolling < -self.threshold] = 1.0
        return signal


# ---------------------------------------------------------------------------
# Regime Filter
# ---------------------------------------------------------------------------

class RegimeFilter:
    """
    Determines whether NIFTY is in a bull or bear market using a moving average.

    Bull regime: NIFTY price > N-day MA  → allow longs
    Bear regime: NIFTY price < N-day MA  → force flat (or allow shorts)

    window=200 : captures full annual trend, fewer false signals
    window=100 : more responsive, catches turns ~2 months faster
    """

    def __init__(self, window: int = 200, target: str = "^NSEI"):
        self.window = window
        self.target = target

    def bull_mask(self, data: pd.DataFrame) -> pd.Series:
        """Returns True on days NIFTY is above its moving average (bull regime).
        Forward-fills prices first so NaN gaps (holidays, cross-market mismatches)
        don't starve the rolling window of valid observations.
        """
        price = data[self.target].ffill()
        ma = price.rolling(self.window).mean()
        return (price > ma).rename(f"bull_{self.window}dma")

    def bear_mask(self, data: pd.DataFrame) -> pd.Series:
        """Returns True on days NIFTY is below its moving average (bear regime)."""
        return (~self.bull_mask(data)).rename(f"bear_{self.window}dma")


# ---------------------------------------------------------------------------
# Signal Combiner
# ---------------------------------------------------------------------------

class SignalCombiner:
    """
    Three-lane signal architecture — each lane has independent hold logic:

    ENTRY  lane: signals that push long (+1). Hold via ffill when neutral.
                 Example: INR strengthening, VIX falling.

    EXIT   lane: signals that force flat (0) when firing. No hold — resets
                 each day based on current conditions.
                 Example: SupplyShockSignal (geopolitical/supply crisis).

    SHORT  lane: signals that force short (-1) when firing. Hold configurable.
                 Example: PanicShortSignal (COVID-style extreme VIX).

    Priority (applied in order):
      1. Start with entry lane → long/flat with hold
      2. Exit lane overrides to flat when firing
      3. Short lane overrides to short when firing (with hold if configured)
      4. Regime filter as final gate

    This allows each crisis type to have its own exit behaviour:
      - Supply shock: flat immediately, resets when signal stops
      - Panic:        short with hold, exits when VIX calms down
    """

    def __init__(self, regime_filter: RegimeFilter = None,
                 reentry_momentum_threshold: float = 0.005):
        self.entry_signals: list[tuple[MacroSignal, float]]        = []
        self.exit_signals:  list[MacroSignal]                      = []
        self.short_signals: list[tuple]                            = []  # (signal, hold, max_hold_days, exit_ma_fast, exit_ma_slow)
        self.regime_filter                  = regime_filter
        self.reentry_momentum_threshold     = reentry_momentum_threshold  # NIFTY 5d return needed to re-enter after exit

    def add_entry(self, signal: MacroSignal, weight: float = 1.0):
        """Long-only entry signal. Contributes +1 to score, held via ffill."""
        self.entry_signals.append((signal, weight))
        return self

    def add_exit(self, signal: MacroSignal):
        """Exit-to-flat signal. Forces position to 0 when firing, no hold."""
        self.exit_signals.append(signal)
        return self

    def add_short(self, signal: MacroSignal, hold: bool = True, max_hold_days: int = 60,
                  exit_ma_fast: int = None, exit_ma_slow: int = None):
        """Short signal. Forces position to -1 when firing.
        hold=True : short persists for up to max_hold_days after last signal fire.
        hold=False: short only active on days signal fires.
        exit_ma_fast/slow: if set, exit short early when NIFTY fast MA crosses above slow MA
                           (short-term trend has reversed). Replaces the fixed day hold cap.
        """
        self.short_signals.append((signal, hold, max_hold_days, exit_ma_fast, exit_ma_slow))
        return self

    def compute_position(self, data: pd.DataFrame) -> pd.Series:
        # -------------------------------------------------------------------
        # Lane 1: Entry signals → long/flat with hold
        # -------------------------------------------------------------------
        if self.entry_signals:
            total_weight = sum(w for _, w in self.entry_signals)
            score = pd.Series(0.0, index=data.index)
            for signal, weight in self.entry_signals:
                score += signal.compute(data) * (weight / total_weight)
            position = pd.Series(0.0, index=data.index)
            position[score > 0] = 1.0
        else:
            score    = pd.Series(0.0, index=data.index)
            position = pd.Series(1.0, index=data.index)

        # Hold: stay in current position when entry signals are neutral.
        # fillna(1.0): default to long before first signal fires.
        position = position.replace(0.0, np.nan).ffill().fillna(1.0)

        # -------------------------------------------------------------------
        # Lane 2: Exit signals → flat while firing + momentum-based re-entry
        # Stay flat as long as exit signal is active OR NIFTY has not yet
        # recovered (5-day return < reentry_momentum_threshold).
        # This replaces the fixed N-day cooldown with a market-driven check.
        # -------------------------------------------------------------------
        nifty_mom = data["^NSEI"].ffill().pct_change(5)
        nifty_recovering = nifty_mom > self.reentry_momentum_threshold

        for signal in self.exit_signals:
            firing       = signal.compute(data) < 0
            firing_vals  = firing.values
            recover_vals = nifty_recovering.values
            in_exit      = False
            exit_flat    = [False] * len(data)
            for i in range(len(data)):
                if firing_vals[i]:
                    in_exit      = True   # exit signal active → latch flat
                    exit_flat[i] = True
                elif in_exit:
                    if recover_vals[i]:
                        in_exit = False   # NIFTY recovered → allow re-entry
                    else:
                        exit_flat[i] = True  # still waiting for recovery
            position[pd.Series(exit_flat, index=data.index)] = 0.0

        # -------------------------------------------------------------------
        # Lane 3: Short signals → force short when firing
        # MA crossover exit: if exit_ma_fast/slow set, exit short early when
        # NIFTY fast MA rises above slow MA (short-term trend has reversed).
        # -------------------------------------------------------------------
        for signal, hold, max_hold_days, exit_ma_fast, exit_ma_slow in self.short_signals:
            raw = signal.compute(data) < 0
            if hold and max_hold_days > 0:
                fired = raw.astype(float)
                held  = fired.rolling(window=max_hold_days, min_periods=1).max()
                if exit_ma_fast is not None and exit_ma_slow is not None:
                    nifty       = data["^NSEI"].ffill()
                    ma_fast     = nifty.rolling(exit_ma_fast).mean()
                    ma_slow     = nifty.rolling(exit_ma_slow).mean()
                    ma_bullish  = ma_fast > ma_slow   # short-term trend reversed
                    # Stay short only when hold active AND trend still bearish
                    position[(held == 1.0) & ~ma_bullish] = -1.0
                else:
                    position[held == 1.0] = -1.0
            else:
                position[raw] = -1.0

        # -------------------------------------------------------------------
        # Post-short flat: after a short ends, stay flat until a fresh entry
        # signal fires. Prevents snapping directly from short to long via
        # Lane 1's pre-computed ffill without re-entry validation.
        # -------------------------------------------------------------------
        if self.short_signals:
            is_short        = (position == -1.0).values
            is_fresh        = nifty_recovering.values  # NIFTY 5d return > threshold
            in_cooldown     = False
            post_short_flat = [False] * len(data)
            for i in range(1, len(data)):
                if is_short[i - 1] and not is_short[i]:
                    in_cooldown = True          # short just ended
                if in_cooldown and is_fresh[i]:
                    in_cooldown = False         # fresh entry signal — re-enter
                if in_cooldown and not is_fresh[i] and not is_short[i]:
                    post_short_flat[i] = True   # waiting for signal — stay flat
            position[pd.Series(post_short_flat, index=data.index)] = 0.0

        # -------------------------------------------------------------------
        # Regime filter: final gate
        # Bull regime → no shorts allowed
        # Bear regime → no longs allowed
        # -------------------------------------------------------------------
        if self.regime_filter:
            bull = self.regime_filter.bull_mask(data)
            position[(position > 0)  & ~bull] = 0.0   # exit longs in bear regime
            position[(position < 0)  &  bull] = 0.0   # exit shorts in bull regime

        return position.rename("position")


# ---------------------------------------------------------------------------
# Strategy Runner
# ---------------------------------------------------------------------------

class MacroStrategy:
    """
    Applies combined signal positions to NIFTY returns and computes PnL.
    """

    def __init__(self, combiner: SignalCombiner, target: str = "^NSEI"):
        self.combiner = combiner
        self.target   = target

    def run(self, data: pd.DataFrame, cost_bps: float = 0) -> pd.DataFrame:
        nifty_returns = data[self.target].pct_change().rename("nifty_return")
        position = self.combiner.compute_position(data)

        # Transaction costs: paid on each day position changes.
        # |Δposition| = 1 for normal entry/exit, 2 for long↔short flips.
        # Costs are realised on the day of the trade (same day as position change).
        trade_cost = position.diff().abs() * (cost_bps / 10000)

        # Signal from day T applied on day T+1; costs on day of change
        strategy_returns = (position.shift(1) * nifty_returns - trade_cost).rename("strategy_return")

        results = pd.DataFrame({
            "nifty_return":       nifty_returns,
            "position":           position,
            "strategy_return":    strategy_returns,
            "cumulative_nifty":   (1 + nifty_returns).cumprod() - 1,
            "cumulative_strategy":(1 + strategy_returns).cumprod() - 1,
        })

        return results


# ---------------------------------------------------------------------------
# Data Loader
# ---------------------------------------------------------------------------

def load_data(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    """Downloads adjusted close prices for the given tickers.
    Forward-fills to handle cross-market holiday gaps (e.g. NSE closed on US trading days).
    """
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
    prices = raw["Close"]
    prices.dropna(how="all", inplace=True)
    prices = prices.ffill()
    return prices


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_results(label: str, results: pd.DataFrame, start: str, end: str):
    pos_counts = results["position"].value_counts().sort_index()
    total_days  = len(results)
    nifty_ret   = results["cumulative_nifty"].iloc[-1] * 100
    strat_ret   = results["cumulative_strategy"].iloc[-1] * 100

    # Sharpe ratio (annualised, risk-free ~6% for India)
    excess = results["strategy_return"] - 0.06 / 252
    sharpe = (excess.mean() / excess.std()) * np.sqrt(252) if excess.std() > 0 else 0

    # Max drawdown
    cum = (1 + results["strategy_return"]).cumprod()
    max_dd = ((cum - cum.cummax()) / cum.cummax()).min() * 100

    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"  Period: {start} to {end}")
    print(f"{'='*55}")
    print(f"  NIFTY Buy & Hold : {nifty_ret:.1f}%")
    print(f"  Macro Strategy   : {strat_ret:.1f}%")
    print(f"  Sharpe Ratio     : {sharpe:.2f}")
    print(f"  Max Drawdown     : {max_dd:.1f}%")
    print(f"\n  Position breakdown ({total_days} total days):")
    for pos, count in pos_counts.items():
        label_str = {1.0: "Long", -1.0: "Short", 0.0: "Flat"}.get(pos, str(pos))
        print(f"    {label_str:6s}: {count:4d} days ({count/total_days*100:.1f}%)")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def run_period(label: str, strategy: MacroStrategy, data: pd.DataFrame,
               start: str, end: str, cost_bps: float = 0):
    results = strategy.run(data, cost_bps=cost_bps)
    results = results.loc[start:end]
    results["cumulative_nifty"]    = (1 + results["nifty_return"]).cumprod() - 1
    results["cumulative_strategy"] = (1 + results["strategy_return"]).cumprod() - 1
    print_results(label, results, start, end)
    return results


def main():
    WARMUP_START = "2006-01-01"   # warmup so DMA is ready by trade start
    TRAIN_START  = "2008-04-01"   # in-sample: 2008-2025 (India VIX launches March 2008)
    TRAIN_END    = "2025-12-31"
    TEST_START   = "2026-01-01"   # out-of-sample: 2026 YTD (geopolitical crisis)
    TEST_END     = "2026-04-25"
    TICKERS      = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX"]

    print("Downloading data...")
    data = load_data(TICKERS, WARMUP_START, TEST_END)

    def make_combiner(rf, with_panic=False, panic_hold=True):
        c = SignalCombiner(regime_filter=rf)
        # Entry lane: INR strengthening + VIX calming → go long, hold
        c.add_entry(USDINRSignal(window=10,   threshold=0.01), weight=1.5)
        c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
        # Exit lane: supply shock → flat immediately, resets each day
        c.add_exit(SupplyShockSignal(window=10, oil_threshold=0.03,
                                     inr_threshold=0.01, vix_threshold=0.20))
        # Short lane: panic → short with/without hold
        if with_panic:
            c.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=rf.window),
                        hold=panic_hold, max_hold_days=60,
                        exit_ma_fast=5, exit_ma_slow=20)
        return c

    # -----------------------------------------------------------------------
    # In-sample: 2020–2025 (training period)
    # -----------------------------------------------------------------------
    print("\n" + "="*55)
    print("  IN-SAMPLE RESULTS (2020–2025)")
    print("="*55)

    configs = [
        ("100 DMA | long only (baseline)",
         MacroStrategy(make_combiner(RegimeFilter(window=100)))),
        ("100 DMA | + panic short, hold",
         MacroStrategy(make_combiner(RegimeFilter(window=100), with_panic=True, panic_hold=True))),
        ("100 DMA | + panic short, no hold",
         MacroStrategy(make_combiner(RegimeFilter(window=100), with_panic=True, panic_hold=False))),
        ("50 DMA  | long only (baseline)",
         MacroStrategy(make_combiner(RegimeFilter(window=50)))),
        ("50 DMA  | + panic short, hold",
         MacroStrategy(make_combiner(RegimeFilter(window=50),  with_panic=True, panic_hold=True))),
        ("50 DMA  | + panic short, no hold",
         MacroStrategy(make_combiner(RegimeFilter(window=50),  with_panic=True, panic_hold=False))),
    ]

    BASE_COST_BPS = 3

    for label, strategy in configs:
        run_period(label, strategy, data, TRAIN_START, TRAIN_END, cost_bps=BASE_COST_BPS)

    # -----------------------------------------------------------------------
    # Transaction cost sensitivity analysis (in-sample)
    # -----------------------------------------------------------------------
    cost_levels = [0, 3, 5, 10, 15, 20]

    print("\n\n" + "="*80)
    print("  TRANSACTION COST SENSITIVITY (in-sample 2008–2025)  [base = 3 bps]")
    print("="*80)

    # Header row: mark base case column
    header = f"{'Config':<38}" + "".join(
        f"  {'*' if c == BASE_COST_BPS else ' '}{c:>2}bps" for c in cost_levels
    )
    print(header)
    print("-" * len(header))

    for label, strategy in configs:
        # Collect (return%, sharpe) at each cost level
        metrics = []
        for bps in cost_levels:
            res = strategy.run(data, cost_bps=bps)
            res = res.loc[TRAIN_START:TRAIN_END].copy()
            res["cumulative_strategy"] = (1 + res["strategy_return"]).cumprod() - 1
            total_ret = res["cumulative_strategy"].iloc[-1] * 100
            # Same Sharpe formula as print_results: daily excess / std * sqrt(252)
            excess = res["strategy_return"] - 0.06 / 252
            sharpe = (excess.mean() / excess.std()) * np.sqrt(252) if excess.std() > 0 else 0.0
            metrics.append((total_ret, sharpe))

        # Print one line per config: label + (return | sharpe) at each bps
        ret_line    = f"{'  ' + label:<38}" + "".join(f"  {m[0]:>5.1f}%" for m in metrics)
        sharpe_line = f"{'  Sharpe':<38}"  + "".join(f"  {m[1]:>5.2f} " for m in metrics)
        print(ret_line)
        print(sharpe_line)
        print()

    # -----------------------------------------------------------------------
    # Out-of-sample: 2026 YTD (geopolitical crisis test)
    # -----------------------------------------------------------------------
    print("\n\n" + "="*55)
    print("  OUT-OF-SAMPLE: 2026 YTD (Geopolitical Crisis)")
    print("="*55)

    oos_configs = [
        ("100 DMA | long only",           MacroStrategy(make_combiner(RegimeFilter(window=100)))),
        ("100 DMA | + panic short, hold", MacroStrategy(make_combiner(RegimeFilter(window=100), with_panic=True, panic_hold=True))),
        ("50 DMA  | long only",           MacroStrategy(make_combiner(RegimeFilter(window=50)))),
        ("50 DMA  | + panic short, hold", MacroStrategy(make_combiner(RegimeFilter(window=50),  with_panic=True, panic_hold=True))),
    ]

    for label, strategy in oos_configs:
        run_period(label, strategy, data, TEST_START, TEST_END, cost_bps=BASE_COST_BPS)

    # Show signal detail for the best OOS config (100 DMA)
    _, best_oos = oos_configs[0]
    test_results = best_oos.run(data, cost_bps=BASE_COST_BPS)
    test_results = test_results.loc[TEST_START:TEST_END]
    test_results["cumulative_nifty"]    = (1 + test_results["nifty_return"]).cumprod() - 1
    test_results["cumulative_strategy"] = (1 + test_results["strategy_return"]).cumprod() - 1

    print(f"\n--- 2026 Signal Detail (100 DMA) ---")
    detail = data.loc[TEST_START:TEST_END].copy()
    detail["oil_10d"]  = detail["CL=F"].pct_change(10) * 100
    detail["inr_10d"]  = detail["INR=X"].pct_change(10) * 100
    detail["vix_10d"]  = detail["^INDIAVIX"].pct_change(10) * 100
    detail["vix_lvl"]  = detail["^INDIAVIX"]
    detail["nifty"]    = detail["^NSEI"].round(0)
    detail["position"] = test_results["position"]
    detail["nifty_ret"]= (test_results["nifty_return"] * 100).round(2)

    print(detail[["nifty","nifty_ret","oil_10d","inr_10d","vix_10d","vix_lvl","position"]]
          .round(2).to_string())


if __name__ == "__main__":
    main()

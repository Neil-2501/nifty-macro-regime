"""
make_plots.py — generate publication-quality plots for the README.

Runs the full backtest internally (strategy logic duplicated here so
strategy.py is not modified). Produces:
  images/equity_curve.png
  images/drawdown.png
  images/yearly_returns.png
  results/results_summary.csv

Prints headline metrics to stdout and verifies they match the README.
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import yfinance as yf

# ---------------------------------------------------------------------------
# Strategy classes — exact copy of strategy.py logic, no changes
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

class SignalCombiner:
    def __init__(self, regime_filter=None, reentry_momentum_threshold=0.005):
        self.entry_signals = []; self.exit_signals = []; self.short_signals = []
        self.regime_filter = regime_filter
        self.reentry_momentum_threshold = reentry_momentum_threshold
    def add_entry(self, signal, weight=1.0):
        self.entry_signals.append((signal, weight)); return self
    def add_exit(self, signal):
        self.exit_signals.append(signal); return self
    def add_short(self, signal, hold=True, max_hold_days=60,
                  exit_ma_fast=None, exit_ma_slow=None):
        self.short_signals.append((signal, hold, max_hold_days, exit_ma_fast, exit_ma_slow))
        return self
    def compute_position(self, data):
        if self.entry_signals:
            total_weight = sum(w for _, w in self.entry_signals)
            score = pd.Series(0.0, index=data.index)
            for signal, weight in self.entry_signals:
                score += signal.compute(data) * (weight / total_weight)
            position = pd.Series(0.0, index=data.index)
            position[score > 0] = 1.0
        else:
            position = pd.Series(1.0, index=data.index)
        position = position.replace(0.0, np.nan).ffill().fillna(1.0)
        nifty_mom = data["^NSEI"].ffill().pct_change(5)
        nifty_recovering = nifty_mom > self.reentry_momentum_threshold
        for signal in self.exit_signals:
            firing = signal.compute(data) < 0
            fv = firing.values; rv = nifty_recovering.values
            in_exit = False; ef = [False] * len(data)
            for i in range(len(data)):
                if fv[i]: in_exit = True; ef[i] = True
                elif in_exit:
                    if rv[i]: in_exit = False
                    else: ef[i] = True
            position[pd.Series(ef, index=data.index)] = 0.0
        for signal, hold, max_hold_days, exit_ma_fast, exit_ma_slow in self.short_signals:
            raw = signal.compute(data) < 0
            if hold and max_hold_days > 0:
                held = raw.astype(float).rolling(window=max_hold_days, min_periods=1).max()
                if exit_ma_fast and exit_ma_slow:
                    n = data["^NSEI"].ffill()
                    ma_bullish = n.rolling(exit_ma_fast).mean() > n.rolling(exit_ma_slow).mean()
                    position[(held == 1.0) & ~ma_bullish] = -1.0
                else:
                    position[held == 1.0] = -1.0
            else:
                position[raw] = -1.0
        if self.short_signals:
            is_short = (position == -1.0).values; is_fresh = nifty_recovering.values
            in_cd = False; psf = [False] * len(data)
            for i in range(1, len(data)):
                if is_short[i-1] and not is_short[i]: in_cd = True
                if in_cd and is_fresh[i]: in_cd = False
                if in_cd and not is_fresh[i] and not is_short[i]: psf[i] = True
            position[pd.Series(psf, index=data.index)] = 0.0
        if self.regime_filter:
            bull = self.regime_filter.bull_mask(data)
            position[(position > 0) & ~bull] = 0.0
            position[(position < 0) &  bull] = 0.0
        return position.rename("position")

class MacroStrategy:
    def __init__(self, combiner, target="^NSEI"):
        self.combiner = combiner; self.target = target
    def run(self, data, cost_bps=0):
        nifty_returns = data[self.target].pct_change().rename("nifty_return")
        position = self.combiner.compute_position(data)
        trade_cost = position.diff().abs() * (cost_bps / 10000)
        strategy_returns = (position.shift(1) * nifty_returns - trade_cost).rename("strategy_return")
        return pd.DataFrame({
            "nifty_return": nifty_returns,
            "position": position,
            "strategy_return": strategy_returns,
            "cumulative_nifty": (1 + nifty_returns).cumprod() - 1,
            "cumulative_strategy": (1 + strategy_returns).cumprod() - 1,
        })

# ---------------------------------------------------------------------------
# run_backtest() — the clean interface make_plots uses
# ---------------------------------------------------------------------------

RF = 0.06  # India risk-free rate

def run_backtest(cost_bps: float = 3) -> dict:
    """
    Downloads data, runs best config (100 DMA | panic short, no hold),
    returns all series needed for plots and metrics.
    """
    WARMUP   = "2006-01-01"
    START    = "2008-04-01"
    END      = "2025-12-31"
    TICKERS  = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX"]

    print("Downloading data ...", file=sys.stderr)
    raw = yf.download(TICKERS, start=WARMUP, end="2026-01-01",
                      auto_adjust=True, progress=False)["Close"]
    raw.dropna(how="all", inplace=True)
    raw = raw.ffill()

    rf = RegimeFilter(window=100)
    c = SignalCombiner(regime_filter=rf)
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    c.add_exit(SupplyShockSignal(window=10, oil_threshold=0.03,
                                 inr_threshold=0.01, vix_threshold=0.20))
    c.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)
    strategy = MacroStrategy(c)

    res = strategy.run(raw, cost_bps=cost_bps).loc[START:END].copy()
    res["cumulative_strategy"] = (1 + res["strategy_return"]).cumprod() - 1
    res["cumulative_nifty"]    = (1 + res["nifty_return"]).cumprod() - 1

    # Cumulative series starting at 1.0 (for log-scale equity curve)
    strat_cum = (1 + res["strategy_return"]).cumprod()
    nifty_cum = (1 + res["nifty_return"]).cumprod()

    # Drawdown series (as fractions, negative)
    strat_dd = (strat_cum - strat_cum.cummax()) / strat_cum.cummax()
    nifty_dd = (nifty_cum - nifty_cum.cummax()) / nifty_cum.cummax()

    # Year-by-year
    annual_s = (1 + res["strategy_return"]).resample("YE").prod() - 1
    annual_n = (1 + res["nifty_return"]).resample("YE").prod() - 1
    yearly = pd.DataFrame({
        "year":         [d.year for d in annual_s.index],
        "strategy_ret": annual_s.values * 100,
        "nifty_ret":    annual_n.values * 100,
    })

    return {
        "dates":        res.index,
        "strategy_cum": strat_cum,
        "nifty_cum":    nifty_cum,
        "strategy_dd":  strat_dd,
        "nifty_dd":     nifty_dd,
        "yearly":       yearly,
        "res":          res,         # full results for metrics
    }

# ---------------------------------------------------------------------------
# Metrics helper
# ---------------------------------------------------------------------------

def compute_metrics(res):
    r = res["strategy_return"]
    n = res["nifty_return"]

    def _metrics(ret):
        cum = (1 + ret).cumprod()
        n_years = len(ret) / 252
        total = cum.iloc[-1] - 1
        cagr = (1 + total) ** (1 / n_years) - 1
        vol = ret.std() * np.sqrt(252)
        excess = ret - RF / 252
        sharpe = (excess.mean() / excess.std()) * np.sqrt(252)
        downside = ret[ret < 0].std() * np.sqrt(252)
        sortino = (cagr - RF) / downside if downside > 0 else np.nan
        dd = ((cum - cum.cummax()) / cum.cummax()).min()
        calmar = cagr / abs(dd) if dd != 0 else np.nan
        return dict(total=total, cagr=cagr, vol=vol,
                    sharpe=sharpe, sortino=sortino, max_dd=dd, calmar=calmar)

    return _metrics(r), _metrics(n)

# ---------------------------------------------------------------------------
# Plot styling constants
# ---------------------------------------------------------------------------

BLUE  = "#1f3b73"
GRAY  = "#7a7a7a"
SPINE_COLOR = "#cccccc"

def _base_ax(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(SPINE_COLOR)
    ax.spines["bottom"].set_color(SPINE_COLOR)
    ax.tick_params(colors="#444444")
    ax.yaxis.label.set_color("#444444")
    ax.xaxis.label.set_color("#444444")
    ax.title.set_color("#222222")
    ax.grid(axis="y", color="#e8e8e8", linewidth=0.8, zorder=0)
    ax.grid(axis="x", visible=False)
    return ax

# ---------------------------------------------------------------------------
# Plot 1 — Equity curve
# ---------------------------------------------------------------------------

def plot_equity_curve(bt, out_path):
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    ax.plot(bt["dates"], bt["strategy_cum"],
            color=BLUE, linewidth=1.5, label="Strategy (net 3 bps)", zorder=3)
    ax.plot(bt["dates"], bt["nifty_cum"],
            color=GRAY, linewidth=1.5, label="NIFTY 50 Buy & Hold", zorder=2)
    ax.set_yscale("log")
    # Explicit ticks at each whole multiple so the axis is readable on log scale
    ax.set_yticks([1, 2, 3, 4, 5, 6])
    ax.set_yticklabels(["1.0x", "2.0x", "3.0x", "4.0x", "5.0x", "6.0x"])
    ax.minorticks_off()
    ax.set_ylim(0.6, 6.5)
    # Gridlines at major ticks, behind data
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, which="major", linestyle="-", linewidth=0.5, alpha=0.3)
    ax.xaxis.grid(False)
    ax.set_ylabel("Cumulative return (x)")
    ax.set_title("Cumulative Returns — Strategy (net of 3 bps) vs NIFTY 50 (2008-2025)",
                 fontsize=11, pad=10)
    ax.legend(loc="lower right", framealpha=0.9, fontsize=9)
    _base_ax(ax)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, transparent=False, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out_path}")

# ---------------------------------------------------------------------------
# Plot 2 — Drawdown
# ---------------------------------------------------------------------------

def plot_drawdown(bt, out_path):
    dates = bt["dates"]
    sdd   = bt["strategy_dd"] * 100   # convert to percent
    ndd   = bt["nifty_dd"]   * 100

    s_max = sdd.min()
    n_max = ndd.min()
    s_max_date = sdd.idxmin()
    n_max_date = ndd.idxmin()

    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)

    ax.fill_between(dates, sdd, 0, color=BLUE, alpha=0.35, zorder=2)
    ax.plot(dates, sdd, color=BLUE, linewidth=1.2,
            label="Strategy (net 3 bps)", zorder=3)

    ax.fill_between(dates, ndd, 0, color=GRAY, alpha=0.25, zorder=1)
    ax.plot(dates, ndd, color=GRAY, linewidth=1.2,
            label="NIFTY 50 Buy & Hold", zorder=2)

    # Annotate max drawdown points
    ax.annotate(f"{s_max:.1f}%",
                xy=(s_max_date, s_max),
                xytext=(10, -12), textcoords="offset points",
                fontsize=8, color=BLUE,
                arrowprops=dict(arrowstyle="-", color=BLUE, lw=0.8))
    ax.annotate(f"{n_max:.1f}%",
                xy=(n_max_date, n_max),
                xytext=(10, -12), textcoords="offset points",
                fontsize=8, color=GRAY,
                arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.8))

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax.set_ylabel("Drawdown")
    ax.set_title("Drawdown — Strategy vs NIFTY 50 (2008-2025)", fontsize=11, pad=10)
    ax.legend(loc="lower right", framealpha=0.9, fontsize=9)
    _base_ax(ax)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, transparent=False, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out_path}")

# ---------------------------------------------------------------------------
# Plot 3 — Yearly returns bar chart
# ---------------------------------------------------------------------------

def plot_yearly_returns(bt, out_path):
    df   = bt["yearly"]
    years = df["year"].values
    s_ret = df["strategy_ret"].values
    n_ret = df["nifty_ret"].values

    x     = np.arange(len(years))
    width = 0.38

    # Cosmetic only: give near-zero bars a minimum visible nub of 0.3pp so they
    # don't vanish entirely. Underlying data values are unchanged everywhere else.
    MIN_VIS = 0.3
    s_plot = np.where(np.abs(s_ret) < MIN_VIS, np.sign(s_ret + 1e-9) * MIN_VIS, s_ret)
    n_plot = np.where(np.abs(n_ret) < MIN_VIS, np.sign(n_ret + 1e-9) * MIN_VIS, n_ret)

    fig, ax = plt.subplots(figsize=(11, 5), dpi=150)
    ax.bar(x - width / 2, s_plot, width, label="Strategy (net 3 bps)",
           color=BLUE, zorder=3)
    ax.bar(x + width / 2, n_plot, width, label="NIFTY 50 Buy & Hold",
           color=GRAY, zorder=3)

    ax.axhline(0, color="#999999", linewidth=0.8, zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(years, rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_ylabel("Annual return (%)")
    ax.set_title("Annual Returns — Strategy vs NIFTY 50", fontsize=11, pad=10)
    ax.legend(loc="upper right", framealpha=0.9, fontsize=9)
    _base_ax(ax)
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, transparent=False, facecolor="white")
    plt.close(fig)
    print(f"  Saved {out_path}")

# ---------------------------------------------------------------------------
# Write results_summary.csv
# ---------------------------------------------------------------------------

def write_summary_csv(sm, nm, csv_path):
    rows = [
        ("cumulative_return_pct",   round(sm["total"] * 100, 1),  round(nm["total"] * 100, 1)),
        ("cagr_pct",                round(sm["cagr"]  * 100, 2),  round(nm["cagr"]  * 100, 2)),
        ("sharpe",                  round(sm["sharpe"],       2),  round(nm["sharpe"],       2)),
        ("sortino",                 round(sm["sortino"],      2),  round(nm["sortino"],      2)),
        ("max_drawdown_pct",        round(sm["max_dd"] * 100, 1),  round(nm["max_dd"] * 100, 1)),
        ("calmar",                  round(sm["calmar"],       2),  round(nm["calmar"],       2)),
        ("ann_vol_pct",             round(sm["vol"]    * 100, 2),  round(nm["vol"]    * 100, 2)),
    ]
    df = pd.DataFrame(rows, columns=["metric", "strategy_net_3bps", "nifty_buy_hold"])
    df.to_csv(csv_path, index=False)
    print(f"  Saved {csv_path}")
    return df

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    os.makedirs("images",  exist_ok=True)
    os.makedirs("results", exist_ok=True)

    bt = run_backtest(cost_bps=3)
    sm, nm = compute_metrics(bt["res"])

    print("\n--- Headline metrics (strategy net of 3 bps) ---")
    print(f"  Cumulative return : {sm['total']*100:.1f}%  (README: 467.2%)")
    print(f"  CAGR              : {sm['cagr']*100:.2f}%  (README: 9.91%)")
    print(f"  Sharpe            : {sm['sharpe']:.2f}     (README: 0.33)")
    print(f"  Sortino           : {sm['sortino']:.2f}     (README: 0.36)")
    print(f"  Max drawdown      : {sm['max_dd']*100:.1f}%  (README: -22.2%)")
    print(f"  Calmar            : {sm['calmar']:.2f}     (README: 0.45)")
    print(f"  Ann. volatility   : {sm['vol']*100:.2f}%  (README: 13.26%)")

    # Deviation check — warn if anything is materially off
    checks = [
        ("Cumulative return", sm["total"]*100, 467.2, 2.0),
        ("CAGR",              sm["cagr"]*100,   9.91, 0.05),
        ("Sharpe",            sm["sharpe"],      0.33, 0.02),
        ("Max drawdown",      sm["max_dd"]*100, -22.2, 0.5),
    ]
    ok = True
    for label, got, expected, tol in checks:
        if abs(got - expected) > tol:
            print(f"  WARNING: {label} = {got:.2f}, expected ~{expected} (diff > {tol})")
            ok = False
    if ok:
        print("  All metrics within tolerance of README values.")

    print("\nGenerating plots ...")
    plot_equity_curve(bt, "images/equity_curve.png")
    plot_drawdown(bt,     "images/drawdown.png")
    plot_yearly_returns(bt, "images/yearly_returns.png")

    print("\nWriting results/results_summary.csv ...")
    df_csv = write_summary_csv(sm, nm, "results/results_summary.csv")
    print(df_csv.to_string(index=False))

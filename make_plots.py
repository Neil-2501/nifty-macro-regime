"""
make_plots.py — generate publication-quality plots for the README.

Runs the production v2.1 Config 7 strategy: NIFTY 200 Momentum 30 long-side +
post-bear NIFTY recovery overlay + slow-stress cooldown + panic-short drawdown
confirmation + momentum-gated gold rotation with macro confirmation. Imports
from strategy.py rather than duplicating logic.

Produces:
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

# Import the strategy classes from the canonical strategy.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import (
    SupplyShockSignal, PanicShortSignal, USDINRSignal, IndiaVIXSignal,
    RegimeFilter, SignalCombiner, MacroStrategy, make_combiner,
    metrics, position_breakdown, build_rbi_repo_rate_series,
    load_nse_index_csv,
)


# ---------------------------------------------------------------------------
# run_backtest() — runs Config 7 production (v2.1)
# ---------------------------------------------------------------------------

def run_backtest(nifty_cost_bps: float = 3, gold_cost_bps: float = 5,
                 use_cash_yield: bool = True,
                 cash_yield_haircut_bps: float = 100) -> dict:
    """
    Downloads data, runs Config 7 (v2.1: Mom30 long-side with post-bear NIFTY
    recovery overlay + slow-stress cooldown + panic-short drawdown confirmation
    + momentum-gated gold rotation with macro confirmation + repo-haircut cash),
    returns all series needed for plots.
    """
    WARMUP   = "2006-01-01"
    START    = "2008-04-01"
    END      = "2025-12-31"
    # v1.4 added ^TNX (US 10Y) for macro-confirmed gold rotation gate
    TICKERS  = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS", "^TNX"]

    print("Downloading data ...", file=sys.stderr)
    raw = yf.download(TICKERS, start=WARMUP, end="2026-01-01",
                      auto_adjust=True, progress=False)["Close"]
    raw.dropna(how="all", inplace=True)
    for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
        if col in raw.columns:
            raw[col] = raw[col].ffill()
    if "GOLDBEES.NS" in raw.columns:
        first_valid = raw["GOLDBEES.NS"].first_valid_index()
        if first_valid is not None:
            mask = raw.index >= first_valid
            raw.loc[mask, "GOLDBEES.NS"] = raw.loc[mask, "GOLDBEES.NS"].ffill()

    # v1.3: Load NIFTY 200 Momentum 30 from NSE CSV (long-side asset)
    mom30 = load_nse_index_csv("data/momentum30_history.csv", "NIFTYMOM30")
    raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()

    # Config 7 (v2.1 production):
    #   Mom30 long-side with post-bear NIFTY recovery overlay (60d, 15% bear DD)
    #   Slow-stress with 5-day cooldown
    #   Panic-short with 15% drawdown confirmation
    #   Momentum-gated gold rotation with macro confirmation (v1.5 bear-req)
    combiner = make_combiner(rotate_stress=True, rotate_panic=False,
                             use_momentum_gold=True,
                             slow_stress_lock_days=5,
                             panic_short_dd_threshold=0.15)
    strategy = MacroStrategy(
        combiner,
        nifty_cost_bps=nifty_cost_bps,
        gold_cost_bps=gold_cost_bps,
        use_cash_yield=use_cash_yield,
        cash_yield_haircut_bps=cash_yield_haircut_bps,
        long_target="NIFTYMOM30",
        long_cost_bps=6,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
    )

    res = strategy.run(raw).loc[START:END].copy()
    res["cumulative_strategy"] = (1 + res["strategy_return"]).cumprod() - 1
    res["cumulative_nifty"]    = (1 + res["nifty_return"]).cumprod() - 1

    strat_cum = (1 + res["strategy_return"]).cumprod()
    nifty_cum = (1 + res["nifty_return"]).cumprod()

    strat_dd = (strat_cum - strat_cum.cummax()) / strat_cum.cummax()
    nifty_dd = (nifty_cum - nifty_cum.cummax()) / nifty_cum.cummax()

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
        "res":          res,
    }


def compute_full_metrics(res):
    return metrics(res["strategy_return"]), metrics(res["nifty_return"])


# ---------------------------------------------------------------------------
# Plot styling
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
# Plot 1 — Equity curve (log-scale)
# ---------------------------------------------------------------------------

def plot_equity_curve(bt, out_path):
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    ax.plot(bt["dates"], bt["strategy_cum"],
            color=BLUE, linewidth=1.5, label="Strategy v2.1 (Mom30 long, 3/5/6 bps + repo-100bps)", zorder=3)
    ax.plot(bt["dates"], bt["nifty_cum"],
            color=GRAY, linewidth=1.5, label="NIFTY 50 Buy & Hold", zorder=2)
    ax.set_yscale("log")
    # v2.1: strategy ends ~17x post-tax (~28x pre-tax), NIFTY ~5.5x
    ax.set_yticks([0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30])
    ax.set_yticklabels(["0.5x", "1.0x", "2.0x", "3.0x", "5.0x", "7.0x", "10.0x", "15.0x", "20.0x", "30.0x"])
    ax.minorticks_off()
    ax.set_ylim(0.5, 30)
    ax.set_axisbelow(True)
    ax.yaxis.grid(True, which="major", linestyle="-", linewidth=0.5, alpha=0.3)
    ax.xaxis.grid(False)
    ax.set_ylabel("Cumulative return (x)")
    ax.set_title("Cumulative Returns — Strategy v2.1 (Mom30 long + recovery overlay + slow-stress cooldown + drawdown-gated panic-short) vs NIFTY 50 (2008-2025)",
                 fontsize=10, pad=10)
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
    sdd   = bt["strategy_dd"] * 100
    ndd   = bt["nifty_dd"]   * 100

    s_max = sdd.min()
    n_max = ndd.min()
    s_max_date = sdd.idxmin()
    n_max_date = ndd.idxmin()

    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)

    ax.fill_between(dates, sdd, 0, color=BLUE, alpha=0.35, zorder=2)
    ax.plot(dates, sdd, color=BLUE, linewidth=1.2,
            label="Strategy v2.1", zorder=3)

    ax.fill_between(dates, ndd, 0, color=GRAY, alpha=0.25, zorder=1)
    ax.plot(dates, ndd, color=GRAY, linewidth=1.2,
            label="NIFTY 50 Buy & Hold", zorder=2)

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
    ax.set_title("Drawdown — Strategy v2.1 vs NIFTY 50 (2008-2025)", fontsize=11, pad=10)
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
    df    = bt["yearly"]
    years = df["year"].values
    s_ret = df["strategy_ret"].values
    n_ret = df["nifty_ret"].values

    x     = np.arange(len(years))
    width = 0.38

    # Cosmetic only: minimum visible bar height of 0.3pp so near-zero bars are
    # visible. Underlying data values are unchanged.
    MIN_VIS = 0.3
    s_plot = np.where(np.abs(s_ret) < MIN_VIS, np.sign(s_ret + 1e-9) * MIN_VIS, s_ret)
    n_plot = np.where(np.abs(n_ret) < MIN_VIS, np.sign(n_ret + 1e-9) * MIN_VIS, n_ret)

    fig, ax = plt.subplots(figsize=(11, 5), dpi=150)
    ax.bar(x - width / 2, s_plot, width, label="Strategy v2.1",
           color=BLUE, zorder=3)
    ax.bar(x + width / 2, n_plot, width, label="NIFTY 50 Buy & Hold",
           color=GRAY, zorder=3)

    ax.axhline(0, color="#999999", linewidth=0.8, zorder=1)
    ax.set_xticks(x)
    ax.set_xticklabels(years, rotation=45, ha="right", fontsize=8)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_ylabel("Annual return (%)")
    ax.set_title("Annual Returns — Strategy v2.1 vs NIFTY 50", fontsize=11, pad=10)
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
    df = pd.DataFrame(rows, columns=["metric", "strategy_v21", "nifty_buy_hold"])
    df.to_csv(csv_path, index=False)
    print(f"  Saved {csv_path}")
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    os.makedirs("images",  exist_ok=True)
    os.makedirs("results", exist_ok=True)

    bt = run_backtest(nifty_cost_bps=3, gold_cost_bps=5, use_cash_yield=True)
    sm, nm = compute_full_metrics(bt["res"])
    bd = position_breakdown(bt["res"])

    print("\n--- Headline metrics (v2.1 Config 7: Mom30 + recovery overlay + slow-stress cooldown + drawdown-gated panic-short, post-tax) ---")
    print(f"  Cumulative return : {sm['total']*100:.1f}%  (expected ~1624%)")
    print(f"  CAGR              : {sm['cagr']*100:.2f}%  (expected ~16.75%)")
    print(f"  Sharpe            : {sm['sharpe']:.2f}    (expected ~0.84)")
    print(f"  Sortino           : {sm['sortino']:.2f}    (expected ~1.01)")
    print(f"  Calmar            : {sm['calmar']:.2f}    (expected ~1.31)")
    print(f"  Max drawdown      : {sm['max_dd']*100:.1f}%  (expected ~-12.8%)")
    print(f"  Ann. volatility   : {sm['vol']*100:.2f}%  (expected ~12.16%)")

    print(f"\n  Position breakdown: long_nifty={bd['long_nifty']}  "
          f"short_nifty={bd['short_nifty']}  long_gold={bd['long_gold']}  "
          f"flat={bd['flat']}  total={bd['total']}")

    # Tolerance check — v2.1 expected values (post-tax)
    checks = [
        ("Cumulative return", sm["total"]*100, 1624.0, 5.0),
        ("CAGR",              sm["cagr"]*100,   16.75, 0.05),
        ("Sharpe",            sm["sharpe"],      0.84, 0.02),
        ("Max drawdown",      sm["max_dd"]*100, -12.78, 0.2),
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

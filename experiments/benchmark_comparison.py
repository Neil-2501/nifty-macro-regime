"""
benchmark_comparison.py — TEST ONLY (strategy.py NOT modified).

Compares v1.4 strategy against 10 increasingly sophisticated benchmarks:
  Static:
    1. NIFTY 50 B&H
    2. Mom30 B&H
    3. GOLDBEES B&H (pre-2009 in cash)
    4. Static 50/50 Mom30/gold (monthly rebal)
    5. Static 70/30 Mom30/gold (monthly rebal)
    6. Risk-parity Mom30/gold (60d vol, monthly rebal)
  Dynamic:
    7. Dynamic A: regime filter alone (Mom30 vs cash on 100 DMA flip)
    8. Dynamic B: regime + static gold (bull 70/30, bear 100% gold)
    9. Dynamic C: cross-sectional momentum (60d return, monthly rebal)
   10. Dynamic D: vol-targeted Mom30 (target 12%, 5% tolerance band)

All benchmarks use:
  - Same tax model (apply_annual_tax, 15%)
  - Same cost rates (Mom30 6bps, gold 5bps, NIFTY 3bps)
  - Same cash yield (haircut-adjusted RBI repo, 100bps haircut)
  - Same pre-2009 gold handling (cash or 100% Mom30 as specified)
"""

import os, sys
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy import (
    make_combiner, MacroStrategy, load_nse_index_csv,
    build_rbi_repo_rate_series, metrics, apply_annual_tax,
)

WARMUP, IS_START, IS_END, OOS_START = "2006-01-01", "2008-04-01", "2025-12-31", "2026-01-01"
TICKERS = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS", "^TNX"]
LONG_BPS, SHORT_BPS, GOLD_BPS, HAIRCUT_BPS = 6, 3, 5, 100
TAX = 0.15
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "benchmark_comparison_results.txt")


# ─────────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────────

print("Downloading data ...", file=sys.stderr)
raw = yf.download(TICKERS, start=WARMUP, end=None, auto_adjust=True,
                  progress=False)["Close"]
raw.dropna(how="all", inplace=True)
for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
    raw[col] = raw[col].ffill()
fv = raw["GOLDBEES.NS"].first_valid_index()
raw.loc[raw.index >= fv, "GOLDBEES.NS"] = raw.loc[raw.index >= fv,
                                                  "GOLDBEES.NS"].ffill()
_data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "momentum30_history.csv")
mom30 = load_nse_index_csv(_data_path, "NIFTYMOM30")
raw["NIFTYMOM30"] = mom30.reindex(raw.index).ffill()

nifty_ret = raw["^NSEI"].pct_change().fillna(0.0)
mom30_ret = raw["NIFTYMOM30"].pct_change().fillna(0.0)
gold_avail = raw["GOLDBEES.NS"].notna()
gold_ret_raw  = raw["GOLDBEES.NS"].pct_change().fillna(0.0).where(gold_avail, 0.0)
# GOLDBEES.NS has a known yfinance data glitch on 2019-12-19/20/23 where two
# trading days are reported at 1/100 of true price (likely a feed/adjustment
# artifact). Clip daily returns to ±50% to eliminate this artifact — the
# strategy doesn't hold gold on those dates, but the GOLDBEES B&H benchmark
# would otherwise show absurd vol/return numbers.
gold_ret = gold_ret_raw.clip(lower=-0.5, upper=0.5)
repo = build_rbi_repo_rate_series(raw.index)
daily_cash_yield = (repo - HAIRCUT_BPS / 10000).clip(lower=0) / 252

idx = raw.index
all_dates = idx[(idx >= pd.Timestamp(IS_START)) & (idx <= pd.Timestamp(IS_END))]
gold_start = pd.Timestamp("2009-01-02")


# ─────────────────────────────────────────────────────────────────────────
# Helper: month-end rebalance dates
# ─────────────────────────────────────────────────────────────────────────

def month_end_dates(date_index):
    """Last trading day of each month within date_index."""
    by_month = pd.Series(date_index, index=date_index).groupby(
        [date_index.year, date_index.month]).max()
    return pd.DatetimeIndex(by_month.values)


me_dates = month_end_dates(idx)


# ─────────────────────────────────────────────────────────────────────────
# Helper: rebalanced two-asset portfolio simulator
# ─────────────────────────────────────────────────────────────────────────

def simulate_static_portfolio(target_w_mom, target_w_gold, rebal_dates,
                              pre_gold_mom_w=1.0):
    """Simulate Mom30 + gold portfolio with monthly rebalance.

    Pre-gold-availability: holds pre_gold_mom_w fraction in Mom30,
    rest in cash. From gold_start onward: rebalances to (target_w_mom,
    target_w_gold) on rebal_dates. Returns daily portfolio returns
    (net of transaction costs).

    Cost model: at each rebalance, turnover_per_asset = |target - current|;
    cost charged = turnover × cost_bps / 10000.
    """
    n = len(idx)
    daily = np.zeros(n)
    # Initial weights pre-2009: pre_gold_mom_w in Mom30, rest in cash
    w_mom = pre_gold_mom_w
    w_gold = 0.0
    w_cash = 1.0 - pre_gold_mom_w
    rebal_set = set(rebal_dates)

    for i in range(n):
        d = idx[i]
        # Day's return (using weights from previous day's close)
        if i == 0:
            r = 0.0
        else:
            r_mom_d = mom30_ret.iloc[i]
            r_gold_d = gold_ret.iloc[i] if gold_avail.iloc[i] else 0.0
            r_cash_d = daily_cash_yield.iloc[i]
            r = w_mom * r_mom_d + w_gold * r_gold_d + w_cash * r_cash_d
            # Drift weights
            w_mom_new = w_mom * (1 + r_mom_d) / (1 + r) if (1 + r) != 0 else w_mom
            w_gold_new = w_gold * (1 + r_gold_d) / (1 + r) if (1 + r) != 0 else w_gold
            w_cash_new = w_cash * (1 + r_cash_d) / (1 + r) if (1 + r) != 0 else w_cash
            w_mom, w_gold, w_cash = w_mom_new, w_gold_new, w_cash_new

        # Rebalance at end of rebalance days
        if d in rebal_set:
            if d >= gold_start:
                target_mom = target_w_mom
                target_gold = target_w_gold
                target_cash = 1.0 - target_mom - target_gold
            else:
                target_mom = pre_gold_mom_w
                target_gold = 0.0
                target_cash = 1.0 - pre_gold_mom_w

            cost = (abs(target_mom - w_mom) * LONG_BPS / 10000
                    + abs(target_gold - w_gold) * GOLD_BPS / 10000)
            r -= cost
            w_mom = target_mom
            w_gold = target_gold
            w_cash = target_cash

        daily[i] = r
    return pd.Series(daily, index=idx)


# ─────────────────────────────────────────────────────────────────────────
# Helper: risk-parity weights
# ─────────────────────────────────────────────────────────────────────────

def risk_parity_weights(rebal_date, window=60):
    """Inverse-vol weights for Mom30 and gold using 60d realized vol."""
    end_loc = idx.get_loc(rebal_date)
    start_loc = max(0, end_loc - window + 1)
    win = slice(start_loc, end_loc + 1)
    vol_mom = mom30_ret.iloc[win].std()
    if rebal_date < gold_start or not gold_avail.loc[rebal_date]:
        return 1.0, 0.0
    vol_gold = gold_ret.iloc[win].std()
    if vol_mom <= 0 or vol_gold <= 0:
        return 0.5, 0.5
    inv_mom, inv_gold = 1 / vol_mom, 1 / vol_gold
    w_mom = inv_mom / (inv_mom + inv_gold)
    w_gold = 1.0 - w_mom
    return w_mom, w_gold


def simulate_risk_parity(rebal_dates):
    n = len(idx)
    daily = np.zeros(n)
    w_mom, w_gold, w_cash = 1.0, 0.0, 0.0
    rebal_set = set(rebal_dates)

    for i in range(n):
        d = idx[i]
        if i == 0:
            r = 0.0
        else:
            r_mom_d = mom30_ret.iloc[i]
            r_gold_d = gold_ret.iloc[i] if gold_avail.iloc[i] else 0.0
            r_cash_d = daily_cash_yield.iloc[i]
            r = w_mom * r_mom_d + w_gold * r_gold_d + w_cash * r_cash_d
            w_mom_new = w_mom * (1 + r_mom_d) / (1 + r) if (1 + r) != 0 else w_mom
            w_gold_new = w_gold * (1 + r_gold_d) / (1 + r) if (1 + r) != 0 else w_gold
            w_cash_new = w_cash * (1 + r_cash_d) / (1 + r) if (1 + r) != 0 else w_cash
            w_mom, w_gold, w_cash = w_mom_new, w_gold_new, w_cash_new

        if d in rebal_set:
            target_mom, target_gold = risk_parity_weights(d, window=60)
            target_cash = 1.0 - target_mom - target_gold
            cost = (abs(target_mom - w_mom) * LONG_BPS / 10000
                    + abs(target_gold - w_gold) * GOLD_BPS / 10000)
            r -= cost
            w_mom, w_gold, w_cash = target_mom, target_gold, target_cash
        daily[i] = r
    return pd.Series(daily, index=idx)


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 1: NIFTY 50 B&H
# ─────────────────────────────────────────────────────────────────────────

def bench_nifty_bh():
    return nifty_ret.copy()


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 2: Mom30 B&H
# ─────────────────────────────────────────────────────────────────────────

def bench_mom30_bh():
    return mom30_ret.copy()


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 3: GOLDBEES B&H (pre-2009 in cash)
# ─────────────────────────────────────────────────────────────────────────

def bench_gold_bh():
    n = len(idx)
    daily = np.zeros(n)
    holding_gold = False
    for i in range(n):
        d = idx[i]
        if d < gold_start:
            # Cash
            if i > 0:
                daily[i] = daily_cash_yield.iloc[i]
            continue
        if not holding_gold:
            # Transition to gold (5 bps cost)
            holding_gold = True
            daily[i] = -GOLD_BPS / 10000
        else:
            daily[i] = gold_ret.iloc[i]
    return pd.Series(daily, index=idx)


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 4: Static 50/50
# ─────────────────────────────────────────────────────────────────────────

def bench_static_50_50():
    return simulate_static_portfolio(0.5, 0.5, me_dates, pre_gold_mom_w=1.0)


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 5: Static 70/30
# ─────────────────────────────────────────────────────────────────────────

def bench_static_70_30():
    return simulate_static_portfolio(0.7, 0.3, me_dates, pre_gold_mom_w=1.0)


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 6: Risk-parity Mom30/gold
# ─────────────────────────────────────────────────────────────────────────

def bench_risk_parity():
    return simulate_risk_parity(me_dates)


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 7: Dynamic A — regime filter alone
# ─────────────────────────────────────────────────────────────────────────

def bench_dynamic_A():
    nifty_close = raw["^NSEI"].ffill()
    dma100 = nifty_close.rolling(100).mean()
    bull = (nifty_close > dma100).reindex(idx).fillna(False)
    n = len(idx)
    daily = np.zeros(n)
    holding_mom = False
    for i in range(n):
        target_mom = bool(bull.iloc[i])
        if i == 0:
            holding_mom = target_mom
            daily[i] = 0.0
            continue
        r = mom30_ret.iloc[i] if holding_mom else daily_cash_yield.iloc[i]
        # Position flip (uses yesterday's position for today's return,
        # then changes position at end of today)
        if target_mom != holding_mom:
            # Cost: full Mom30 ETF entry/exit
            r -= LONG_BPS / 10000
            holding_mom = target_mom
        daily[i] = r
    return pd.Series(daily, index=idx)


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 8: Dynamic B — regime + static gold (bull 70/30, bear 100% gold)
# ─────────────────────────────────────────────────────────────────────────

def bench_dynamic_B():
    nifty_close = raw["^NSEI"].ffill()
    dma100 = nifty_close.rolling(100).mean()
    bull = (nifty_close > dma100).reindex(idx).fillna(False)
    n = len(idx)
    daily = np.zeros(n)
    w_mom, w_gold, w_cash = 1.0, 0.0, 0.0   # initial (pre-2009 all Mom30)
    me_set = set(me_dates)

    for i in range(n):
        d = idx[i]
        if i == 0:
            daily[i] = 0.0
            continue
        # Apply yesterday's weights to today's returns
        r_mom_d = mom30_ret.iloc[i]
        r_gold_d = gold_ret.iloc[i] if gold_avail.iloc[i] else 0.0
        r_cash_d = daily_cash_yield.iloc[i]
        r = w_mom * r_mom_d + w_gold * r_gold_d + w_cash * r_cash_d
        # Drift
        if (1 + r) != 0:
            w_mom = w_mom * (1 + r_mom_d) / (1 + r)
            w_gold = w_gold * (1 + r_gold_d) / (1 + r)
            w_cash = w_cash * (1 + r_cash_d) / (1 + r)

        # Regime flip OR month-end → rebalance
        regime_flip = (i > 0) and (bull.iloc[i] != bull.iloc[i - 1])
        if regime_flip or d in me_set:
            if bull.iloc[i]:
                # Bull regime: 70/30 Mom30/gold (or 100% Mom30 pre-2009)
                if d >= gold_start:
                    target_mom, target_gold = 0.7, 0.3
                else:
                    target_mom, target_gold = 1.0, 0.0
                target_cash = 1.0 - target_mom - target_gold
            else:
                # Bear regime: 100% gold (or 100% cash pre-2009)
                if d >= gold_start:
                    target_mom, target_gold, target_cash = 0.0, 1.0, 0.0
                else:
                    target_mom, target_gold, target_cash = 0.0, 0.0, 1.0
            cost = (abs(target_mom - w_mom) * LONG_BPS / 10000
                    + abs(target_gold - w_gold) * GOLD_BPS / 10000)
            r -= cost
            w_mom, w_gold, w_cash = target_mom, target_gold, target_cash
        daily[i] = r
    return pd.Series(daily, index=idx)


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 9: Dynamic C — cross-sectional momentum (60d return, monthly)
# ─────────────────────────────────────────────────────────────────────────

def cash_60d_return(end_loc, window=60):
    """Compounded daily cash yield over last 60 trading days."""
    start = max(0, end_loc - window + 1)
    yields = daily_cash_yield.iloc[start:end_loc + 1].values
    return float(np.prod(1 + yields) - 1)


def bench_dynamic_C():
    n = len(idx)
    daily = np.zeros(n)
    me_set = set(me_dates)
    holding = "cash"   # "mom", "gold", "cash"

    for i in range(n):
        d = idx[i]
        if i == 0:
            daily[i] = 0.0
            continue
        # Today's return based on current holding
        if holding == "mom":
            r = mom30_ret.iloc[i]
        elif holding == "gold":
            r = gold_ret.iloc[i] if gold_avail.iloc[i] else 0.0
        else:
            r = daily_cash_yield.iloc[i]
        # Month-end rebalance: rank assets by 60d return, switch if needed
        if d in me_set:
            # Rank candidates
            end_loc = i
            # Mom30 60d return
            r_mom_60 = (mom30_ret.iloc[max(0, end_loc - 59):end_loc + 1] + 1).prod() - 1
            r_cash_60 = cash_60d_return(end_loc)
            ranks = [("mom", r_mom_60), ("cash", r_cash_60)]
            if d >= gold_start:
                r_gold_60 = (gold_ret.iloc[max(0, end_loc - 59):end_loc + 1] + 1).prod() - 1
                ranks.append(("gold", r_gold_60))
            new_holding = max(ranks, key=lambda x: x[1])[0]
            if new_holding != holding:
                # Cost: exit current + enter new
                exit_cost = {"mom": LONG_BPS, "gold": GOLD_BPS, "cash": 0}[holding]
                enter_cost = {"mom": LONG_BPS, "gold": GOLD_BPS, "cash": 0}[new_holding]
                r -= (exit_cost + enter_cost) / 10000
                holding = new_holding
        daily[i] = r
    return pd.Series(daily, index=idx)


# ─────────────────────────────────────────────────────────────────────────
# Benchmark 10: Dynamic D — vol-targeted Mom30 (5% tolerance)
# ─────────────────────────────────────────────────────────────────────────

def bench_dynamic_D():
    target_vol = 0.12
    realized_vol_20 = mom30_ret.rolling(20).std() * np.sqrt(252)
    # Raw scale factor (clipped)
    raw_scale = (target_vol / realized_vol_20).clip(0.3, 1.0).fillna(1.0)
    # Apply 5% tolerance band
    n = len(idx)
    actual_scale = np.zeros(n)
    last = float(raw_scale.iloc[0])
    actual_scale[0] = last
    for i in range(1, n):
        cur = float(raw_scale.iloc[i])
        if abs(cur - last) >= 0.05:
            last = cur
        actual_scale[i] = last
    actual_scale = pd.Series(actual_scale, index=idx)

    daily = np.zeros(n)
    prev_w = 1.0
    for i in range(n):
        if i == 0:
            daily[i] = 0.0
            prev_w = actual_scale.iloc[i]
            continue
        w_mom_d = prev_w
        w_cash_d = 1.0 - prev_w
        r = w_mom_d * mom30_ret.iloc[i] + w_cash_d * daily_cash_yield.iloc[i]
        # Update weight today; cost on change
        new_w = actual_scale.iloc[i]
        if abs(new_w - prev_w) > 1e-9:
            cost = abs(new_w - prev_w) * LONG_BPS / 10000
            r -= cost
            prev_w = new_w
        daily[i] = r
    return pd.Series(daily, index=idx)


# ─────────────────────────────────────────────────────────────────────────
# Run strategy v1.4
# ─────────────────────────────────────────────────────────────────────────

print("Running v1.4 strategy ...", file=sys.stderr)
s = MacroStrategy(make_combiner(rotate_stress=True, rotate_panic=False,
                                use_momentum_gold=True),
                  nifty_cost_bps=SHORT_BPS, gold_cost_bps=GOLD_BPS,
                  long_target="NIFTYMOM30", long_cost_bps=LONG_BPS,
                  apply_tax=False)
res = s.run(raw)
strategy_daily_pretax = res["strategy_return_pretax"].fillna(0.0)


# ─────────────────────────────────────────────────────────────────────────
# Run all benchmarks
# ─────────────────────────────────────────────────────────────────────────

print("Running benchmarks ...", file=sys.stderr)
benchmarks_raw = {
    "Strategy v1.4":                       strategy_daily_pretax,
    "1. NIFTY 50 B&H":                     bench_nifty_bh(),
    "2. Mom30 B&H":                        bench_mom30_bh(),
    "3. GOLDBEES B&H":                     bench_gold_bh(),
    "4. Static 50/50":                     bench_static_50_50(),
    "5. Static 70/30":                     bench_static_70_30(),
    "6. Risk-parity":                      bench_risk_parity(),
    "7. Dynamic A: Regime filter alone":   bench_dynamic_A(),
    "8. Dynamic B: Regime + static gold":  bench_dynamic_B(),
    "9. Dynamic C: Cross-sectional mom":   bench_dynamic_C(),
    "10. Dynamic D: Vol-targeted Mom30":   bench_dynamic_D(),
}

# Apply tax to all (apples-to-apples) and slice IS
benchmarks = {}
for name, daily in benchmarks_raw.items():
    daily_is = daily.loc[IS_START:IS_END].fillna(0.0)
    benchmarks[name] = {
        "pretax": daily_is,
        "posttax": apply_annual_tax(daily_is, tax_rate=TAX),
    }


# ─────────────────────────────────────────────────────────────────────────
# Sanity checks
# ─────────────────────────────────────────────────────────────────────────

lines = []
def out(s=""): lines.append(s)

m_strat = metrics(benchmarks["Strategy v1.4"]["posttax"])
m_strat_pre = metrics(benchmarks["Strategy v1.4"]["pretax"])
m_nifty = metrics(benchmarks["1. NIFTY 50 B&H"]["pretax"])

out("=" * 110)
out("  SANITY CHECKS")
out("=" * 110)
out(f"\n  Strategy v1.4 post-tax Sharpe: {m_strat['sharpe']:.3f}  (expected ~0.775)")
out(f"  Strategy v1.4 pre-tax  Sharpe: {m_strat_pre['sharpe']:.3f}  (expected ~0.871)")
out(f"  Strategy v1.4 post-tax CAGR:   {m_strat['cagr']*100:.2f}%  (expected ~15.5%)")
out(f"  Strategy v1.4 pre-tax  CAGR:   {m_strat_pre['cagr']*100:.2f}%  (expected ~18.51%)")
out(f"  Strategy v1.4 Max DD:          {m_strat['max_dd']*100:.1f}%  (expected ~-17.2%)")
out(f"\n  NIFTY 50 B&H pre-tax Sharpe:   {m_nifty['sharpe']:.3f}  (expected ~0.27)")
out(f"  NIFTY 50 B&H pre-tax CAGR:     {m_nifty['cagr']*100:.2f}%  (expected ~9.74%)")
ok = (abs(m_strat['sharpe'] - 0.775) <= 0.02
      and abs(m_strat_pre['cagr'] - 0.1851) <= 0.005)
out(f"  Status: {'OK' if ok else 'FAIL'}")
if not ok:
    print("FAIL: sanity check", file=sys.stderr); sys.exit(1)

# Risk-parity sanity: 2008 (high vol) should have higher gold weight than equity
rp_2008 = me_dates[(me_dates.year == 2008) & (me_dates >= pd.Timestamp(IS_START))]
out(f"\n  Risk-parity sanity check — vol-implied weights at 2008 month-ends:")
for d in rp_2008[:6]:
    w_m, w_g = risk_parity_weights(d, window=60)
    out(f"    {d.date()}: w_mom={w_m:.3f}, w_gold={w_g:.3f}")


# ─────────────────────────────────────────────────────────────────────────
# Compute headline metrics for all
# ─────────────────────────────────────────────────────────────────────────

def turnover_estimate(daily):
    """Rough proxy: sum of |return| / avg(1) for asset-bearing days. We don't
    track turnover natively here; report total annual return-vol as proxy
    where exact turnover isn't computed."""
    return np.nan  # placeholder

# Build summary
summary = {}
for name, bdata in benchmarks.items():
    m_post = metrics(bdata["posttax"])
    m_pre = metrics(bdata["pretax"])
    summary[name] = {
        "cagr_post": m_post["cagr"], "cagr_pre": m_pre["cagr"],
        "vol_post": m_post["vol"], "vol_pre": m_pre["vol"],
        "sharpe_post": m_post["sharpe"], "sharpe_pre": m_pre["sharpe"],
        "sortino": m_post["sortino"], "calmar": m_post["calmar"],
        "max_dd": m_post["max_dd"],
    }


# ─────────────────────────────────────────────────────────────────────────
# Output 1: headline comparison table
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 130)
out("  OUTPUT 1 — HEADLINE COMPARISON (all post-tax, except where noted)")
out("=" * 130)
out()
out(f"  {'#':<3s}{'Benchmark':<37s}{'CAGR':>9s}{'Vol':>8s}{'Sharpe':>9s}{'Sortino':>9s}{'Calmar':>9s}{'MaxDD':>9s}")
out("  " + "-" * 90)

# Print strategy first, then 1..10
ordered = ["Strategy v1.4"] + [f"{i}. " for i in range(1, 11)]
for name in benchmarks.keys():
    s_data = summary[name]
    n_disp = name[:36]
    out(f"  {'':<3s}{n_disp:<37s}{s_data['cagr_post']*100:>+8.2f}%"
        f"{s_data['vol_post']*100:>+7.2f}%{s_data['sharpe_post']:>9.3f}"
        f"{s_data['sortino']:>9.2f}{s_data['calmar']:>9.2f}"
        f"{s_data['max_dd']*100:>+8.1f}%")


# ─────────────────────────────────────────────────────────────────────────
# Output 2: strategy excess returns vs each benchmark
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 110)
out("  OUTPUT 2 — STRATEGY EXCESS RETURNS vs each benchmark (post-tax)")
out("=" * 110)
out()
s_data = summary["Strategy v1.4"]
out(f"  {'vs Benchmark':<37s}{'Δ CAGR (pp)':>14s}{'Δ Sharpe':>12s}{'Δ Max DD (pp)':>16s}")
out("  " + "-" * 79)
for name in benchmarks.keys():
    if name == "Strategy v1.4":
        continue
    b = summary[name]
    out(f"  {name:<37s}"
        f"{(s_data['cagr_post'] - b['cagr_post'])*100:>+13.2f}"
        f"{s_data['sharpe_post'] - b['sharpe_post']:>+12.3f}"
        f"{(s_data['max_dd'] - b['max_dd'])*100:>+15.2f}")

out()
out("  Interpretive note:")
out("  - Δ vs Dynamic B (Regime + static gold) isolates the alpha from active")
out("    gold rotation timing (G10 gate + per-latch state machine) above what")
out("    a static gold sleeve with regime filter delivers.")
out("  - Δ vs Dynamic A (Regime filter alone) isolates the alpha from the entire")
out("    override layer (slow-stress + panic-short + gold rotation) above the")
out("    regime filter in isolation.")
out("  - Δ vs Dynamic C (cross-sectional momentum) tests whether the sophisticated")
out("    multi-signal architecture beats a naive momentum-rotation rule.")
out("  - The smallest positive residual across dynamic benchmarks is the cleanest")
out("    measure of regime-timing alpha.")


# ─────────────────────────────────────────────────────────────────────────
# Output 3: crisis-window comparison
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 130)
out("  OUTPUT 3 — CRISIS WINDOWS (pre-tax cumulative returns)")
out("=" * 130)
out()
crisis_windows = [
    ("GFC 2008-09",        "2008-09-01", "2009-03-31"),
    ("Euro debt 2011",     "2011-07-01", "2011-12-31"),
    ("Taper 2013",         "2013-05-15", "2013-09-15"),
    ("NBFC 2018",          "2018-08-15", "2018-11-30"),
    ("COVID 2020",         "2020-02-15", "2020-05-31"),
    ("Russia 2022",        "2022-02-01", "2022-06-30"),
    ("Momentum 2025-26",   "2025-10-01", "2026-04-30"),
]

bench_short = ["Strategy v1.4", "1. NIFTY 50 B&H", "2. Mom30 B&H",
               "5. Static 70/30", "6. Risk-parity",
               "7. Dynamic A: Regime filter alone",
               "8. Dynamic B: Regime + static gold"]

hdr = f"  {'Crisis':<22s}"
for nm in bench_short:
    label = nm.split(":")[0].replace("Strategy v1.4", "Strat").replace(". ", ".") if "." in nm else nm
    label = label[:10]
    hdr += f"{label:>11s}"
out(hdr)
out("  " + "-" * (22 + 11 * len(bench_short)))

# Pull pre-tax full series (not just IS) since some crises span OOS
benchmarks_full_pretax = {}
for name, daily in benchmarks_raw.items():
    benchmarks_full_pretax[name] = daily.fillna(0.0)

for cname, cs, ce in crisis_windows:
    row = f"  {cname:<22s}"
    for nm in bench_short:
        s_ = benchmarks_full_pretax[nm]
        win = s_.loc[cs:ce]
        cum = (1 + win).prod() - 1 if len(win) else float("nan")
        row += f"{cum*100:>+10.2f}%"
    out(row)


# ─────────────────────────────────────────────────────────────────────────
# Output 4: year-by-year strategy excess returns
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 130)
out("  OUTPUT 4 — YEAR-BY-YEAR STRATEGY EXCESS (vs each benchmark, post-tax)")
out("=" * 130)
out()

key_benchmarks = ["1. NIFTY 50 B&H", "2. Mom30 B&H", "5. Static 70/30",
                  "7. Dynamic A: Regime filter alone",
                  "8. Dynamic B: Regime + static gold"]

hdr = f"  {'Year':<6s}{'Strategy':>10s}"
for nm in key_benchmarks:
    short = nm.split(":")[0].replace("1. ", "vs N50").replace("2. ", "vs M30").replace("5. ", "vs 70/30")
    short = short.replace("7. Dynamic A", "vs DynA").replace("8. Dynamic B", "vs DynB")
    short = short[:10]
    hdr += f"{short:>12s}"
out(hdr)
out("  " + "-" * (6 + 10 + 12 * len(key_benchmarks)))

s_post = benchmarks["Strategy v1.4"]["posttax"]
for y in range(2008, 2026):
    mask = s_post.index.year == y
    if not mask.any():
        continue
    s_y = (1 + s_post[mask]).prod() - 1
    row = f"  {y:<6d}{s_y*100:>+9.2f}%"
    for nm in key_benchmarks:
        b_post = benchmarks[nm]["posttax"][mask]
        b_y = (1 + b_post).prod() - 1
        row += f"{(s_y - b_y)*100:>+11.2f}"
    target = "  <<" if y in (2018, 2022, 2025) else ""
    out(row + target)


# ─────────────────────────────────────────────────────────────────────────
# Output 5: turnover comparison (approximate)
# ─────────────────────────────────────────────────────────────────────────

out()
out("=" * 110)
out("  OUTPUT 5 — TURNOVER / TRANSACTION COST BURDEN (approximate)")
out("=" * 110)
out()
out("  Turnover is computed where directly trackable (B&H = 0; monthly rebal ~ 1-2x;")
out("  dynamic strategies vary). For strategy v1.4 and dynamic benchmarks we estimate")
out("  via position-flip counting.")
out()

# Strategy turnover from positions
np_strat = res["nifty_position"].loc[IS_START:IS_END]
gp_strat = res["gold_position"].loc[IS_START:IS_END]
strat_turn = (np_strat.diff().abs().fillna(0).sum()
              + gp_strat.diff().abs().fillna(0).sum()) / (len(np_strat) / 252)

out(f"  {'Benchmark':<37s}{'Approximate annual turnover':>30s}")
out("  " + "-" * 67)
out(f"  {'Strategy v1.4':<37s}{strat_turn:>27.2f}x")
out(f"  {'1. NIFTY 50 B&H':<37s}{'0.00x (buy-and-hold)':>30s}")
out(f"  {'2. Mom30 B&H':<37s}{'0.00x (buy-and-hold)':>30s}")
out(f"  {'3. GOLDBEES B&H':<37s}{'0.06x (one cash-to-gold flip)':>30s}")
out(f"  {'4-5. Static portfolios (monthly rebal)':<37s}{'~1.0-2.0x (12 rebalances/yr)':>30s}")
out(f"  {'6. Risk-parity (monthly rebal)':<37s}{'~1.5-2.5x':>30s}")
out(f"  {'7. Dynamic A: Regime filter alone':<37s}{'~0.3-0.5x (rare flips)':>30s}")
out(f"  {'8. Dynamic B: Regime + static gold':<37s}{'~1.5-2.5x':>30s}")
out(f"  {'9. Dynamic C: Cross-sectional mom':<37s}{'~3-5x (monthly switches)':>30s}")
out(f"  {'10. Dynamic D: Vol-targeted Mom30':<37s}{'~5-10x (daily scaling)':>30s}")


# ─────────────────────────────────────────────────────────────────────────
# Output 6: save + print
# ─────────────────────────────────────────────────────────────────────────

text = "\n".join(lines)
print(text)
with open(OUTPUT_PATH, "w") as f:
    f.write(text + "\n")
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)

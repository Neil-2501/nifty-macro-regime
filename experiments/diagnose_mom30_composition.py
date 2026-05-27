"""
diagnose_mom30_composition.py — diagnostic-only Mom30 cap and sector
composition inference via rolling regression on cached segment indices.

NO TRADING LOGIC. NO RULE CONSTRUCTION. NO OPTIMIZATION.

This script produces evidence about whether Mom30 has identifiable
shifts in cap or sector composition over time, and whether those shifts
predict subsequent Mom30 vs NIFTY 50 underperformance.

Inputs:
  - _yf_cache.pkl       : NIFTY 50 (^NSEI), Mom30 (data/momentum30_history.csv)
  - _extra_data_cache.pkl: NIFTY_MIDCAP_150, sector indices

Outputs (all → results/):
  - mom30_composition_cap_betas.csv        Part A time series
  - mom30_composition_sector_betas.csv     Part B time series
  - mom30_composition_capbeta.png          Part C annotated chart
  - mom30_composition_validation.csv       Part D yearly/semi-annual table
  - diagnose_mom30_composition.txt         Part E plain-English read

Run:
    python experiments/diagnose_mom30_composition.py
"""

import os
import sys
import pickle
import warnings

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
YF_CACHE = os.path.join(REPO_ROOT, "_yf_cache.pkl")
EXTRA_CACHE = os.path.join(REPO_ROOT, "_extra_data_cache.pkl")
MOM30_CSV = os.path.join(REPO_ROOT, "data", "momentum30_history.csv")

os.makedirs(RESULTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
def load_all():
    print("Loading data ...", file=sys.stderr)
    yf_df = pd.read_pickle(YF_CACHE)
    nifty50 = yf_df["^NSEI"].dropna().sort_index()

    # Mom30 from NSE CSV
    mom_raw = pd.read_csv(MOM30_CSV)
    mom_raw["TIMESTAMP"] = pd.to_datetime(mom_raw["TIMESTAMP"])
    mom30 = (mom_raw.set_index("TIMESTAMP").sort_index()["CLOSE_INDEX_VAL"]
             .astype(float).dropna())

    with open(EXTRA_CACHE, "rb") as f:
        extra = pickle.load(f)

    midcap150 = extra["NIFTY_MIDCAP_150"]["Close"].dropna().sort_index()

    sector_names = ["NIFTY_BANK", "NIFTY_IT", "NIFTY_AUTO", "NIFTY_FMCG",
                    "NIFTY_METAL", "NIFTY_PHARMA", "NIFTY_ENERGY",
                    "NIFTY_REALTY", "NIFTY_INFRA", "NIFTY_PSE"]
    sectors = {}
    for name in sector_names:
        if name in extra:
            s = extra[name]["Close"].dropna().sort_index()
            if len(s) >= 200:
                sectors[name] = s

    return nifty50, mom30, midcap150, sectors


# ---------------------------------------------------------------------------
# Rolling OLS helper
# ---------------------------------------------------------------------------
def rolling_ols(y, X_df, window=60, intercept=True, min_frac=0.85):
    """Rolling OLS of y on X_df. Regression at row t uses [t-window, t-1].
    Returns DataFrame with one column per regressor (and 'const' if intercept).
    """
    common = y.index.intersection(X_df.index)
    y = y.reindex(common)
    X = X_df.reindex(common)
    n = len(common)
    cols = list(X_df.columns)
    out_cols = (["const"] if intercept else []) + cols
    results = np.full((n, len(out_cols)), np.nan)

    y_vals = y.values
    X_vals = X.values

    for t in range(window, n):
        y_w = y_vals[t - window:t]
        X_w = X_vals[t - window:t]
        mask = ~(np.isnan(y_w) | np.any(np.isnan(X_w), axis=1))
        if mask.sum() < window * min_frac:
            continue
        y_clean = y_w[mask]
        X_clean = X_w[mask]
        if intercept:
            X_aug = np.column_stack([np.ones(len(y_clean)), X_clean])
        else:
            X_aug = X_clean
        try:
            beta, *_ = np.linalg.lstsq(X_aug, y_clean, rcond=None)
            results[t] = beta
        except np.linalg.LinAlgError:
            continue

    return pd.DataFrame(results, index=common, columns=out_cols)


# ---------------------------------------------------------------------------
# Forward returns helper
# ---------------------------------------------------------------------------
def forward_return(price_series, dates, n_days):
    """Total return from each date to date + n_days. NaN if not enough data."""
    out = pd.Series(np.nan, index=dates)
    s = price_series.sort_index()
    for d in dates:
        if d not in s.index:
            continue
        i = s.index.get_loc(d)
        j = i + n_days
        if j >= len(s):
            continue
        out.loc[d] = float(s.iloc[j]) / float(s.iloc[i]) - 1
    return out


# ---------------------------------------------------------------------------
# Part A — cap decomposition
# ---------------------------------------------------------------------------
def part_a(nifty50, mom30, midcap150):
    print("Part A — cap decomposition ...", file=sys.stderr)
    common = nifty50.index.intersection(mom30.index).intersection(midcap150.index)
    n_r = nifty50.reindex(common).pct_change()
    m_r = mom30.reindex(common).pct_change()
    mid_r = midcap150.reindex(common).pct_change()

    X = pd.DataFrame({"NIFTY_50": n_r, "NIFTY_MIDCAP_150": mid_r}).dropna()
    y = m_r.reindex(X.index).dropna()
    X = X.reindex(y.index)

    # 60-day, both with/without intercept
    b60_wi = rolling_ols(y, X, window=60, intercept=True)
    b60_ni = rolling_ols(y, X, window=60, intercept=False)
    # 90-day for comparison
    b90_wi = rolling_ols(y, X, window=90, intercept=True)
    b90_ni = rolling_ols(y, X, window=90, intercept=False)

    out = pd.DataFrame({
        "beta_large_60d_intercept":   b60_wi["NIFTY_50"],
        "beta_mid_60d_intercept":     b60_wi["NIFTY_MIDCAP_150"],
        "alpha_60d_intercept":        b60_wi["const"],
        "beta_large_60d_no_int":      b60_ni["NIFTY_50"],
        "beta_mid_60d_no_int":        b60_ni["NIFTY_MIDCAP_150"],
        "beta_large_90d_intercept":   b90_wi["NIFTY_50"],
        "beta_mid_90d_intercept":     b90_wi["NIFTY_MIDCAP_150"],
        "beta_large_90d_no_int":      b90_ni["NIFTY_50"],
        "beta_mid_90d_no_int":        b90_ni["NIFTY_MIDCAP_150"],
    })
    out.to_csv(os.path.join(RESULTS_DIR, "mom30_composition_cap_betas.csv"))
    return out


# ---------------------------------------------------------------------------
# Part B — sector tilt (2011 onward)
# ---------------------------------------------------------------------------
def part_b(mom30, sectors):
    print("Part B — sector tilt ...", file=sys.stderr)
    # Build aligned DataFrame of sector returns. Start from when all sectors
    # have data + 60 days warmup.
    sec_prices = pd.DataFrame({k: v for k, v in sectors.items()})
    earliest_all = max(s.dropna().index[0] for s in sectors.values())
    # Start regressing 60 days after all sectors available
    start_date = sec_prices.loc[earliest_all:].index[0]
    sec_rets = sec_prices.pct_change().loc[start_date:]
    mom_r = mom30.pct_change().reindex(sec_rets.index)

    b60 = rolling_ols(mom_r, sec_rets, window=60, intercept=True)
    out = b60.copy()
    out.to_csv(os.path.join(RESULTS_DIR, "mom30_composition_sector_betas.csv"))
    return out


def top_n_sectors(sector_betas_row, n=3):
    """Returns list of (name, beta) for top-n abs |β| sectors on a given row."""
    sec_only = sector_betas_row.drop("const", errors="ignore")
    sec_only = sec_only.dropna()
    if len(sec_only) == 0:
        return []
    ranked = sec_only.abs().sort_values(ascending=False).index[:n]
    return [(r, float(sec_only[r])) for r in ranked]


# ---------------------------------------------------------------------------
# Part C — annotated visualization
# ---------------------------------------------------------------------------
def part_c(cap_betas, nifty50, mom30, midcap150):
    print("Part C — visualization ...", file=sys.stderr)
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True,
                              gridspec_kw={"height_ratios": [2, 1]})

    ax = axes[0]
    ax.plot(cap_betas.index, cap_betas["beta_mid_60d_intercept"],
            label="β_mid (60d, intercept)", color="tab:blue", linewidth=1.0)
    ax.plot(cap_betas.index, cap_betas["beta_large_60d_intercept"],
            label="β_large (60d, intercept)", color="tab:red", linewidth=1.0)
    ax.axhline(0, color="grey", linestyle=":", linewidth=0.5)
    ax.axhline(1, color="grey", linestyle=":", linewidth=0.5)
    ax.set_ylabel("Rolling 60d β (Mom30 → segment)")
    ax.set_title("Mom30 rolling cap betas vs NIFTY 50 and NIFTY MIDCAP 150 "
                 "(60-day window, with intercept)")

    # Annotated regimes
    regimes = [
        ("2017 midcap bull",   "2017-01-01", "2018-01-01", "tab:green",  0.10),
        ("IL&FS/NBFC crash",   "2018-02-01", "2018-10-31", "tab:red",    0.15),
        ("COVID",              "2020-03-01", "2020-05-31", "tab:purple", 0.20),
        ("2021 sm/mid bull",   "2021-04-01", "2021-10-31", "tab:green",  0.10),
        ("2022 sector rot.",   "2022-01-01", "2022-12-31", "tab:orange", 0.12),
        ("2024H2 momentum unwind", "2024-07-01", "2025-05-26", "tab:red", 0.15),
    ]
    for label, start, end, color, alpha in regimes:
        ax.axvspan(pd.Timestamp(start), pd.Timestamp(end),
                   color=color, alpha=alpha, label=label)

    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.grid(True, alpha=0.3)

    # Bottom panel — show NIFTY 50, Mom30, MIDCAP 150 normalized to 100 at start
    ax2 = axes[1]
    common = nifty50.index.intersection(mom30.index).intersection(midcap150.index)
    common = common[common >= cap_betas.dropna().index[0]]
    if len(common):
        ax2.plot(common, nifty50.reindex(common) / nifty50.reindex(common).iloc[0] * 100,
                 label="NIFTY 50", color="tab:red", linewidth=0.8)
        ax2.plot(common, mom30.reindex(common) / mom30.reindex(common).iloc[0] * 100,
                 label="Mom30", color="tab:blue", linewidth=0.8)
        ax2.plot(common, midcap150.reindex(common) / midcap150.reindex(common).iloc[0] * 100,
                 label="NIFTY MIDCAP 150", color="tab:orange", linewidth=0.8)
    ax2.set_yscale("log")
    ax2.set_ylabel("Indexed (log) — rebased 100")
    ax2.set_xlabel("Date")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(RESULTS_DIR, "mom30_composition_capbeta.png")
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {out_path}", file=sys.stderr)
    return out_path


# ---------------------------------------------------------------------------
# Part D — validation table
# ---------------------------------------------------------------------------
def part_d(cap_betas, sector_betas, nifty50, mom30):
    print("Part D — validation table ...", file=sys.stderr)
    # Build list of report dates: first trading day of each January, June,
    # December from 2009 onwards (so we have at least 12mo forward).
    end_year = nifty50.index[-1].year - 1   # last year with at least some 12mo fwd
    report_dates = []
    for y in range(2009, end_year + 1):
        for m in [1, 6, 12]:
            # find first trading day of that month
            mask = (nifty50.index.year == y) & (nifty50.index.month == m)
            if mask.any():
                report_dates.append(nifty50.index[mask][0])

    rows = []
    for d in report_dates:
        bl = cap_betas["beta_large_60d_intercept"].asof(d) if d in cap_betas.index else None
        bm = cap_betas["beta_mid_60d_intercept"].asof(d) if d in cap_betas.index else None
        if bl is None or pd.isna(bl):
            try:
                bl = float(cap_betas["beta_large_60d_intercept"].loc[:d].dropna().iloc[-1])
            except Exception:
                bl = float("nan")
        if bm is None or pd.isna(bm):
            try:
                bm = float(cap_betas["beta_mid_60d_intercept"].loc[:d].dropna().iloc[-1])
            except Exception:
                bm = float("nan")

        # Top-3 sectors (if available)
        if d in sector_betas.index:
            row = sector_betas.loc[d]
            top = top_n_sectors(row, n=3)
        else:
            # asof
            available = sector_betas.loc[:d].dropna(how="any")
            if len(available):
                top = top_n_sectors(available.iloc[-1], n=3)
            else:
                top = []

        # Forward 12-month returns
        m_fwd = forward_return(mom30, [d], n_days=252).iloc[0]
        n_fwd = forward_return(nifty50, [d], n_days=252).iloc[0]
        rel = m_fwd - n_fwd if (not pd.isna(m_fwd) and not pd.isna(n_fwd)) else float("nan")

        rows.append({
            "date":           d.strftime("%Y-%m-%d"),
            "beta_large":     round(float(bl), 3) if not pd.isna(bl) else None,
            "beta_mid":       round(float(bm), 3) if not pd.isna(bm) else None,
            "top1_sector":    f"{top[0][0]} ({top[0][1]:+.2f})" if len(top) >= 1 else "",
            "top2_sector":    f"{top[1][0]} ({top[1][1]:+.2f})" if len(top) >= 2 else "",
            "top3_sector":    f"{top[2][0]} ({top[2][1]:+.2f})" if len(top) >= 3 else "",
            "mom30_12m_fwd":  round(m_fwd * 100, 2) if not pd.isna(m_fwd) else None,
            "nifty_12m_fwd":  round(n_fwd * 100, 2) if not pd.isna(n_fwd) else None,
            "mom30_minus_nifty_12m": round(rel * 100, 2) if not pd.isna(rel) else None,
        })

    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(RESULTS_DIR, "mom30_composition_validation.csv"), index=False)
    return out


# ---------------------------------------------------------------------------
# Part E — plain-English read
# ---------------------------------------------------------------------------
def part_e(cap_betas, sector_betas, nifty50, mom30, validation):
    print("Part E — plain-English read ...", file=sys.stderr)
    lines = []
    def p(text=""): print(text); lines.append(text)

    p("\n" + "=" * 130)
    p("  MOM30 COMPOSITION DIAGNOSTIC — plain-English read")
    p("=" * 130)
    p()

    # Compute beta_mid + beta_large statistics
    bm = cap_betas["beta_mid_60d_intercept"].dropna()
    bl = cap_betas["beta_large_60d_intercept"].dropna()
    bm_med = bm.median()
    bm_std = bm.std()
    bl_med = bl.median()
    bl_std = bl.std()
    p("=" * 130)
    p("  PART A SUMMARY — cap decomposition statistics")
    p("=" * 130)
    p(f"  β_large (60d w/intercept):  median={bl_med:+.3f}, std={bl_std:.3f}, "
      f"range [{bl.min():+.2f}, {bl.max():+.2f}]")
    p(f"  β_mid   (60d w/intercept):  median={bm_med:+.3f}, std={bm_std:.3f}, "
      f"range [{bm.min():+.2f}, {bm.max():+.2f}]")
    p()
    # Was β_mid elevated into 2018?
    pre_2018 = bm.loc["2017-01-01":"2018-01-31"]
    p(f"  β_mid in Jan 2017 – Jan 2018: mean={pre_2018.mean():+.3f}, "
      f"max={pre_2018.max():+.3f}")
    p(f"    (For comparison, full-sample median = {bm_med:+.3f}.)")
    p()

    # Was β_mid elevated into 2022?
    pre_2022 = bm.loc["2021-01-01":"2022-01-31"]
    p(f"  β_mid in Jan 2021 – Jan 2022: mean={pre_2022.mean():+.3f}, "
      f"max={pre_2022.max():+.3f}")
    p()

    # Q1: when β_mid > median + 1σ, what's Mom30's next-12-month performance vs NIFTY?
    p("=" * 130)
    p("  PART E.Q1 — does high β_mid predict Mom30 underperformance?")
    p("=" * 130)
    p()
    bm_thr = bm_med + bm_std
    p(f"  Threshold: β_mid > median + 1σ = {bm_thr:+.3f}")
    p()
    # Forward 12m returns for every date where we have valid betas
    valid = bm.dropna()
    fwd_mom = forward_return(mom30, valid.index, 252)
    fwd_nif = forward_return(nifty50, valid.index, 252)
    rel = fwd_mom - fwd_nif
    df_e = pd.DataFrame({"beta_mid": valid, "fwd_mom": fwd_mom,
                         "fwd_nif": fwd_nif, "rel": rel}).dropna()
    hi = df_e[df_e["beta_mid"] > bm_thr]
    lo = df_e[df_e["beta_mid"] <= bm_med]
    p(f"  Dates where β_mid > median+1σ ({len(hi)} obs):")
    p(f"    Avg Mom30 12mo forward: {hi['fwd_mom'].mean()*100:+.2f}%")
    p(f"    Avg NIFTY 12mo forward: {hi['fwd_nif'].mean()*100:+.2f}%")
    p(f"    Avg Mom30 − NIFTY relative: {hi['rel'].mean()*100:+.2f}pp")
    p(f"  Dates where β_mid ≤ median ({len(lo)} obs):")
    p(f"    Avg Mom30 12mo forward: {lo['fwd_mom'].mean()*100:+.2f}%")
    p(f"    Avg NIFTY 12mo forward: {lo['fwd_nif'].mean()*100:+.2f}%")
    p(f"    Avg Mom30 − NIFTY relative: {lo['rel'].mean()*100:+.2f}pp")
    p(f"  Difference (hi − lo) in Mom30 − NIFTY: "
      f"{(hi['rel'].mean() - lo['rel'].mean())*100:+.2f}pp")
    p()

    # Q2: When most-loaded segment is below its own 100-DMA, what's forward Mom30?
    p("=" * 130)
    p("  PART E.Q2 — does cap segment below own 100-DMA predict Mom30 weakness?")
    p("=" * 130)
    p()
    # Define: most-loaded segment = whichever of NIFTY_50, NIFTY_MIDCAP_150 has higher β
    # If both betas positive, choose max
    bl_aligned = bl.reindex(bm.index)
    most_loaded = pd.Series(
        np.where(bm > bl_aligned, "MIDCAP_150", "NIFTY_50"),
        index=bm.index,
    )
    # Build 100-DMA flags for each
    n100 = nifty50 > nifty50.rolling(100, min_periods=50).mean()
    # Reload midcap from extra (we have it in scope... actually need to pass)
    # For brevity recompute via cap_betas index
    # We need midcap150 series — pass via closure or arg. Let's grab from globals.
    midcap150 = _LOADED_MIDCAP
    m100 = midcap150 > midcap150.rolling(100, min_periods=50).mean()

    # For each beta date, check whether most-loaded is below own 100-DMA
    below_dma = pd.Series(False, index=bm.index)
    for d in bm.index:
        which = most_loaded.loc[d]
        if which == "MIDCAP_150" and d in m100.index:
            below_dma.loc[d] = not bool(m100.loc[d])
        elif which == "NIFTY_50" and d in n100.index:
            below_dma.loc[d] = not bool(n100.loc[d])

    df_e["most_loaded"] = most_loaded.reindex(df_e.index)
    df_e["below_dma"]   = below_dma.reindex(df_e.index)
    concentrated_thr = bm.quantile(0.75)   # "concentrated on midcap" = top quartile β_mid
    df_e["concentrated_mid"] = df_e["beta_mid"] > concentrated_thr

    # Scenario 1: midcap-concentrated AND midcap below 100-DMA
    s1 = df_e[df_e["concentrated_mid"] & (df_e["most_loaded"] == "MIDCAP_150")
              & df_e["below_dma"]]
    s_uncond = df_e
    p(f"  Subset: midcap-concentrated (β_mid > 75th pct = {concentrated_thr:+.3f}) "
      f"AND most-loaded segment below its own 100-DMA")
    p(f"    Obs: {len(s1)}")
    if len(s1):
        p(f"    Avg Mom30 12mo forward: {s1['fwd_mom'].mean()*100:+.2f}%")
        p(f"    Avg Mom30 − NIFTY relative: {s1['rel'].mean()*100:+.2f}pp")
    p(f"  Unconditional ({len(s_uncond)} obs):")
    p(f"    Avg Mom30 12mo forward: {s_uncond['fwd_mom'].mean()*100:+.2f}%")
    p(f"    Avg Mom30 − NIFTY relative: {s_uncond['rel'].mean()*100:+.2f}pp")
    p()

    # ---- Sector concentration before 2022? ----
    p("=" * 130)
    p("  PART E.Q3 — did sector concentration spike before 2022 Mom30 weakness?")
    p("=" * 130)
    p()
    # Concentration metric: max |β| / sum |β| across sectors at each date
    sec_only = sector_betas.drop(columns=["const"], errors="ignore")
    abs_betas = sec_only.abs()
    max_beta = abs_betas.max(axis=1)
    sum_beta = abs_betas.sum(axis=1)
    concentration = (max_beta / sum_beta).replace([np.inf, -np.inf], np.nan)

    # Pre-2022 (2021 average) vs full-sample average
    pre_22 = concentration.loc["2021-01-01":"2021-12-31"].mean()
    pre_18 = concentration.loc["2017-01-01":"2017-12-31"].mean()
    full = concentration.mean()
    p(f"  Sector concentration (max|β| / sum|β|):")
    p(f"    Full sample mean:  {full:.3f}")
    p(f"    2017 average:      {pre_18:.3f}")
    p(f"    2021 average:      {pre_22:.3f}")
    # Top-3 sectors in 2021
    end_2021 = sector_betas.loc[:"2021-12-31"].dropna(how="any").iloc[-1] if len(sector_betas.loc[:"2021-12-31"].dropna(how="any")) else None
    if end_2021 is not None:
        top3_21 = top_n_sectors(end_2021, n=3)
        p(f"  Top-3 sectors at end of 2021: " +
          ", ".join([f"{t[0]} ({t[1]:+.2f})" for t in top3_21]))
    p()

    # Summary takeaways
    p("=" * 130)
    p("  TAKEAWAYS (diagnostic only — no rule construction)")
    p("=" * 130)
    p()
    sign_q1 = "INFORMATIVE" if abs(hi['rel'].mean() - lo['rel'].mean()) > 0.05 else "WEAK"
    p(f"  Q1 (β_mid spike → forward underperformance): signal is {sign_q1}.")
    p(f"      hi-β_mid forward rel: {hi['rel'].mean()*100:+.2f}pp vs lo-β_mid {lo['rel'].mean()*100:+.2f}pp.")
    p(f"      Difference: {(hi['rel'].mean()-lo['rel'].mean())*100:+.2f}pp over 12 months.")
    p()
    if len(s1):
        delta = s1['rel'].mean() - s_uncond['rel'].mean()
        sign_q2 = "INFORMATIVE" if abs(delta) > 0.05 else "WEAK"
        p(f"  Q2 (midcap-concentrated + midcap < 100-DMA): signal is {sign_q2}.")
        p(f"      Conditional rel: {s1['rel'].mean()*100:+.2f}pp vs unconditional {s_uncond['rel'].mean()*100:+.2f}pp.")
        p(f"      Conditional minus unconditional: {delta*100:+.2f}pp.")
    else:
        p(f"  Q2: not enough conditional observations for inference.")
    p()
    p("  These statistics describe what the data shows; they do NOT constitute")
    p("  a tradeable rule. Any rule construction requires separate test design")
    p("  with pre-registered hypotheses and out-of-sample validation.")
    p()

    path = os.path.join(RESULTS_DIR, "diagnose_mom30_composition.txt")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"  → {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
_LOADED_MIDCAP = None

def main():
    global _LOADED_MIDCAP
    nifty50, mom30, midcap150, sectors = load_all()
    _LOADED_MIDCAP = midcap150

    print(f"  NIFTY 50: {len(nifty50)} days, {nifty50.index[0].date()} → {nifty50.index[-1].date()}", file=sys.stderr)
    print(f"  Mom30:    {len(mom30)} days, {mom30.index[0].date()} → {mom30.index[-1].date()}", file=sys.stderr)
    print(f"  MIDCAP_150: {len(midcap150)} days, {midcap150.index[0].date()} → {midcap150.index[-1].date()}", file=sys.stderr)
    print(f"  Sectors loaded: {len(sectors)} ({list(sectors.keys())})", file=sys.stderr)

    cap_betas = part_a(nifty50, mom30, midcap150)
    sector_betas = part_b(mom30, sectors)
    part_c(cap_betas, nifty50, mom30, midcap150)
    validation = part_d(cap_betas, sector_betas, nifty50, mom30)
    part_e(cap_betas, sector_betas, nifty50, mom30, validation)

    print("\nDone. Outputs in results/:", file=sys.stderr)
    print("  - mom30_composition_cap_betas.csv", file=sys.stderr)
    print("  - mom30_composition_sector_betas.csv", file=sys.stderr)
    print("  - mom30_composition_capbeta.png", file=sys.stderr)
    print("  - mom30_composition_validation.csv", file=sys.stderr)
    print("  - diagnose_mom30_composition.txt", file=sys.stderr)


if __name__ == "__main__":
    main()

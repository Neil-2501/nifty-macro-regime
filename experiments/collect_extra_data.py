"""
collect_extra_data.py — pull and cache additional NSE market data series
for future experiments.

ISOLATION GUARANTEE:
  - Does NOT touch strategy.py or any existing experiment.
  - Does NOT touch _yf_cache.pkl (the main strategy cache).
  - Writes to _extra_data_cache.pkl in the repo root (a separate file).
  - Writes coverage report to results/extra_data_coverage.txt.

Re-running this script REFRESHES the cache (overwrite, not append). The
cache structure is a dict {canonical_name: DataFrame}, where each
DataFrame has a DatetimeIndex and at minimum a "Close" column. OHLCV is
retained where available.

Each ticker is tried with its primary symbol first; if that returns empty
or errors, the listed fallback is tried. Failures are flagged in the
coverage report at the bottom.

Coverage report columns:
  Canonical          — clean canonical name we'll use in future experiments
  Ticker used        — the actual symbol that worked (primary or fallback)
  First valid date   — earliest date with Close data
  Last valid date    — latest date with Close data
  Days               — number of trading days with data
  Reaches 2008?      — YES/NO does the series cover 2008-04-01 (backtest start)
  Corr60(NIFTY)      — average 60-day rolling return correlation with ^NSEI
                       (sanity check that the series moves with the market)

Usage:
    python experiments/collect_extra_data.py
"""

import os
import sys
import time
import pickle
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)

# ----- Paths --------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(REPO_ROOT, "_extra_data_cache.pkl")
REPORT_PATH = os.path.join(REPO_ROOT, "results", "extra_data_coverage.txt")
BACKTEST_START = pd.Timestamp("2008-04-01")

# ----- Ticker specs -------------------------------------------------------
# (canonical_name, primary_symbol, fallback_symbol_or_None)
TICKER_SPECS = [
    # NSE sector indices
    ("NIFTY_BANK",            "^NSEBANK",        None),
    ("NIFTY_IT",              "^CNXIT",          None),
    ("NIFTY_AUTO",            "^CNXAUTO",        None),
    ("NIFTY_FMCG",            "^CNXFMCG",        None),
    ("NIFTY_METAL",           "^CNXMETAL",       None),
    ("NIFTY_PHARMA",          "^CNXPHARMA",      None),
    ("NIFTY_ENERGY",          "^CNXENERGY",      None),
    ("NIFTY_REALTY",          "^CNXREALTY",      None),
    ("NIFTY_INFRA",           "^CNXINFRA",       None),
    ("NIFTY_PSE",             "^CNXPSE",         None),
    ("NIFTY_FIN_SERVICES",    "^CNXFIN",         "NIFTY_FIN_SERVICE.NS"),
    # Cap segments
    ("NIFTY_MIDCAP_100",      "^CNXMIDCAP",      None),
    ("NIFTY_MIDCAP_150",      "^NSMIDCP",        "NIFTYMIDCAP150.NS"),
    ("NIFTY_SMALLCAP_250",    "^CNXSC",          "NIFTYSMLCAP250.NS"),
    ("NIFTY_100",             "^CNX100",         None),
    ("NIFTY_500",             "^CNX500",         None),
    # Style / factor indices
    ("NIFTY_QUALITY_30",      "^CNXQUALITY30",   "NIFTYQUALITY30.NS"),
    ("NIFTY_LOWVOL_30",       "^CNXLOWVOL30",    "NIFTYLOWVOL30.NS"),
    ("NIFTY_ALPHA_50",        "^CNXALPHA50",     "NIFTYALPHA50.NS"),
]


def fetch_one(symbol: str):
    """Try to download a single symbol. Returns DataFrame (with at least
    Close column) on success, or None on failure / empty result."""
    try:
        df = yf.download(
            symbol,
            start="2007-01-01",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception as e:
        print(f"    ERROR {symbol}: {e}", file=sys.stderr)
        return None

    if df is None or df.empty:
        return None

    # Flatten multi-index columns (yfinance returns multi-index even for single ticker)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    if "Close" not in df.columns:
        return None

    # Drop rows where Close is NaN to find true coverage
    if df["Close"].dropna().empty:
        return None

    return df


def pull_with_fallback(canonical: str, primary: str, fallback):
    """Try primary; if empty/errors, try fallback. Returns (ticker_used, df) or (None, None)."""
    print(f"  {canonical}: trying {primary} ...", file=sys.stderr)
    df = fetch_one(primary)
    if df is not None:
        return primary, df
    if fallback:
        print(f"    primary failed; trying fallback {fallback} ...", file=sys.stderr)
        df = fetch_one(fallback)
        if df is not None:
            return fallback, df
    return None, None


def fetch_nifty_for_correlation():
    """Pull NIFTY 50 fresh just for the correlation column in the coverage
    report. Not saved to the extra cache."""
    print("  (correlation ref) NIFTY 50 ^NSEI ...", file=sys.stderr)
    df = fetch_one("^NSEI")
    if df is None:
        return None
    return df["Close"]


def avg_rolling_corr(series_a: pd.Series, series_b: pd.Series, window: int = 60) -> float:
    """Average of rolling-window correlation of daily returns."""
    a, b = series_a.dropna(), series_b.dropna()
    common = a.index.intersection(b.index)
    if len(common) < window + 5:
        return float("nan")
    ra = a.loc[common].pct_change()
    rb = b.loc[common].pct_change()
    corr = ra.rolling(window).corr(rb)
    return float(corr.mean())


def main():
    print("=" * 70, file=sys.stderr)
    print(f"Collecting extra market data → {CACHE_PATH}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    cache = {}                 # canonical → DataFrame
    used_symbols = {}          # canonical → ticker_used
    failed = []                # list of (canonical, primary, fallback)

    for canonical, primary, fallback in TICKER_SPECS:
        ticker, df = pull_with_fallback(canonical, primary, fallback)
        if df is not None:
            cache[canonical] = df
            used_symbols[canonical] = ticker
            n = int(df["Close"].dropna().shape[0])
            print(f"    ✓ {canonical} via {ticker} ({n} trading days)", file=sys.stderr)
        else:
            failed.append((canonical, primary, fallback))
            print(f"    ✗ {canonical} FAILED", file=sys.stderr)
        time.sleep(0.5)        # polite delay to avoid rate limits

    # Save cache (idempotent: overwrite any existing cache)
    os.makedirs(os.path.dirname(CACHE_PATH) or ".", exist_ok=True)
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(cache, f)
    print(f"\nCached {len(cache)} series to {CACHE_PATH}", file=sys.stderr)

    # Pull NIFTY 50 for correlation reference (not saved to extra cache)
    nifty_close = fetch_nifty_for_correlation()

    # ----- Coverage report ----------------------------------------------
    out = []

    def p(text=""):
        print(text)
        out.append(text)

    p()
    p("=" * 130)
    p("  EXTRA DATA COVERAGE REPORT")
    p(f"  Cache: {CACHE_PATH}")
    p(f"  Backtest start anchor: {BACKTEST_START.date()}")
    p("=" * 130)
    p()
    p(f"  {'Canonical':<22} {'Ticker used':<22} {'First date':<12} "
      f"{'Last date':<12} {'Days':>6} {'≥2008?':>8} {'Corr60 NIFTY':>13}")
    p("  " + "-"*22 + " " + "-"*22 + " " + "-"*12 + " " + "-"*12 + " "
      + "-"*6 + " " + "-"*8 + " " + "-"*13)

    full_sample_ok = []          # series with first date ≤ 2008-04-01 AND days ≥ 60
    partial_sample = []          # (canonical, first_date) for partial but usable
    minimal_data = []            # (canonical, ticker) for ones that returned <60 days
    MIN_USABLE_DAYS = 60

    for canonical, primary, fallback in TICKER_SPECS:
        if canonical not in cache:
            continue
        df = cache[canonical]
        ticker = used_symbols[canonical]
        close = df["Close"].dropna()
        first = close.index[0]
        last = close.index[-1]
        days = len(close)
        covers_2008 = first <= BACKTEST_START
        usable = days >= MIN_USABLE_DAYS

        # Correlation with NIFTY 50
        if nifty_close is not None and usable:
            corr60 = avg_rolling_corr(close, nifty_close, window=60)
            corr_str = f"{corr60:>+13.3f}" if not np.isnan(corr60) else f"{'n/a':>13}"
        else:
            corr_str = f"{'n/a':>13}"

        if not usable:
            flag = "*NO DATA*"
        elif covers_2008:
            flag = "YES"
        else:
            flag = "NO"

        p(f"  {canonical:<22} {ticker:<22} {first.date()!s:<12} "
          f"{last.date()!s:<12} {days:>6d} {flag:>9} {corr_str}")

        if not usable:
            minimal_data.append((canonical, ticker, days))
        elif covers_2008:
            full_sample_ok.append(canonical)
        else:
            partial_sample.append((canonical, first.date()))

    p()
    p(f"  Legend: YES/NO = covers 2008-04-01. *NO DATA* = yfinance returned <{MIN_USABLE_DAYS} days (effectively unavailable).")
    p()

    # ----- Failure list -------------------------------------------------
    p("=" * 130)
    p("  FAILED TICKERS")
    p("=" * 130)
    if failed:
        for canonical, primary, fallback in failed:
            tried = primary + (f" + {fallback}" if fallback else "")
            p(f"  ✗ {canonical}: tried {tried}")
    else:
        p("  (none — every ticker fetched successfully)")
    p()

    # ----- Usability summary --------------------------------------------
    p("=" * 130)
    p("  USABILITY SUMMARY")
    p("=" * 130)
    p()
    p(f"  FULL SAMPLE (covers 2008-04-01 → today): {len(full_sample_ok)} series")
    for c in full_sample_ok:
        p(f"      - {c}")
    p()
    p(f"  PARTIAL SAMPLE (starts after 2008-04-01, but real history): {len(partial_sample)} series")
    for c, d in partial_sample:
        p(f"      - {c} (first data: {d})")
    p()
    p(f"  EFFECTIVELY UNAVAILABLE — yfinance returned <60 days (treat as failed): {len(minimal_data)} series")
    for c, t, d in minimal_data:
        p(f"      - {c} ({t} returned only {d} day(s))")
    p()
    p(f"  TRUE FAIL (need alternate source — NSE direct, third party, etc.): {len(failed)} series")
    for canonical, primary, fallback in failed:
        tried = primary + (f" + {fallback}" if fallback else "")
        p(f"      - {canonical} (tried {tried})")
    p()

    # ----- Save report ---------------------------------------------------
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("\n".join(out))
    print(f"\nCoverage report saved to {REPORT_PATH}", file=sys.stderr)
    print(f"Cache saved to {CACHE_PATH}", file=sys.stderr)
    print(f"  → load with: import pickle; cache = pickle.load(open({CACHE_PATH!r}, 'rb'))",
          file=sys.stderr)


if __name__ == "__main__":
    main()

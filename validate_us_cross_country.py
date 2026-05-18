"""
validate_us_cross_country.py — DEPLOYED VALIDATION.

Tests whether the v1.4 SlowStressSignal architecture generalizes beyond
Indian data by applying the same signal logic to US data 1995-2025.

Substitutions (US analogs to India inputs):
  India INR weakening   →  US DXY rising (USD strengthening = global flight
                            to safety = US equity stress proxy)
  India VIX             →  US VIX (^VIX)

v5b signal logic preserved:
    currency_stressed = currency.pct_change(20) > 0.01
    vix_stressed = (vix_90d_z > 1.5) AND (vix_5d_mom > 0)
    fires = currency_stressed AND vix_stressed

Output: did the signal fire on 9 known US stress events?
False-positive check: 4 calm bull periods.

This is a SIGNAL-FIRING validation only — no full backtest. It tests
whether the SlowStressSignal architecture is country-economics-dependent
or generalizes to other major equity markets.

Result (as of validation date): 9 of 9 US stress events caught, overall
fire rate 3.84%, calm-year false-positive rates 0-7.5%. The signal
architecture validates cross-country.
"""

import os
import sys
import pandas as pd
import yfinance as yf

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "validate_us_cross_country_results.txt")
WARMUP    = "1993-01-01"
SAMPLE_START = "1995-01-01"  # 2-year warmup for 90d/252d windows

# Known US stress windows for validation
US_STRESS_WINDOWS = [
    ("1998 LTCM / Russia / Asian crisis",  "1998-07-01", "1998-12-31"),
    ("2000-2002 dot-com bust",              "2000-03-01", "2002-12-31"),
    ("2007 pre-GFC slow burn",              "2007-06-01", "2007-12-31"),
    ("2008 GFC peak",                       "2008-09-01", "2009-03-31"),
    ("2011 Euro debt crisis",               "2011-07-01", "2011-12-31"),
    ("2015-2016 China devaluation",         "2015-08-01", "2016-02-29"),
    ("2018 Fed hiking / China trade war",   "2018-09-01", "2018-12-31"),
    ("2020 COVID",                          "2020-02-15", "2020-04-30"),
    ("2022 inflation + Ukraine",            "2022-02-01", "2022-10-31"),
]

# Calm bull windows for false-positive check
US_CALM_WINDOWS = [
    ("2014 calm bull",                      "2014-01-01", "2014-12-31"),
    ("2017 calm bull",                      "2017-01-01", "2017-12-31"),
    ("2019 calm bull",                      "2019-01-01", "2019-09-30"),
    ("2021 reflation",                      "2021-01-01", "2021-12-31"),
]


def identify_latches(signal):
    s = signal.astype(bool)
    s_prev = s.shift(1, fill_value=False)
    starts = list(s.index[s & ~s_prev])
    ends   = list(s.index[~s & s_prev])
    if len(ends) < len(starts):
        ends.append(s.index[-1])
    out = []
    for st, en in zip(starts, ends):
        en_idx = s.index.get_loc(en)
        last = s.index[en_idx - 1] if en_idx > 0 else st
        n = s.index.get_loc(last) - s.index.get_loc(st) + 1
        out.append((st, last, n))
    return out


print("Downloading US data (^GSPC, ^VIX, DXY) ...", file=sys.stderr)
us_tickers = ["^GSPC", "^VIX", "DX-Y.NYB"]
raw = yf.download(us_tickers, start=WARMUP, end=None, auto_adjust=True,
                  progress=False)["Close"]
raw.dropna(how="all", inplace=True)
raw = raw.ffill()

# Build v5b-equivalent signal with US inputs
dxy = raw["DX-Y.NYB"]
vix = raw["^VIX"]
dxy_20d = dxy.pct_change(20)
vix_mean = vix.rolling(90).mean()
vix_std  = vix.rolling(90).std()
vix_z = (vix - vix_mean) / vix_std
vix_5d_mom = vix - vix.shift(5)

DXY_stressed = (dxy_20d > 0.01).fillna(False)
VIX_stressed = ((vix_z > 1.5) & (vix_5d_mom > 0)).fillna(False)
fires = (DXY_stressed & VIX_stressed).fillna(False)

sample = raw.loc[SAMPLE_START:]
fires_sample = fires.loc[SAMPLE_START:]
latches = identify_latches(fires_sample)


lines = []
def out(s=""): lines.append(s)


out("=" * 110)
out("  US CROSS-COUNTRY VALIDATION — v1.4 SlowStressSignal architecture")
out(f"  Sample: {SAMPLE_START} → {raw.index[-1].date()}  "
    f"({len(sample)} trading days)")
out("=" * 110)
out()
out("  Signal (US analogs of India inputs):")
out("    DXY_stressed = DXY 20d return > 1%       (USD strengthening = stress)")
out("    VIX_stressed = (90d z > 1.5) AND (5d mom > 0)")
out("    fires        = DXY_stressed AND VIX_stressed")
out()
out(f"  Total fires:   {int(fires_sample.sum())} ({fires_sample.mean()*100:.2f}% of days)")
out(f"  Total latches: {len(latches)}")


# Stress windows
out()
out("=" * 110)
out("  KNOWN US STRESS WINDOWS — did the signal fire?")
out("=" * 110)
out()
out(f"  {'Event':<42s}{'Window':<26s}{'Fires?':>8s}{'Days':>6s}{'%':>7s}"
    f"{'1st fire':>22s}")
out("  " + "-" * 111)
hits = 0
for name, start, end in US_STRESS_WINDOWS:
    s_ts = pd.Timestamp(start); e_ts = pd.Timestamp(end)
    win_mask = (fires_sample.index >= s_ts) & (fires_sample.index <= e_ts)
    win_size = win_mask.sum()
    fires_in_window = fires_sample[win_mask].sum()
    if win_size == 0:
        out(f"  {name:<42s}{start[:10]} → {end[:10]:<11s}{'NO DATA':>8s}")
        continue
    fired = fires_in_window > 0
    pct = fires_in_window / win_size * 100 if win_size > 0 else 0
    if fired:
        hits += 1
        first = fires_sample[win_mask & fires_sample].index[0]
        days_in = (first - s_ts).days
        first_str = f"+{days_in}d ({first.date()})"
    else:
        first_str = "—"
    out(f"  {name:<42s}{start[:10]} → {end[:10]:<11s}"
        f"{'YES' if fired else 'NO':>8s}{int(fires_in_window):>6d}"
        f"{pct:>6.1f}%{first_str:>22s}")
out()
out(f"  Stress windows caught: {hits}/{len(US_STRESS_WINDOWS)}")


# Calm windows
out()
out("=" * 110)
out("  CALM BULL WINDOWS — false positive check (signal should be mostly quiet)")
out("=" * 110)
out()
out(f"  {'Period':<42s}{'Window':<26s}{'Fires':>8s}{'Days':>6s}{'% days':>9s}")
out("  " + "-" * 91)
for name, start, end in US_CALM_WINDOWS:
    s_ts = pd.Timestamp(start); e_ts = pd.Timestamp(end)
    win_mask = (fires_sample.index >= s_ts) & (fires_sample.index <= e_ts)
    win_size = win_mask.sum()
    fires_in_window = fires_sample[win_mask].sum()
    pct = fires_in_window / win_size * 100 if win_size > 0 else 0
    out(f"  {name:<42s}{start[:10]} → {end[:10]:<11s}"
        f"{int(fires_in_window):>8d}{win_size:>6d}{pct:>8.1f}%")


# All latches
out()
out("=" * 110)
out("  ALL v5b LATCHES IN US DATA")
out("=" * 110)
out()
out(f"  {'Start':<12s}{'End':<12s}{'Days':>6s}{'VIX':>6s}{'z':>7s}"
    f"{'DXY 20d':>10s}{'~ event':<35s}")
out("  " + "-" * 88)


def find_nearest_event(date):
    for name, start, end in US_STRESS_WINDOWS:
        s_ts = pd.Timestamp(start); e_ts = pd.Timestamp(end)
        if s_ts <= date <= e_ts:
            return name[:33]
        if 0 <= (s_ts - date).days <= 30:
            return f"pre: {name[:28]}"
    return ""


for s, e, n in latches:
    v_at = vix.loc[s] if not pd.isna(vix.loc[s]) else 0
    z_at = vix_z.loc[s] if not pd.isna(vix_z.loc[s]) else 0
    d_at = dxy_20d.loc[s] * 100 if not pd.isna(dxy_20d.loc[s]) else 0
    event = find_nearest_event(s)
    out(f"  {str(s.date()):<12s}{str(e.date()):<12s}{n:>6d}{v_at:>6.1f}"
        f"{z_at:>+7.2f}{d_at:>+9.2f}%  {event:<35s}")


text = "\n".join(lines)
print(text)
with open(OUTPUT_PATH, "w") as f:
    f.write(text + "\n")
print(f"\nSaved to {OUTPUT_PATH}", file=sys.stderr)

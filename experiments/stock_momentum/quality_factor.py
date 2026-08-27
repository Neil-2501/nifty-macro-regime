"""Quality factor — era-specific scoring + cross-sectional percentile bridge.

At each rebalance date:
  1. Build the eligible universe (top-200 most-liquid that meet trust filters)
  2. Apply REPORTING_LAG to pick the latest fiscal year visible at rebalance date
  3. Score quality per stock using era-specific definition
  4. Convert to cross-sectional percentile within the date's universe

Output (parquet): per (symbol, rebalance_date) — quality_score_raw,
quality_percentile, n_components_used, era_used, basis_used.

This module is PURE SCORING. quality_backtest.py runs the portfolios.
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore', category=FutureWarning)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIPELINE_DIR = os.path.join(REPO_ROOT, "data", "bse_pipeline")
PANEL_PATH = os.path.join(PIPELINE_DIR, "extended_fundamentals_v2.parquet")
UNIVERSE_PATH = os.path.join(REPO_ROOT, "data", "stock_universe",
                               "nifty500_pointintime.parquet")
OUT_DIR = os.path.join(REPO_ROOT, "data", "quality_factor")
os.makedirs(OUT_DIR, exist_ok=True)
SCORES_PARQUET = os.path.join(OUT_DIR, "quality_scores_pit.parquet")

# Config (matches the user's spec — change here only)
REPORTING_LAG_MONTHS = 6
UNIVERSE_TOP_N = 200
MIN_CONFIDENCE = {"high", "verified"}
EXCLUDE_FINANCIALS = True
PREFERRED_BASIS = "consolidated"

# Era boundary (last-reported FY at rebalance must be >= 2014 for "post" screen)
ERA_BOUNDARY_FY = 2014


def _winsorize(s, low=0.01, high=0.99):
    if s.empty or s.isna().all():
        return s
    lo = s.quantile(low)
    hi = s.quantile(high)
    return s.clip(lower=lo, upper=hi)


def _zscore(s):
    if s.empty or s.isna().all():
        return s
    std = s.std()
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def load_panel():
    """Load and apply trust filters."""
    df = pd.read_parquet(PANEL_PATH)
    df = df[df['confidence'].isin(MIN_CONFIDENCE)]
    df = df[~df['catastrophic_outlier'].astype(bool)]
    if EXCLUDE_FINANCIALS:
        df = df[~df['is_bank'].fillna(False).astype(bool)]
    # Prefer consolidated where available; fall back to standalone per
    # (symbol, fiscal_year, line_item)
    df['_basis_pref'] = df['basis'].apply(
        lambda b: 0 if b == PREFERRED_BASIS else 1)
    df = df.sort_values(['symbol', 'fiscal_year', 'line_item', '_basis_pref'])
    df = df.drop_duplicates(subset=['symbol', 'fiscal_year', 'line_item'],
                              keep='first').drop(columns=['_basis_pref'])
    return df


def wide_fundamentals(df):
    """Pivot LONG → WIDE (one row per symbol×fiscal_year, columns per metric)."""
    w = df.pivot_table(index=['symbol', 'fiscal_year'],
                          columns='line_item', values='value',
                          aggfunc='first').reset_index()
    return w


def latest_fy_at_date(rebalance_date):
    """Latest fiscal year filed by `rebalance_date` given REPORTING_LAG.
    Indian FY ends March 31. Lag is months from FY end.
    E.g. FY2010 ended Mar 31 2010; with 6mo lag, available Sep 30 2010.
    For rebalance Jun 30 2010 → latest available is FY2009.
    For rebalance Dec 31 2010 → FY2010 is available.
    """
    rd = pd.Timestamp(rebalance_date)
    for y in range(rd.year, 1995, -1):
        fy_end = pd.Timestamp(year=y, month=3, day=31)
        avail = fy_end + pd.DateOffset(months=REPORTING_LAG_MONTHS)
        if avail <= rd:
            return y
    return None


def load_universe_at(rebalance_date):
    """Top-N most-liquid stocks at the rebalance date."""
    u = pd.read_parquet(UNIVERSE_PATH)
    u['rebalance_date'] = pd.to_datetime(u['rebalance_date'])
    sub = u[(u['rebalance_date'] == pd.Timestamp(rebalance_date)) &
              (u['included'])]
    return sub.nlargest(UNIVERSE_TOP_N, 'avg_60d_turnover_rupees')[
        ['symbol', 'rank', 'avg_60d_turnover_rupees']].copy()


def compute_post_2014_components(wide, fy):
    """Piotroski-7 + ratio composite for fiscal year `fy`.
    Returns DataFrame indexed by symbol with: piotroski_frac, piotroski_n,
    ratio_composite, and individual components.
    """
    cur = wide[wide['fiscal_year'] == fy].set_index('symbol')
    prev_raw = wide[wide['fiscal_year'] == fy - 1].set_index('symbol')
    # Align prev to cur's index — Series ops below need identical indices
    prev = prev_raw.reindex(cur.index)

    def safe(d, c):
        if c not in d.columns:
            return pd.Series(dtype=float)
        return d[c]

    np_cur = safe(cur, 'net_profit')
    ta_cur = safe(cur, 'total_assets')
    td_cur = safe(cur, 'total_debt')
    eq_cur = safe(cur, 'equity')
    cfo_cur = safe(cur, 'cfo')
    rev_cur = safe(cur, 'revenue')
    ebit_cur = safe(cur, 'ebit')
    int_cur = safe(cur, 'interest_expense')

    np_prev = safe(prev, 'net_profit')
    ta_prev = safe(prev, 'total_assets')
    td_prev = safe(prev, 'total_debt')
    rev_prev = safe(prev, 'revenue')
    ebit_prev = safe(prev, 'ebit')

    roa_cur = np_cur / ta_cur
    roa_prev = np_prev / ta_prev
    leverage_cur = td_cur / ta_cur
    leverage_prev = td_prev / ta_prev
    margin_cur = ebit_cur / rev_cur
    margin_prev = ebit_prev / rev_prev
    turnover_cur = rev_cur / ta_cur
    turnover_prev = rev_prev / ta_prev

    components = pd.DataFrame(index=cur.index)
    components['P1_ROA_pos']     = (roa_cur > 0).astype(float).where(roa_cur.notna())
    components['P2_CFO_pos']     = (cfo_cur > 0).astype(float).where(cfo_cur.notna())
    components['P3_dROA_pos']    = (roa_cur > roa_prev).astype(float).where(
        roa_cur.notna() & roa_prev.notna())
    components['P4_accruals']    = (cfo_cur > np_cur).astype(float).where(
        cfo_cur.notna() & np_cur.notna())
    components['P5_dLev_neg']    = (leverage_cur < leverage_prev).astype(float).where(
        leverage_cur.notna() & leverage_prev.notna())
    components['P6_dMargin_pos'] = (margin_cur > margin_prev).astype(float).where(
        margin_cur.notna() & margin_prev.notna())
    components['P7_dTurnover_pos'] = (turnover_cur > turnover_prev).astype(float).where(
        turnover_cur.notna() & turnover_prev.notna())

    n_computed = components.notna().sum(axis=1)
    n_passed   = components.fillna(0).sum(axis=1)
    frac       = n_passed / n_computed.replace(0, np.nan)

    # Ratio composite (level signals)
    ratios = pd.DataFrame(index=cur.index)
    ratios['ROCE']    = ebit_cur / (eq_cur + td_cur)
    ratios['IntCov']  = ebit_cur / int_cur
    ratios['DE']      = -(td_cur / eq_cur)        # sign-adjust: lower is better
    ratios['CashConv'] = cfo_cur / ebit_cur
    ratios['ROA']     = roa_cur
    ratios['NM']      = np_cur / rev_cur

    ratios_z = pd.DataFrame(index=ratios.index)
    for c in ratios.columns:
        ratios_z[c] = _zscore(_winsorize(ratios[c]))
    ratio_composite = ratios_z.mean(axis=1, skipna=True)

    out = pd.DataFrame({
        'piotroski_frac':   frac,
        'piotroski_n':      n_computed,
        'ratio_composite':  ratio_composite,
    })
    return out


def compute_pre_2014_components(wide, fy):
    """Pre-2014 era components — uses the era's richer current-items coverage."""
    cur = wide[wide['fiscal_year'] == fy].set_index('symbol')
    prev_raw = wide[wide['fiscal_year'] == fy - 1].set_index('symbol')
    prev = prev_raw.reindex(cur.index)

    def safe(d, c):
        if c not in d.columns:
            return pd.Series(dtype=float)
        return d[c]

    np_cur = safe(cur, 'net_profit')
    cfo_cur = safe(cur, 'cfo')
    eq_cur = safe(cur, 'equity')
    rev_cur = safe(cur, 'revenue')
    ca_cur = safe(cur, 'current_assets')
    cl_cur = safe(cur, 'current_liabilities')
    td_cur = safe(cur, 'total_debt')

    np_prev = safe(prev, 'net_profit')
    eq_prev = safe(prev, 'equity')
    rev_prev = safe(prev, 'revenue')
    ca_prev = safe(prev, 'current_assets')
    cl_prev = safe(prev, 'current_liabilities')
    td_prev = safe(prev, 'total_debt')

    roe_cur = np_cur / eq_cur
    roe_prev = np_prev / eq_prev
    margin_cur = np_cur / rev_cur
    margin_prev = np_prev / rev_prev
    cratio_cur = ca_cur / cl_cur
    cratio_prev = ca_prev / cl_prev
    de_cur = td_cur / eq_cur
    de_prev = td_prev / eq_prev

    components = pd.DataFrame(index=cur.index)
    components['Q1_NP_pos']      = (np_cur > 0).astype(float).where(np_cur.notna())
    components['Q2_CFO_pos']     = (cfo_cur > 0).astype(float).where(cfo_cur.notna())
    components['Q3_accruals']    = (cfo_cur > np_cur).astype(float).where(
        cfo_cur.notna() & np_cur.notna())
    components['Q4_ROE_pos']     = (roe_cur > 0).astype(float).where(roe_cur.notna())
    components['Q5_dROE_pos']    = (roe_cur > roe_prev).astype(float).where(
        roe_cur.notna() & roe_prev.notna())
    components['Q6_dMargin_pos'] = (margin_cur > margin_prev).astype(float).where(
        margin_cur.notna() & margin_prev.notna())
    components['Q7_dCR_pos']     = (cratio_cur > cratio_prev).astype(float).where(
        cratio_cur.notna() & cratio_prev.notna())
    components['Q8_dDE_neg']     = (de_cur < de_prev).astype(float).where(
        de_cur.notna() & de_prev.notna())

    n_computed = components.notna().sum(axis=1)
    n_passed   = components.fillna(0).sum(axis=1)
    frac       = n_passed / n_computed.replace(0, np.nan)

    # Ratio composite — what's available pre-2014
    ratios = pd.DataFrame(index=cur.index)
    ratios['ROE']        = roe_cur
    ratios['NM']         = margin_cur
    ratios['CurrRatio']  = cratio_cur
    ratios['CashConv']   = cfo_cur / np_cur

    ratios_z = pd.DataFrame(index=ratios.index)
    for c in ratios.columns:
        ratios_z[c] = _zscore(_winsorize(ratios[c]))
    ratio_composite = ratios_z.mean(axis=1, skipna=True)

    out = pd.DataFrame({
        'piotroski_frac':   frac,
        'piotroski_n':      n_computed,
        'ratio_composite':  ratio_composite,
    })
    return out


def score_one_date(wide, rebalance_date):
    """Build the score for a single rebalance date.
    Returns DataFrame with one row per stock in the eligible universe.
    """
    fy = latest_fy_at_date(rebalance_date)
    if fy is None:
        return pd.DataFrame()
    universe = load_universe_at(rebalance_date)
    universe = universe.set_index('symbol')

    era = 'post-2014' if fy >= ERA_BOUNDARY_FY else 'pre-2014'
    if era == 'post-2014':
        components = compute_post_2014_components(wide, fy)
    else:
        components = compute_pre_2014_components(wide, fy)

    # Restrict to the eligible universe for the date
    out = universe.join(components, how='left')
    # quality_score_raw = z(piotroski_frac) + z(ratio_composite)
    out['piotroski_z'] = _zscore(out['piotroski_frac'])
    out['ratio_z']     = _zscore(out['ratio_composite'])
    out['quality_score_raw'] = out['piotroski_z'] + out['ratio_z']
    # Cross-sectional percentile within the date's universe (0..1)
    out['quality_percentile'] = out['quality_score_raw'].rank(pct=True)
    out['rebalance_date']    = pd.Timestamp(rebalance_date)
    out['fiscal_year_used']  = fy
    out['era']               = era
    out['n_components_used'] = out['piotroski_n']
    out = out.reset_index().rename(columns={'index': 'symbol'})
    return out


def run_all():
    print(f"Loading panel from {PANEL_PATH}...")
    df = load_panel()
    print(f"  Trusted rows: {len(df):,}, stocks: {df['symbol'].nunique()}")

    wide = wide_fundamentals(df)
    print(f"  Wide fundamentals: {wide.shape}")

    u = pd.read_parquet(UNIVERSE_PATH)
    rebalance_dates = sorted(pd.to_datetime(u['rebalance_date']).unique())
    print(f"  Rebalance dates: {len(rebalance_dates)} "
          f"({rebalance_dates[0].date()} → {rebalance_dates[-1].date()})")

    all_scores = []
    for rd in rebalance_dates:
        scores = score_one_date(wide, rd)
        if not scores.empty:
            all_scores.append(scores)
            era = scores['era'].iloc[0]
            n_scored = scores['quality_score_raw'].notna().sum()
            print(f"  {rd.strftime('%Y-%m-%d')}  era={era}  "
                  f"universe={len(scores)}  scored={n_scored}  "
                  f"fy_used={scores['fiscal_year_used'].iloc[0]}")
    if not all_scores:
        print("ERROR: no scores produced")
        return None

    result = pd.concat(all_scores, ignore_index=True)
    result.to_parquet(SCORES_PARQUET, index=False)
    print(f"\n→ wrote {SCORES_PARQUET}")
    print(f"  Rows: {len(result):,}")
    print(f"  Avg coverage: {result['quality_score_raw'].notna().mean()*100:.1f}%")
    print(f"  Era breakdown:")
    print(result.groupby('era').agg(
        n=('symbol', 'size'),
        scored=('quality_score_raw', lambda x: x.notna().sum()),
        avg_components=('n_components_used', 'mean')).to_string())
    return result


if __name__ == '__main__':
    run_all()

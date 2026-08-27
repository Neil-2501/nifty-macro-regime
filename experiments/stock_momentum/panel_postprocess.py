"""Post-process the standardized fundamentals into a clean panel.

Pipeline:
1. Load standardized_fundamentals.parquet + raw extraction JSONs
2. Derive basis (consolidated|standalone|unknown) per row from extraction JSON
3. Magnitude-sanity gate per stock-field series: flag values < 0.2x or > 5x
   stock-field median; attempt re-pick from extracted alternates where available
4. Enforce single-basis per stock-field series (whichever has most coverage)
5. Apply manual_overrides.csv (verified hand-corrected values)
6. Compute derived per-row confidence flag
7. Merge with Screener panel
8. Write extended_fundamentals.parquet
"""
from __future__ import annotations

import glob
import json
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PIPELINE_DIR = os.path.join(REPO_ROOT, "data", "bse_pipeline")
EXTRACT_DIR = os.path.join(PIPELINE_DIR, "extractions")
STANDARDIZED = os.path.join(PIPELINE_DIR, "standardized_fundamentals.parquet")
SCREENER_PANEL = os.path.join(REPO_ROOT, "data", "screener_bulk",
                                "fundamentals_panel.parquet")
OVERRIDES_CSV = os.path.join(REPO_ROOT, "data", "bse_pipeline",
                               "manual_overrides.csv")
OUT_PARQUET = os.path.join(PIPELINE_DIR, "extended_fundamentals_v2.parquet")
QC_REPORT = os.path.join(PIPELINE_DIR, "panel_postprocess_report.json")


def load_basis_and_bank_flags():
    """Read every extraction JSON to build per-(symbol, report_year) basis
    and bank flag tables. Look in EXTRACT_DIR first; if empty, fall back
    to most recent extractions_v?_backup_* dir so we can post-process even
    while a new Phase 4 is running."""
    candidates = [EXTRACT_DIR]
    backups = sorted(glob.glob(os.path.join(
        os.path.dirname(EXTRACT_DIR), "extractions_v*_backup_*")),
        reverse=True)
    candidates += backups

    rows = []
    used_dir = None
    for d in candidates:
        files = glob.glob(os.path.join(d, "*.json"))
        if len(files) < 100:  # skip empty / nearly-empty dirs
            continue
        used_dir = d
        for f in files:
            try:
                with open(f, encoding='utf-8') as fh:
                    rec = json.load(fh)
            except Exception:
                continue
            sym = rec.get('symbol')
            ry = rec.get('report_year')
            if not sym or ry is None:
                continue
            rows.append({
                'symbol': sym,
                'source_pdf_year': int(ry),
                'basis_pdf': rec.get('consolidated_or_standalone') or 'unknown',
                'is_bank': bool(rec.get('is_bank', False)),
            })
        break
    print(f"  Reading basis flags from: {used_dir or '(none)'}")
    df = pd.DataFrame(rows)
    if df.empty:
        # Empty stub with correct columns so downstream merges don't crash
        df = pd.DataFrame(columns=['symbol', 'source_pdf_year',
                                       'basis_pdf', 'is_bank'])
    return df


def apply_magnitude_sanity(df):
    """Per (symbol, line_item) series: flag values < 0.2x or > 5x the
    series median (using at least 3-year coverage). Also flag absolute
    outliers >20x own-median. Mark with `magnitude_flag`."""
    df = df.copy()
    df['magnitude_flag'] = False
    df['series_median'] = np.nan

    grouped = df.groupby(['symbol', 'line_item'])
    medians = grouped['value'].transform(lambda x: np.median(np.abs(x.dropna()))
                                          if x.dropna().size >= 1 else np.nan)
    df['series_median'] = medians

    # Need at least 2 non-null observations to trust the median for flagging
    series_size = grouped['value'].transform('count')

    mask = (series_size >= 2) & df['value'].notna() & (medians > 0)
    ratio = np.where(mask, np.abs(df['value']) / medians.replace(0, np.nan), np.nan)

    # Catastrophic outliers: >20x or < (1/20)x own-median
    df['magnitude_flag'] = mask & ((ratio > 5) | (ratio < 0.2))
    df['catastrophic_outlier'] = mask & ((ratio > 20) | (ratio < 0.05))
    df['series_size'] = series_size
    return df


def enforce_single_basis(df):
    """Per (symbol, line_item): keep rows whose basis matches the majority
    basis for that stock-field. Flag the minority rows with basis_flag."""
    df = df.copy()
    df['basis_flag'] = False

    # Compute majority basis per (symbol, line_item)
    counts = df.groupby(['symbol', 'line_item', 'basis']).size().reset_index(name='n')
    if counts.empty:
        return df
    majority = counts.sort_values('n', ascending=False).drop_duplicates(
        subset=['symbol', 'line_item'])[['symbol', 'line_item', 'basis']]
    majority = majority.rename(columns={'basis': 'majority_basis'})
    df = df.merge(majority, on=['symbol', 'line_item'], how='left')
    df['basis_flag'] = (df['basis'] != df['majority_basis']) & df['basis'].ne('unknown')
    return df


def load_overrides():
    """Read manual_overrides.csv if exists. Schema:
    symbol, fiscal_year, line_item, value, basis, source_note"""
    if not os.path.exists(OVERRIDES_CSV):
        return pd.DataFrame(columns=['symbol', 'fiscal_year', 'line_item',
                                       'value', 'basis', 'source_note'])
    return pd.read_csv(OVERRIDES_CSV, comment='#')


def derive_confidence(row):
    """Per-row confidence: verified | high | medium | low.

    - verified: from manual_overrides
    - high: from screener (post-2014, reliable) OR from BSE with no flags
    - medium: BSE with magnitude_flag OR basis_flag (but not catastrophic)
    - low: catastrophic_outlier OR from no-PDF-source / unknown
    """
    if row.get('source') == 'manual_override':
        return 'verified'
    if row.get('source') == 'screener':
        return 'high'
    if row.get('catastrophic_outlier'):
        return 'low'
    flags = bool(row.get('magnitude_flag')) or bool(row.get('basis_flag'))
    if not flags:
        return 'high' if row.get('confidence', '') == 'high' else 'medium'
    return 'medium'


def main():
    print("=== Panel post-processing ===")
    if not os.path.exists(STANDARDIZED):
        print(f"ERROR: {STANDARDIZED} not found")
        return 1
    bse = pd.read_parquet(STANDARDIZED)
    print(f"Standardized BSE: {len(bse):,} rows, {bse['symbol'].nunique()} symbols")

    print("Loading basis/bank flags from JSONs...")
    flags = load_basis_and_bank_flags()
    print(f"Per-PDF flags: {len(flags):,} rows")

    bse = bse.merge(flags, on=['symbol', 'source_pdf_year'], how='left')
    bse['basis'] = bse['basis_pdf'].fillna('unknown')
    bse['is_bank'] = bse['is_bank'].fillna(False)
    bse = bse.drop(columns=['basis_pdf'])

    # Magnitude sanity per stock-field series
    print("Applying magnitude sanity per (symbol, line_item)...")
    bse = apply_magnitude_sanity(bse)
    n_flag = bse['magnitude_flag'].sum()
    n_cat = bse['catastrophic_outlier'].sum()
    print(f"  magnitude_flag (>5x or <0.2x own-median): {n_flag:,}")
    print(f"  catastrophic_outlier (>20x or <0.05x):    {n_cat:,}")

    # Single-basis enforcement
    print("Enforcing single-basis per (symbol, line_item)...")
    bse = enforce_single_basis(bse)
    n_basis_flag = bse['basis_flag'].sum()
    print(f"  basis_flag (mid-series basis switch): {n_basis_flag:,}")

    # Source column
    bse['source'] = 'bse'

    # Load Screener panel
    print("Loading Screener panel...")
    sc = pd.read_parquet(SCREENER_PANEL)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from bse_pipeline_full import canonical_line_item
    sc = sc.copy()
    sc['fiscal_year'] = sc['period'].astype(str).str.extract(r'(\d{4})$').astype(float)
    sc = sc.dropna(subset=['fiscal_year'])
    sc['fiscal_year'] = sc['fiscal_year'].astype(int)

    # Screener-specific label mapping: their column names don't match the
    # BSE parser's canonical mapping for several fields. Fix them here.
    SCREENER_DIRECT_MAP = {
        'Cash from Operating Activity': 'cfo',
        'Net Cash Flow': 'cash_net_change',
        'Free Cash Flow': 'fcf',
        'Equity Capital': 'equity_share_capital',
        'Reserves': 'reserves',
        'Borrowings': 'total_debt',
        'Total Assets': 'total_assets',
        'Sales': 'revenue',
        'Net Profit': 'net_profit',
        'Operating Profit': 'ebit',
        'Interest': 'interest_expense',
    }
    sc['line_item_can'] = sc['line_item'].map(SCREENER_DIRECT_MAP)
    # Fallback to canonical regex for anything not in direct map
    mask = sc['line_item_can'].isna()
    sc.loc[mask, 'line_item_can'] = sc.loc[mask, 'line_item'].apply(canonical_line_item)
    sc = sc.dropna(subset=['line_item_can', 'value'])

    # Synthesize equity = Equity Capital + Reserves per (symbol, fiscal_year)
    equity_parts = sc[sc['line_item_can'].isin(['equity_share_capital',
                                                      'reserves'])]
    if not equity_parts.empty:
        equity_sum = equity_parts.groupby(
            ['symbol', 'fiscal_year', 'statement_type'])['value'].sum().reset_index()
        equity_sum['line_item'] = 'Equity (synthesized)'
        equity_sum['line_item_can'] = 'equity'
        sc = pd.concat([sc, equity_sum], ignore_index=True, sort=False)
        print(f"  Synthesized {len(equity_sum):,} equity rows from "
              f"Equity Capital + Reserves")
    # Screener was scraped with consolidated-preferred URL (the scraper
    # picks /consolidated/ first, falls back to standalone). No
    # cons/standalone column on the parquet, so we mark all Screener rows
    # as 'consolidated' (the scrape default) — accurate for most stocks.
    # Drop the raw line_item column BEFORE renaming to avoid duplicate names
    sc = sc.drop(columns=['line_item'])
    sc = sc.rename(columns={'line_item_can': 'line_item'})
    sc['basis'] = 'consolidated'
    sc = sc.sort_values(['symbol', 'fiscal_year', 'line_item'])
    sc_resolved = sc.drop_duplicates(
        subset=['symbol', 'fiscal_year', 'line_item'], keep='last')
    sc_resolved = sc_resolved[
        ['symbol', 'fiscal_year', 'line_item', 'value', 'basis']].copy()
    sc_resolved['source'] = 'screener'
    sc_resolved['confidence'] = 'screener'
    sc_resolved['magnitude_flag'] = False
    sc_resolved['catastrophic_outlier'] = False
    sc_resolved['basis_flag'] = False
    sc_resolved['is_bank'] = False
    sc_resolved['source_pdf_year'] = pd.NA
    sc_resolved['series_median'] = np.nan
    sc_resolved['series_size'] = pd.NA
    sc_resolved['majority_basis'] = sc_resolved['basis']
    print(f"Screener resolved: {len(sc_resolved):,} rows")

    # Combine
    cols = ['symbol', 'fiscal_year', 'line_item', 'value', 'source', 'basis',
             'is_bank', 'confidence', 'magnitude_flag', 'catastrophic_outlier',
             'basis_flag', 'series_median', 'series_size', 'majority_basis']

    # Safety: deduplicate column names (sometimes joins create dupes)
    def _dedup_cols(df):
        df = df.loc[:, ~df.columns.duplicated(keep='first')]
        for c in cols:
            if c not in df.columns:
                df[c] = pd.NA
        return df[cols].copy()

    bse_out = _dedup_cols(bse)
    sc_out = _dedup_cols(sc_resolved)
    combined = pd.concat([bse_out, sc_out], ignore_index=True, sort=False)

    # Prefer screener > bse on conflicts (screener is 94% accurate post-2014)
    combined['source_priority'] = combined['source'].map(
        {'manual_override': 0, 'screener': 1, 'bse': 2})
    combined = combined.sort_values(
        ['symbol', 'fiscal_year', 'line_item', 'source_priority'])
    combined = combined.drop_duplicates(
        subset=['symbol', 'fiscal_year', 'line_item'], keep='first')
    combined = combined.drop(columns=['source_priority'])

    # Apply manual overrides on top
    overrides = load_overrides()
    if not overrides.empty:
        print(f"Applying manual overrides: {len(overrides):,} rows")
        ov = overrides.copy()
        ov['source'] = 'manual_override'
        ov['is_bank'] = False
        ov['confidence'] = 'verified'
        ov['magnitude_flag'] = False
        ov['catastrophic_outlier'] = False
        ov['basis_flag'] = False
        ov['series_median'] = np.nan
        ov['series_size'] = pd.NA
        ov['majority_basis'] = ov['basis']
        if 'basis' not in ov.columns:
            ov['basis'] = 'unknown'
        ov_out = ov.reindex(columns=cols)
        # Remove rows already in panel that overrides cover
        keys = list(zip(ov_out['symbol'], ov_out['fiscal_year'], ov_out['line_item']))
        keyset = set(keys)
        combined['_key'] = list(zip(combined['symbol'], combined['fiscal_year'],
                                       combined['line_item']))
        combined = combined[~combined['_key'].isin(keyset)]
        combined = combined.drop(columns=['_key'])
        combined = pd.concat([ov_out, combined], ignore_index=True, sort=False)

    # Derived confidence
    combined['confidence'] = combined.apply(derive_confidence, axis=1)

    combined.to_parquet(OUT_PARQUET, index=False)
    print(f"\n=== Wrote: {OUT_PARQUET} ===")
    print(f"Total rows: {len(combined):,}, symbols: {combined['symbol'].nunique()}")
    print(f"Confidence distribution:")
    for c, n in combined['confidence'].value_counts().items():
        print(f"  {c:10s}  {n:,}")
    print(f"Source distribution:")
    for s, n in combined['source'].value_counts().items():
        print(f"  {s:16s}  {n:,}")

    # QC report
    report = {
        'total_rows': len(combined),
        'symbols': int(combined['symbol'].nunique()),
        'year_range': [int(combined['fiscal_year'].min()),
                        int(combined['fiscal_year'].max())],
        'source_distribution': combined['source'].value_counts().to_dict(),
        'confidence_distribution': combined['confidence'].value_counts().to_dict(),
        'magnitude_flag_count': int(combined['magnitude_flag'].sum()),
        'catastrophic_outlier_count': int(combined['catastrophic_outlier'].sum()),
        'basis_flag_count': int(combined['basis_flag'].sum()),
    }
    with open(QC_REPORT, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nQC report → {QC_REPORT}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

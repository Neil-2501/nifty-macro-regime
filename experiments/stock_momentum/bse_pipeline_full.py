#!/usr/bin/env python3
"""
bse_pipeline_full.py — Complete BSE annual report → fundamentals pipeline.

Multi-day pipeline:
  Phase 0  NSE → BSE scrip code mapping via ISIN
  Phase 1  Fetch all annual report listings
  Phase 2  Select target PDFs per stock (5 per stock ≈ 10 years)
  Phase 3  Bulk PDF download (resumable, ~5-7h unattended)
  Phase 4  Detailed statement extraction from each PDF
  Phase 5  Cross-stock standardization
  Phase 6  Validate vs Screener
  Phase 7  Build extended fundamentals panel

Run as:
  python bse_pipeline_full.py --phase 0
  python bse_pipeline_full.py --phase 0,1,2
  python bse_pipeline_full.py --phase all

Every phase is resumable — re-running skips items already on disk.

Bracket notation throughout (df['column']).
"""

import os
import sys
import time
import json
import re
import glob
import signal
import argparse
import traceback
from typing import Optional

import pandas as pd
import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PIPELINE_DIR = os.path.join(REPO_ROOT, "data", "bse_pipeline")
LISTINGS_DIR = os.path.join(PIPELINE_DIR, "annual_report_listings")
PDFS_DIR = os.path.join(PIPELINE_DIR, "pdfs")
EXTRACT_DIR = os.path.join(PIPELINE_DIR, "extractions")
RESULTS_DIR = os.path.join(REPO_ROOT, "results")

UNIVERSE_PATH = os.path.join(REPO_ROOT, "data", "stock_universe",
                              "nifty500_pointintime.parquet")
BHAVCOPY_ROOT = os.path.join(REPO_ROOT, "data", "bhavcopy")
SCREENER_PANEL = os.path.join(REPO_ROOT, "data", "screener_bulk",
                               "fundamentals_panel.parquet")

ISIN_LOOKUP_CSV = os.path.join(PIPELINE_DIR, "nse_isin_lookup.csv")
BSE_MASTER_CSV = os.path.join(PIPELINE_DIR, "bse_master_list.csv")
MAPPING_CSV = os.path.join(PIPELINE_DIR, "nse_bse_mapping.csv")
SELECTION_CSV = os.path.join(PIPELINE_DIR, "pdf_selection_plan.csv")
STANDARDIZED_PARQUET = os.path.join(PIPELINE_DIR, "standardized_fundamentals.parquet")
EXTENDED_PARQUET = os.path.join(PIPELINE_DIR, "extended_fundamentals.parquet")
VALIDATION_CSV = os.path.join(PIPELINE_DIR, "validation_report.csv")
MANUAL_REVIEW_CSV = os.path.join(PIPELINE_DIR, "manual_review_queue.csv")
LOG_PATH = os.path.join(RESULTS_DIR, "bse_pipeline_full.txt")

os.makedirs(PIPELINE_DIR, exist_ok=True)
os.makedirs(LISTINGS_DIR, exist_ok=True)
os.makedirs(PDFS_DIR, exist_ok=True)
os.makedirs(EXTRACT_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
HDRS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 '
                    'Safari/537.36'),
    'Referer': 'https://www.bseindia.com/',
    'Accept': 'application/json, text/plain, */*',
}
TIMEOUT_SEC = 25
LISTING_SLEEP = 1.5
DOWNLOAD_SLEEP = 2.0
MASTER_SLEEP = 3.0
RETRY_ON_5XX_NETWORK = [10, 30]

# Target fiscal years to download — each AR covers self + prior year
TARGET_FY_YEARS = [2014, 2012, 2010, 2008, 2006]

# Spot-check expected mappings (used by Phase 0 verify)
KNOWN_MAPPINGS = {
    'RELIANCE': '500325', 'TCS': '532540', 'HDFCBANK': '500180',
    'ITC': '500875', 'INFY': '500209', 'SATYAMCOMP': '500376',
    'DHFL': '511072', 'LT': '500510', 'WIPRO': '507685',
    'HINDUNILVR': '500696',
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_file = None


def open_log(append: bool = True) -> None:
    global _log_file
    mode = "a" if append else "w"
    _log_file = open(LOG_PATH, mode, encoding="utf-8", buffering=1)


def close_log() -> None:
    global _log_file
    if _log_file:
        _log_file.close()
        _log_file = None


def p(text: str = "") -> None:
    print(text, flush=True)
    if _log_file:
        _log_file.write(text + "\n")


def flush_log() -> None:
    if _log_file:
        _log_file.flush()
        try:
            os.fsync(_log_file.fileno())
        except OSError:
            pass


def ts() -> str:
    return pd.Timestamp.now().strftime("%H:%M:%S")


def fmt_eta(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds/60:.1f}m"
    return f"{seconds/3600:.1f}h"


def section(title: str) -> None:
    p()
    p("=" * 80)
    p(f"  {title}")
    p("=" * 80)


# ---------------------------------------------------------------------------
# Signal handlers
# ---------------------------------------------------------------------------
_should_stop = False


def signal_handler(signum, frame):
    global _should_stop
    _should_stop = True
    p(f"\n[{ts()}] Caught signal {signum} — will exit after current item")
    flush_log()


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def get_json(url: str, retries: int = 2) -> tuple[Optional[object], int, str]:
    last_err = ""
    last_status = 0
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HDRS, timeout=TIMEOUT_SEC)
            last_status = r.status_code
            if r.status_code == 200:
                body = r.text
                try:
                    return r.json(), 200, ""
                except Exception:
                    m = re.search(r'(\{.*\}|\[.*\])', body, re.DOTALL)
                    if m:
                        try:
                            return json.loads(m.group(1)), 200, ""
                        except Exception:
                            pass
                    last_err = "non-JSON body"
                    break
            elif 500 <= r.status_code < 600 and attempt < retries:
                time.sleep(RETRY_ON_5XX_NETWORK[min(attempt, len(RETRY_ON_5XX_NETWORK) - 1)])
                continue
            else:
                last_err = f"HTTP {r.status_code}"
                break
        except (requests.Timeout, requests.ConnectionError) as e:
            last_err = f"{type(e).__name__}"
            if attempt < retries:
                time.sleep(RETRY_ON_5XX_NETWORK[min(attempt, len(RETRY_ON_5XX_NETWORK) - 1)])
                continue
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
            break
    return None, last_status, last_err


def get_binary(url: str, retries: int = 1) -> tuple[Optional[bytes], int, str]:
    last_err = ""
    last_status = 0
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, headers=HDRS, timeout=TIMEOUT_SEC)
            last_status = r.status_code
            if r.status_code == 200:
                return r.content, 200, ""
            elif 500 <= r.status_code < 600 and attempt < retries:
                time.sleep(10)
                continue
            else:
                last_err = f"HTTP {r.status_code}"
                break
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:100]}"
            if attempt < retries:
                time.sleep(10)
                continue
            break
    return None, last_status, last_err


# ===========================================================================
# PHASE 0 — NSE → BSE MAPPING
# ===========================================================================
def phase_0_extract_isins() -> pd.DataFrame:
    """Extract most recent ISIN per universe symbol from bhavcopy data."""
    p(f"\n  [{ts()}] Phase 0a: extracting ISINs from bhavcopy archive ...")
    u = pd.read_parquet(UNIVERSE_PATH)
    if 'included' in u.columns:
        u = u[u['included']]
    universe_syms = set(u['symbol'].dropna().unique())
    p(f"    Universe symbols: {len(universe_syms):,}")

    # Walk bhavcopy from most recent year backward; take first non-empty ISIN
    isin_map: dict[str, str] = {}
    bhav_files = sorted(glob.glob(os.path.join(BHAVCOPY_ROOT, '*', '*.parquet')),
                         reverse=True)  # newest first

    for f in bhav_files:
        if not universe_syms:
            break
        try:
            df = pd.read_parquet(f, columns=['symbol', 'series', 'isin'])
        except Exception:
            try:
                df = pd.read_parquet(f)
            except Exception:
                continue
        # Filter to universe-only and EQ series
        if 'series' in df.columns:
            df = df[df['series'] == 'EQ']
        df = df[df['symbol'].isin(universe_syms)]
        if 'isin' in df.columns:
            df = df[df['isin'].notna() & (df['isin'].astype(str).str.len() > 0)]
            for sym, isin in zip(df['symbol'], df['isin']):
                sym = str(sym)
                isin = str(isin).strip()
                if sym in universe_syms and isin and sym not in isin_map:
                    isin_map[sym] = isin
                    universe_syms.discard(sym)

    out = pd.DataFrame({'symbol': list(isin_map.keys()),
                         'isin': list(isin_map.values())})
    out.to_csv(ISIN_LOOKUP_CSV, index=False)
    p(f"    ISINs found: {len(out):,} / {pd.read_parquet(UNIVERSE_PATH)['symbol'].nunique():,}")
    if universe_syms:
        p(f"    No ISIN found for: {len(universe_syms)} symbols "
          f"(sample: {sorted(list(universe_syms))[:8]})")
    p(f"    ISIN lookup → {ISIN_LOOKUP_CSV}")
    return out


def phase_0_fetch_bse_master() -> pd.DataFrame:
    """Download BSE equity master list (active + delisted)."""
    p(f"\n  [{ts()}] Phase 0b: fetching BSE equity master list ...")
    parts = []
    for status_filter in ('Active', 'Delisted'):
        url = (f"https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"
               f"?Group=&Scripcode=&industry=&Segment=Equity&Status={status_filter}")
        p(f"    Fetching {status_filter} list ...")
        time.sleep(MASTER_SLEEP)
        data, status, err = get_json(url, retries=2)
        if data is None:
            p(f"      ❌ HTTP {status}  {err}")
            continue
        if isinstance(data, dict):
            # The endpoint sometimes wraps data; locate any list inside
            list_val = None
            for k, v in data.items():
                if isinstance(v, list):
                    list_val = v
                    break
            data = list_val or []
        if not isinstance(data, list):
            p(f"      ⚠️ response not a list (type={type(data).__name__})")
            continue
        p(f"      received {len(data):,} entries")
        df = pd.DataFrame(data)
        df['_source_status'] = status_filter
        parts.append(df)

    if not parts:
        p(f"    ⚠️ no BSE master data fetched")
        return pd.DataFrame()

    master = pd.concat(parts, ignore_index=True)
    # Normalize column names — BSE returns: SCRIP_CD, Scrip_Name, ISIN_NUMBER,
    # scrip_id, Status, GROUP, etc. Match by uppercased name.
    rename_map = {}
    for c in master.columns:
        cu = c.upper()
        if cu in ('SCRIP_CD', 'SCRIP_CODE', 'SCRIPCODE', 'SC_CODE'):
            rename_map[c] = 'bse_code'
        elif cu in ('SCRIP_ID', 'SYMBOL', 'SC_ID'):
            rename_map[c] = 'bse_symbol'
        elif cu in ('SCRIP_NAME', 'COMPANY_NAME', 'COMPANYNAME', 'SC_NAME',
                     'ISSUER_NAME'):
            # Prefer Scrip_Name; only set if not already mapped to company_name
            if 'company_name' not in rename_map.values():
                rename_map[c] = 'company_name'
        elif cu in ('ISIN_NUMBER', 'ISIN'):
            rename_map[c] = 'isin'
        elif cu in ('STATUS', 'STATUS_FLAG'):
            rename_map[c] = 'status_native'
    master = master.rename(columns=rename_map)
    keep = [c for c in ('bse_code', 'bse_symbol', 'company_name', 'isin',
                          'status_native', '_source_status') if c in master.columns]
    master = master[keep].copy()
    # Cast bse_code to string for joining
    if 'bse_code' in master.columns:
        master['bse_code'] = master['bse_code'].astype(str).str.strip()
    if 'isin' in master.columns:
        master['isin'] = master['isin'].astype(str).str.strip()
    master = master.drop_duplicates(subset=['bse_code'])
    master.to_csv(BSE_MASTER_CSV, index=False)
    p(f"    BSE master → {BSE_MASTER_CSV}  ({len(master):,} entries)")
    return master


def _normalize_name(s: str) -> str:
    s = str(s or '').upper()
    s = re.sub(r'[^A-Z0-9 ]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    # Strip common suffixes
    for suf in (' LIMITED', ' LTD', ' INDIA', ' INDIA LIMITED', ' INDIA LTD',
                 ' COMPANY', ' CO', ' THE'):
        if s.endswith(suf):
            s = s[: -len(suf)].strip()
    return s


def phase_0_join(isin_df: pd.DataFrame, master_df: pd.DataFrame) -> pd.DataFrame:
    """Join NSE universe → BSE codes via ISIN, then fuzzy name fallback."""
    p(f"\n  [{ts()}] Phase 0c: joining universe to BSE ...")

    u = pd.read_parquet(UNIVERSE_PATH)
    if 'included' in u.columns:
        u = u[u['included']]
    syms = sorted(u['symbol'].dropna().unique())
    p(f"    Universe symbols: {len(syms):,}")

    # ISIN-based primary join
    isin_to_bse = {}
    if not master_df.empty and 'isin' in master_df.columns:
        m = master_df[master_df['isin'].astype(str).str.len() > 0]
        # Some ISINs map to multiple bse_codes (split shares, DVR); prefer Active
        active = m[m['_source_status'] == 'Active']
        delisted = m[m['_source_status'] == 'Delisted']
        for _, r in active.iterrows():
            isin = r['isin']
            if isin not in isin_to_bse:
                isin_to_bse[isin] = (r['bse_code'], r.get('company_name', ''),
                                       'Active')
        for _, r in delisted.iterrows():
            isin = r['isin']
            if isin not in isin_to_bse:
                isin_to_bse[isin] = (r['bse_code'], r.get('company_name', ''),
                                       'Delisted')

    isin_lookup = dict(zip(isin_df['symbol'], isin_df['isin']))

    rows = []
    for sym in syms:
        isin = isin_lookup.get(sym)
        rec = {'symbol': sym, 'isin': isin, 'bse_code': None,
               'company_name': '', 'bse_status': '', 'match_method': ''}
        if isin and isin in isin_to_bse:
            bcode, cname, status = isin_to_bse[isin]
            rec['bse_code'] = bcode
            rec['company_name'] = cname
            rec['bse_status'] = status
            rec['match_method'] = 'isin'
        rows.append(rec)

    mapping_df = pd.DataFrame(rows)
    n_isin = (mapping_df['match_method'] == 'isin').sum()
    p(f"    ISIN-matched: {n_isin:,} / {len(mapping_df):,}")

    # Fuzzy-name fallback: try to match company name vs BSE master
    unmapped = mapping_df['bse_code'].isna()
    if not master_df.empty and unmapped.any():
        # Build normalized-name → bse_code map
        master_named = master_df.copy()
        master_named['_norm'] = master_named['company_name'].apply(_normalize_name)
        norm_to_code = dict(zip(master_named['_norm'], master_named['bse_code']))
        n_fuzzy = 0
        for idx in mapping_df[unmapped].index:
            sym = mapping_df.loc[idx, 'symbol']
            # First try: NSE symbol itself as a candidate normalized name
            cand = _normalize_name(sym)
            if cand and cand in norm_to_code:
                mapping_df.loc[idx, 'bse_code'] = norm_to_code[cand]
                mapping_df.loc[idx, 'match_method'] = 'name_exact'
                n_fuzzy += 1
        if n_fuzzy:
            p(f"    Name-exact-matched: {n_fuzzy}")

    final_mapped = mapping_df['bse_code'].notna().sum()
    p(f"    Total mapped: {final_mapped:,} / {len(mapping_df):,} "
      f"({final_mapped/len(mapping_df)*100:.1f}%)")

    mapping_df.to_csv(MAPPING_CSV, index=False)
    p(f"    Mapping → {MAPPING_CSV}")
    return mapping_df


def phase_0_verify(mapping_df: pd.DataFrame) -> None:
    p(f"\n  [{ts()}] Phase 0d: verifying mappings against known truth ...")
    n_correct, n_wrong, n_missing = 0, 0, 0
    for sym, expected in KNOWN_MAPPINGS.items():
        row = mapping_df[mapping_df['symbol'] == sym]
        if not len(row):
            p(f"    {sym}: NOT IN UNIVERSE (skipped)")
            continue
        got = row.iloc[0].get('bse_code')
        if got is None or (isinstance(got, float) and pd.isna(got)):
            n_missing += 1
            p(f"    {sym}: ❌ NO MAPPING (expected {expected})")
        elif str(got).strip() == str(expected):
            n_correct += 1
            p(f"    {sym}: ✓ {got}")
        else:
            n_wrong += 1
            p(f"    {sym}: ⚠️ got {got}, expected {expected}")
    p(f"\n    Spot-check verdict: {n_correct} correct, "
      f"{n_wrong} wrong, {n_missing} missing")


def phase_0() -> None:
    section("PHASE 0 — NSE → BSE MAPPING")
    if os.path.exists(MAPPING_CSV):
        p(f"  [skip] {MAPPING_CSV} exists — loading existing mapping")
        mapping_df = pd.read_csv(MAPPING_CSV)
    else:
        isin_df = (pd.read_csv(ISIN_LOOKUP_CSV)
                   if os.path.exists(ISIN_LOOKUP_CSV)
                   else phase_0_extract_isins())
        master_df = (pd.read_csv(BSE_MASTER_CSV)
                     if os.path.exists(BSE_MASTER_CSV)
                     else phase_0_fetch_bse_master())
        if master_df.empty:
            p(f"  ❌ BSE master fetch returned empty — cannot proceed")
            return
        mapping_df = phase_0_join(isin_df, master_df)
    phase_0_verify(mapping_df)
    p(f"\n  Phase 0 done.")


# ===========================================================================
# PHASE 1 — AR LISTINGS
# ===========================================================================
def phase_1() -> None:
    section("PHASE 1 — FETCH ALL ANNUAL REPORT LISTINGS")
    if not os.path.exists(MAPPING_CSV):
        p(f"  ❌ {MAPPING_CSV} missing — run Phase 0 first")
        return
    mapping_df = pd.read_csv(MAPPING_CSV)
    mapped = mapping_df[mapping_df['bse_code'].notna()].copy()
    mapped['bse_code'] = mapped['bse_code'].astype(str).str.replace(r'\.0$', '', regex=True)
    syms = mapped['symbol'].tolist()
    codes = dict(zip(mapped['symbol'], mapped['bse_code']))

    to_fetch = []
    for sym in syms:
        path = os.path.join(LISTINGS_DIR, f"{sym}.json")
        if not os.path.exists(path):
            to_fetch.append(sym)

    p(f"  Mapped symbols: {len(syms):,}")
    p(f"  Already on disk: {len(syms) - len(to_fetch):,}")
    p(f"  To fetch: {len(to_fetch):,}")
    p(f"  Estimated time: {fmt_eta(len(to_fetch) * LISTING_SLEEP)}")

    n_ok, n_empty, n_fail = 0, 0, 0
    t_loop = time.time()
    for i, sym in enumerate(to_fetch, 1):
        if _should_stop:
            p(f"  [{ts()}] Stopping at user request after {i - 1}")
            break
        code = codes[sym]
        url = (f"https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w"
               f"?scripcode={code}")
        time.sleep(LISTING_SLEEP)
        data, status, err = get_json(url, retries=2)
        out_path = os.path.join(LISTINGS_DIR, f"{sym}.json")
        if data is None:
            n_fail += 1
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump({'_error': err, '_status': status}, f)
        else:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, default=str)
            rows = data.get('Table') if isinstance(data, dict) else []
            if isinstance(rows, list) and rows:
                n_ok += 1
            else:
                n_empty += 1

        if i % 50 == 0 or i == len(to_fetch):
            elapsed = time.time() - t_loop
            rate = elapsed / i
            remaining = (len(to_fetch) - i) * rate
            p(f"  [{ts()}] {i}/{len(to_fetch)}  ok={n_ok} empty={n_empty} "
              f"fail={n_fail}  ETA ~{fmt_eta(remaining)}")
            flush_log()

    p(f"\n  Phase 1 done.  total ok={n_ok} empty={n_empty} fail={n_fail}")


# ===========================================================================
# PHASE 2 — SELECT TARGET PDFS
# ===========================================================================
def phase_2() -> None:
    section("PHASE 2 — SELECT TARGET PDFS PER STOCK")
    if not os.path.exists(MAPPING_CSV):
        p(f"  ❌ {MAPPING_CSV} missing — run Phase 0 first")
        return
    mapping_df = pd.read_csv(MAPPING_CSV)
    mapped = mapping_df[mapping_df['bse_code'].notna()].copy()
    mapped['bse_code'] = mapped['bse_code'].astype(str).str.replace(r'\.0$', '', regex=True)

    rows = []
    p(f"  Selecting up to {len(TARGET_FY_YEARS)} PDFs per stock for "
      f"{len(mapped):,} mapped stocks...")
    for sym in mapped['symbol']:
        path = os.path.join(LISTINGS_DIR, f"{sym}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        table = data.get('Table') or []
        if not table:
            continue
        # Build {year_int: pdf_url} map
        available = {}
        for r in table:
            try:
                y = int(r.get('Year') or 0)
            except (TypeError, ValueError):
                continue
            url = r.get('PDFDownload') or ''
            if y > 0 and url:
                available[y] = url

        if not available:
            continue
        years_sorted = sorted(available.keys())

        # Selection logic — nearest available to each target FY
        selected = {}
        for target in TARGET_FY_YEARS:
            # Pick nearest available year
            nearest = min(years_sorted, key=lambda y: abs(y - target))
            if nearest not in selected:
                selected[nearest] = ('target', target)

        # Always include the latest AR (post-2018 if available) for cross-validation
        latest = max(years_sorted)
        if latest not in selected and latest >= 2018:
            selected[latest] = ('latest', latest)

        bse_code = mapped[mapped['symbol'] == sym]['bse_code'].iloc[0]
        for y, (reason, target) in selected.items():
            rows.append({
                'symbol': sym, 'bse_code': bse_code, 'report_year': y,
                'reason': reason, 'target_fy': target,
                'pdf_url': available[y],
            })

    sel = pd.DataFrame(rows)
    sel.to_csv(SELECTION_CSV, index=False)
    p(f"\n  Selection plan → {SELECTION_CSV}")
    p(f"  Total PDFs to download: {len(sel):,}")
    if len(sel):
        p(f"  PDFs per stock distribution:")
        per_stock = sel.groupby('symbol').size()
        p(f"    mean={per_stock.mean():.1f}, median={per_stock.median():.0f}, "
          f"min={per_stock.min()}, max={per_stock.max()}")
        p(f"  Reason distribution:")
        for k, v in sel['reason'].value_counts().items():
            p(f"    {k:20s}  {v}")
        p(f"  Estimated download time: "
          f"{fmt_eta(len(sel) * DOWNLOAD_SLEEP)}")


# ===========================================================================
# PHASE 3 — BULK PDF DOWNLOAD
# ===========================================================================
def _pdf_path(symbol: str, year: int) -> str:
    return os.path.join(PDFS_DIR, f"{symbol}_{year}.pdf")


def phase_3() -> None:
    section("PHASE 3 — BULK PDF DOWNLOAD")
    if not os.path.exists(SELECTION_CSV):
        p(f"  ❌ {SELECTION_CSV} missing — run Phase 2 first")
        return
    sel = pd.read_csv(SELECTION_CSV)
    sel = sel.sort_values(['symbol', 'report_year']).reset_index(drop=True)

    # Resume skip
    to_download = []
    for _, r in sel.iterrows():
        path = _pdf_path(r['symbol'], int(r['report_year']))
        if not (os.path.exists(path) and os.path.getsize(path) > 1024):
            to_download.append(r)
    p(f"  Total in plan: {len(sel):,}")
    p(f"  Already on disk: {len(sel) - len(to_download):,}")
    p(f"  To download: {len(to_download):,}")
    p(f"  Estimated time: {fmt_eta(len(to_download) * DOWNLOAD_SLEEP)}")

    if not to_download:
        return

    n_ok, n_404, n_size, n_corrupt, n_net = 0, 0, 0, 0, 0
    t_loop = time.time()
    failures = []
    for i, r in enumerate(to_download, 1):
        if _should_stop:
            p(f"  [{ts()}] Stopping after {i - 1} attempts")
            break
        sym = r['symbol']
        year = int(r['report_year'])
        url = r['pdf_url']
        time.sleep(DOWNLOAD_SLEEP)
        content, status, err = get_binary(url, retries=1)
        if content is None:
            if status == 404:
                n_404 += 1
                failures.append({'symbol': sym, 'year': year, 'reason': '404',
                                 'url': url})
            elif status == 0:
                n_net += 1
                failures.append({'symbol': sym, 'year': year,
                                 'reason': f'network: {err}', 'url': url})
            else:
                n_net += 1
                failures.append({'symbol': sym, 'year': year,
                                 'reason': f'http_{status}: {err}', 'url': url})
        elif len(content) < 100_000:
            n_size += 1
            failures.append({'symbol': sym, 'year': year, 'reason': 'too_small',
                             'url': url})
        elif not content.startswith(b'%PDF'):
            n_corrupt += 1
            failures.append({'symbol': sym, 'year': year,
                             'reason': 'not_a_pdf', 'url': url})
        else:
            path = _pdf_path(sym, year)
            tmp = path + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(content)
            os.replace(tmp, path)
            n_ok += 1

        if i % 100 == 0 or i == len(to_download):
            elapsed = time.time() - t_loop
            rate = elapsed / i
            remaining = (len(to_download) - i) * rate
            p(f"  [{ts()}] {i}/{len(to_download)}  ok={n_ok} "
              f"404={n_404} size={n_size} corrupt={n_corrupt} net={n_net}  "
              f"ETA ~{fmt_eta(remaining)}")
            flush_log()
            # Persist failures log periodically
            if failures:
                pd.DataFrame(failures).to_csv(
                    os.path.join(PIPELINE_DIR, 'phase3_failures.csv'),
                    index=False)

    if failures:
        pd.DataFrame(failures).to_csv(
            os.path.join(PIPELINE_DIR, 'phase3_failures.csv'), index=False)
    p(f"\n  Phase 3 done.  ok={n_ok} 404={n_404} size={n_size} "
      f"corrupt={n_corrupt} net={n_net}")


# ===========================================================================
# PHASE 4 — DETAILED STATEMENT EXTRACTION
# ===========================================================================
# Canonical line-item dictionary: substring → canonical key
LINE_ITEM_PATTERNS = [
    # Revenue / Sales
    ('revenue', [
        r'revenue\s+from\s+operations', r'\btotal\s+revenue\b',
        r'\bnet\s+sales\b', r'\bturnover\b', r'\bsales\b',
        r'interest\s+earned', r'gross\s+income',
    ]),
    # Operating Profit / EBIT / PBDIT / EBITDA family
    ('ebit', [
        r'\bebit\b', r'\bebitda\b', r'\bpbdit\b', r'\bpbidt\b',
        r'operating\s+profit',
        r'profit\s+before\s+interest\s+and\s+tax',
        r'profit\s+before\s+(?:interest,?\s+)?depreciation,?\s+tax',
        r'profit\s+before\s+depreciation,?\s+(?:interest,?\s+)?tax',
        r'profit\s+before\s+interest,?\s+depreciation',
        r'earnings\s+before\s+interest',
        r'\bopm\b', r'operating\s+margin',
    ]),
    # Interest expense / Finance cost
    ('interest_expense', [
        r'finance\s+cost', r'\binterest\b(?!.*earned)',
        r'interest\s+and\s+finance\s+charges', r'finance\s+charges',
    ]),
    # Net Profit
    ('net_profit', [
        r'profit\s+after\s+tax', r'profit\s+for\s+the\s+year',
        r'profit/\s*\(loss\)\s+after\s+tax', r'net\s+profit', r'\bPAT\b',
        r'net\s+income',
    ]),
    # Total Assets
    ('total_assets', [r'total\s+assets', r'application\s+of\s+funds']),
    # Borrowings / Debt — do NOT include "deposits" (customer deposits are
    # a liability, not debt; banks need a separate handling)
    ('total_debt', [
        r'\btotal\s+borrowings\b',
        r'\bborrowings\b',
        r'long[-\s]term\s+borrowings',
        r'short[-\s]term\s+borrowings',
        r'loan\s+funds',
        r'long[-\s]term\s+debt',
    ]),
    # Bank customer deposits (captured separately so banks can be handled).
    # Bank-specific: avoid matching "fixed deposits" (treasury investments)
    ('bank_deposits', [
        r'(?:demand|saving|term|current\s+account)\s+deposits',
        r'\bcustomer\s+deposits\b',
        r'\bdeposits\s+from\s+(?:bank|customer)',
        r'\btotal\s+deposits\b',
    ]),
    # Equity
    ('equity', [
        r'shareholders.{0,3}\s+funds', r'\bnet\s+worth\b',
        r'total\s+equity', r'equity\s+share\s+capital',
        r'reserves\s+and\s+surplus',
    ]),
    # CFO
    ('cfo', [
        r'(?:net\s+)?cash\s+(?:from|generated\s+from|provided\s+by)\s+operating\s+activit',
        r'cash\s+generated\s+from\s+operations',
        r'cash\s+flow\s+from\s+operating\s+activit',
        r'cash\s+(?:flow\s+)?from\s+operations',
        r'net\s+cash\s+(?:from|generated\s+from|provided\s+by)\s+operating',
    ]),
    # Current Assets / Liabilities
    ('current_assets', [r'total\s+current\s+assets', r'current\s+assets']),
    ('current_liabilities', [
        r'total\s+current\s+liabilities', r'current\s+liabilities',
    ]),
]


def canonical_line_item(label: str) -> Optional[str]:
    """Return canonical key for a row label, or None if no match."""
    s = re.sub(r'\s+', ' ', (label or '')).strip().lower()
    if not s:
        return None
    for key, patterns in LINE_ITEM_PATTERNS:
        for pat in patterns:
            if re.search(pat, s):
                return key
    return None


_NUM_CLEAN = re.compile(r'[^\d.\-()]')


def parse_number(s: str) -> Optional[float]:
    if s is None:
        return None
    s = str(s).strip()
    if not s or s in ('-', '–', '—', 'NA', 'N.A.', 'NIL', 'Nil', 'nil'):
        return None
    # Negatives in parens
    neg = False
    if s.startswith('(') and s.endswith(')'):
        neg = True
        s = s[1:-1]
    # Strip Rs. ` ₹ symbols and commas
    s = s.replace('₹', '').replace('`', '').replace(',', '')
    s = s.replace('Rs.', '').replace('Rs', '')
    s = _NUM_CLEAN.sub('', s)
    if not s or s in ('-', '.'):
        return None
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def find_section_pages(pdf, keywords: list[str], max_check: int = 200) -> list[int]:
    """Return page indices (0-based) whose text contains any keyword."""
    pages = []
    n = min(len(pdf.pages), max_check)
    for i in range(n):
        try:
            t = (pdf.pages[i].extract_text() or '').lower()
        except Exception:
            continue
        if any(kw in t for kw in keywords):
            pages.append(i)
    return pages


def extract_table_text_pairs(text: str) -> list[tuple[str, list[float]]]:
    """Parse free text of a single statement page into (label, [values]) pairs.

    Heuristic: each line that ends with 2 or more numeric tokens is a row.
    Values are parsed via parse_number().
    """
    pairs: list[tuple[str, list[float]]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Split on whitespace; take trailing numeric tokens
        toks = line.split()
        # Find the longest trailing run of numeric-looking tokens
        nums = []
        for tok in reversed(toks):
            cand = parse_number(tok)
            if cand is not None:
                nums.append(cand)
            else:
                break
        if len(nums) < 1:
            continue
        nums = list(reversed(nums))
        label = ' '.join(toks[:len(toks) - len(nums)]).strip()
        if not label:
            continue
        pairs.append((label, nums))
    return pairs


# ---------------------------------------------------------------------------
# Unit detection — Indian ARs vary: ₹ in Crores / Lakhs / Million / Thousands
# ---------------------------------------------------------------------------
_UNIT_PATTERNS = [
    (re.compile(r'(?:rs|rupees|₹|`)\.?\s*(?:in\s+)?crores?\b', re.I),         1.0),
    (re.compile(r'(?:rs|rupees|₹|`)\.?\s*(?:in\s+)?lakhs?\b', re.I),          0.01),
    (re.compile(r'(?:rs|rupees|₹|`)\.?\s*(?:in\s+)?millions?\b', re.I),       0.1),
    (re.compile(r'(?:rs|rupees|₹|`)\.?\s*(?:in\s+)?thousands?\b', re.I),    0.0001),
    (re.compile(r'\bcr\.?\b', re.I),                                            1.0),
    (re.compile(r'amount\s+in\s+lakhs?', re.I),                                0.01),
    (re.compile(r'amount\s+in\s+millions?', re.I),                              0.1),
    (re.compile(r'amount\s+in\s+thousands?', re.I),                          0.0001),
    (re.compile(r'figures?\s+in\s+lakhs?', re.I),                              0.01),
    (re.compile(r'figures?\s+in\s+millions?', re.I),                            0.1),
]


def detect_unit_multiplier(page_text: str) -> tuple[float, str]:
    """Find the most prominent unit indicator on a page → multiplier to crore.
    Default to crore (1.0) if nothing detected."""
    # Look in the first ~600 chars (header) for most reliable signal
    header = page_text[:800]
    for pat, mult in _UNIT_PATTERNS:
        if pat.search(header):
            label = pat.pattern
            return mult, label
    # Fall back to whole-page scan
    for pat, mult in _UNIT_PATTERNS:
        if pat.search(page_text):
            return mult, pat.pattern
    return 1.0, 'default_crore'


# ---------------------------------------------------------------------------
# Section-aware line-item categorization
# ---------------------------------------------------------------------------
# Each statement type has its own allowed canonical line items, preventing
# cross-table contamination (e.g. don't read "Total Assets" off a P&L page).
SECTION_ALLOWED = {
    'pl': {'revenue', 'ebit', 'interest_expense', 'net_profit'},
    'bs': {'total_assets', 'total_debt', 'bank_deposits', 'equity',
           'current_assets', 'current_liabilities'},
    'cf': {'cfo'},
}


def filter_canonical_for_section(label: str, section: str) -> Optional[str]:
    key = canonical_line_item(label)
    if key is None:
        return None
    allowed = SECTION_ALLOWED.get(section, set())
    return key if key in allowed else None


def _pick_values_two_years(nums: list[float]) -> list[float]:
    """Given raw trailing numeric tokens from a row, pick the 2 most likely
    annual-figure values. Skip obviously-too-small entries that look like
    growth percentages or face values."""
    if not nums:
        return []
    # Drop trailing single-digit "note" markers (e.g. "Note 5")
    if len(nums) > 2 and -10 < nums[0] < 10 and nums[0] == int(nums[0]):
        nums = nums[1:]
    # Most statements show current year + prior year as the two main columns.
    # Anything 3rd+ is usually growth-percent or USD-converted noise — drop it.
    if len(nums) >= 2:
        return [nums[0], nums[1]]
    return nums[:1]


def extract_from_section_pages(pdf, page_idxs: list[int], section: str,
                                  cons_pref: str = '') -> dict:
    """Walk pages of one statement type, gather canonical line items.

    Returns {key: ([val_t, val_tm1], unit_multiplier_applied, page_idx)}.
    """
    found = {}
    for page_idx in page_idxs:
        try:
            text = pdf.pages[page_idx].extract_text() or ''
        except Exception:
            continue
        # Detect unit on this page
        mult, _unit_label = detect_unit_multiplier(text)
        pairs = extract_table_text_pairs(text)
        for label, nums in pairs:
            key = filter_canonical_for_section(label, section)
            if key is None or key in found:
                continue
            picked = _pick_values_two_years(nums)
            if not picked:
                continue
            # Apply unit multiplier (lakhs → crore = ×0.01, etc.)
            picked = [v * mult for v in picked]
            found[key] = picked
    return found


# ---------------------------------------------------------------------------
# PARSER v3 — table-based extraction with column-aware year detection
# and magnitude sanity checks
# ---------------------------------------------------------------------------
# Year-header detection: matches "31 March 2024", "March 31, 2024",
# "Year ended 31.03.2024", "FY 2023-24", "F.Y. 2024", bare "2024", etc.
_YEAR_HEADER_PATTERNS = [
    re.compile(r'(?:31[\s./-]*(?:march|mar)[\s./,]*|march[\s./,]*31[\s./,]*)(\d{4})', re.I),
    re.compile(r'(?:year\s+ended|as\s+at|as\s+on)[\s./,]*(?:31[\s./-]*(?:march|mar)[\s./,]*)?(\d{4})', re.I),
    re.compile(r'\bFY[\s.]*(\d{4})', re.I),
    re.compile(r'(?:fiscal|financial)\s+year\s+(\d{4})', re.I),
    re.compile(r'31[./-]03[./-](\d{4})'),
    re.compile(r'31[./-]3[./-](\d{4})'),
    re.compile(r'\b(20\d{2})[\s\-/](?:20)?\d{2}\b'),  # 2023-24
    re.compile(r'\b(20\d{2})\b'),  # bare year fallback
]


def parse_year_from_header(cell: str) -> Optional[int]:
    """Extract fiscal year (Mar-ending) from a single header cell."""
    if not cell:
        return None
    s = re.sub(r'\s+', ' ', cell).strip()
    for pat in _YEAR_HEADER_PATTERNS:
        m = pat.search(s)
        if m:
            try:
                y = int(m.group(1))
                if 1990 <= y <= 2030:
                    return y
            except (ValueError, IndexError):
                pass
    return None


def detect_year_columns(rows: list[list[str]]) -> list[Optional[int]]:
    """Look at the first few rows; find the row that best identifies year
    columns. Returns per-column fiscal year (None if not a year column)."""
    n_cols = max((len(r) for r in rows[:8] if r), default=0)
    if n_cols == 0:
        return []
    best = [None] * n_cols
    best_hits = 0
    for row in rows[:8]:
        if not row:
            continue
        years = []
        for cell in row:
            years.append(parse_year_from_header(cell or ''))
        # Pad/trim to n_cols
        while len(years) < n_cols:
            years.append(None)
        years = years[:n_cols]
        hits = sum(1 for y in years if y is not None)
        if hits > best_hits:
            best = years
            best_hits = hits
    return best


# Magnitude sanity ranges (in ₹ crore) per canonical line item.
# Tightened: biggest Indian companies cap revenue ~₹900k cr (RIL), net_profit
# ~₹75k cr; debt/assets driven by banks (SBI ~₹70 lakh cr assets, so 8M cap).
_SANITY_RANGES = {
    'revenue':              (0.1,       1_500_000),
    'ebit':                 (-30_000,     300_000),
    'interest_expense':     (0,           150_000),
    'net_profit':           (-30_000,     120_000),
    'total_assets':         (1,         8_000_000),
    'total_debt':           (0,         5_000_000),
    'equity':               (-50_000,   2_000_000),
    'cfo':                  (-50_000,    150_000),
    'current_assets':       (0,         2_000_000),
    'current_liabilities':  (0,         2_000_000),
    'bank_deposits':        (0,        15_000_000),  # SBI peaks ~₹50 lakh cr
}


def passes_sanity(key: str, value: float) -> bool:
    """True if value is within plausible range for the line item."""
    lo, hi = _SANITY_RANGES.get(key, (-1e18, 1e18))
    return lo <= value <= hi


def try_unit_repair(key: str, value: float) -> Optional[float]:
    """If value fails sanity, try dividing by 100 (lakhs→crore),
    10 (millions→crore), or 10,000 (thousands→crore) and return the first that
    passes. Returns None if nothing works."""
    for divisor in (100, 10, 10_000, 1000, 1_000_000):
        repaired = value / divisor
        if passes_sanity(key, repaired):
            return repaired
    return None


def clean_cell(s) -> str:
    """Normalize a table cell to a string."""
    if s is None:
        return ''
    s = str(s).replace('\n', ' ').strip()
    return re.sub(r'\s+', ' ', s)


def smart_pick_two(nums: list[float]) -> list[float]:
    """Given raw numerics from a row, return the 2 most likely annual-figure
    values. Filters out: small note-numbers, year headers, growth-%
    artifacts. Picks the two whose magnitudes are most similar (year-over-
    year values are usually within 5x of each other)."""
    candidates: list[float] = []
    for v in nums:
        if v is None:
            continue
        av = abs(v)
        # Drop years
        if 1990 <= v <= 2030 and v == int(v):
            continue
        # Drop tiny ints (likely note numbers)
        if av < 30 and v == int(v) and av >= 1:
            continue
        candidates.append(v)
    if len(candidates) < 2:
        return candidates[:1] if candidates else []
    # Find the consecutive pair with closest magnitudes (sliding window)
    best_pair = None
    best_ratio = float('inf')
    for i in range(len(candidates) - 1):
        a, b = candidates[i], candidates[i + 1]
        if abs(a) < 1e-6 or abs(b) < 1e-6:
            continue
        ratio = max(abs(a), abs(b)) / min(abs(a), abs(b))
        if ratio < best_ratio:
            best_ratio = ratio
            best_pair = (a, b)
    # Fallback: take 2 largest by absolute value
    if best_pair is None or best_ratio > 100:
        srt = sorted(candidates, key=lambda x: abs(x), reverse=True)
        return srt[:2]
    return list(best_pair)


def extract_rows_from_tables(page) -> list[tuple[str, list[float]]]:
    """Run extract_tables() on a page. Return list of
    (label, [raw_numeric_cells_in_row_after_label]).
    """
    try:
        tables = page.extract_tables() or []
    except Exception:
        tables = []
    out = []
    for tbl in tables:
        if not tbl or len(tbl) < 2:
            continue
        rows = [[clean_cell(c) for c in row] for row in tbl]
        for row in rows:
            if not row:
                continue
            # Label = first non-empty cell that isn't a year-only header
            # or a pure-numeric (note-number) cell
            label = ''
            label_idx = -1
            for i, c in enumerate(row):
                if not c:
                    continue
                if parse_year_from_header(c) is not None and len(c) < 25:
                    continue  # year header cell
                if parse_number(c) is not None and len(c) < 6:
                    continue  # note number / pure numeric
                label = c
                label_idx = i
                break
            if not label or label_idx < 0:
                continue
            raw_nums: list[float] = []
            for i, c in enumerate(row):
                if i <= label_idx:
                    continue
                v = parse_number(c)
                if v is None:
                    continue
                raw_nums.append(v)
            if not raw_nums:
                continue
            out.append((label, raw_nums))
    return out


def extract_section_v3(pdf, page_idxs: list[int], section: str,
                          report_year: int) -> dict:
    """Walk pages for a statement section. Returns {canonical_key: [v_t,
    v_tm1]} (values aligned to [report_year, report_year-1]).

    Strategy:
    1. For each page, run extract_tables() → row pairs.
    2. If no tables, fall back to text-pair extraction.
    3. Per matching row: smart_pick_two → apply page unit multiplier →
       sanity-check → if fail, try unit repair (×0.01 / ×0.1 / ×0.0001).
    """
    found: dict[str, list[float]] = {}
    for page_idx in page_idxs:
        page = pdf.pages[page_idx]
        try:
            text = page.extract_text() or ''
        except Exception:
            text = ''
        page_mult, _ = detect_unit_multiplier(text)
        rows = extract_rows_from_tables(page)
        if not rows:
            pairs = extract_table_text_pairs(text)
            rows = [(label, nums) for label, nums in pairs]
        for label, raw_nums in rows:
            key = filter_canonical_for_section(label, section)
            if key is None or key in found:
                continue
            picked = smart_pick_two(raw_nums)
            if not picked:
                continue
            cleaned = []
            for v in picked:
                v_scaled = v * page_mult
                if passes_sanity(key, v_scaled):
                    cleaned.append(v_scaled)
                else:
                    repaired = try_unit_repair(key, v_scaled)
                    if repaired is not None:
                        cleaned.append(repaired)
                    else:
                        cleaned.append(None)
            if any(x is not None for x in cleaned):
                found[key] = cleaned
    return found


def extract_one_pdf_v3(pdf_path: str, symbol: str, report_year: int) -> dict:
    """v4 extractor: table-based, column-aware, sanity-checked, bank-aware,
    expanded EBIT patterns, multi-page sections."""
    rec = {
        'symbol': symbol, 'report_year': report_year,
        'extraction_status': 'unknown',
        'consolidated_or_standalone': '',
        'is_bank': False,
        'fiscal_years_covered': [],
        'units': 'INR crore',
        'extraction_confidence': 'low',
        'line_items': {},
        'extraction_warnings': [],
        'parser_version': 'v4',
    }
    try:
        import pdfplumber
    except ImportError:
        rec['extraction_status'] = 'pdfplumber_missing'
        return rec
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as e:
        rec['extraction_status'] = 'open_failed'
        rec['extraction_warnings'].append(f"open: {type(e).__name__}: {e}")
        return rec
    try:
        pl_cons = find_section_pages(pdf, [
            'consolidated statement of profit and loss',
            'consolidated profit and loss',
        ])
        pl_std = find_section_pages(pdf, [
            'standalone statement of profit and loss',
            'standalone profit and loss',
            'statement of profit and loss',
            'profit and loss account',
            'profit & loss account',
        ])
        bs_cons = find_section_pages(pdf, ['consolidated balance sheet'])
        bs_std = find_section_pages(pdf, [
            'standalone balance sheet',
            'balance sheet as at',
            'balance sheet as on',
        ])
        cf_cons = find_section_pages(pdf, [
            'consolidated cash flow',
            'consolidated statement of cash flow',
        ])
        cf_std = find_section_pages(pdf, [
            'standalone cash flow',
            'cash flow statement',
            'statement of cash flow',
        ])

        pl_pages = pl_cons or pl_std
        bs_pages = bs_cons or bs_std
        cf_pages = cf_cons or cf_std
        chose_consolidated = bool(pl_cons or bs_cons or cf_cons)
        rec['consolidated_or_standalone'] = (
            'consolidated' if chose_consolidated else 'standalone'
        )

        if not pl_pages and not bs_pages and not cf_pages:
            rec['extraction_status'] = 'no_sections_found'
            return rec

        # Bank detection: presence of bank-specific terms on PL pages
        bank_indicators = ('interest earned', 'net interest income',
                            'demand deposits', 'savings deposits')
        is_bank = False
        for p_idx in (pl_pages[:2] + bs_pages[:2])[:4]:
            try:
                t = (pdf.pages[p_idx].extract_text() or '').lower()
            except Exception:
                continue
            if sum(1 for kw in bank_indicators if kw in t) >= 2:
                is_bank = True
                break
        rec['is_bank'] = is_bank

        # Multi-page scans (3.6): up to 5 pages per section so CFO isn't
        # truncated and "Application of Funds" balance sheets get found
        pl_items = extract_section_v3(pdf, pl_pages[:5], 'pl', report_year)
        bs_items = extract_section_v3(pdf, bs_pages[:5], 'bs', report_year)
        cf_items = extract_section_v3(pdf, cf_pages[:5], 'cf', report_year)

        # Fallback to v2 text-pair extraction for sections that produced nothing.
        # smart_pick_two + sanity gate still applies (we wrap v2 results).
        def _v2_fallback(page_idxs, section):
            v2 = extract_from_section_pages(pdf, page_idxs, section)
            out = {}
            for k, vals in v2.items():
                if not vals:
                    continue
                picked = smart_pick_two(vals if isinstance(vals, list) else [vals])
                if not picked:
                    continue
                cleaned = []
                for v in picked:
                    if passes_sanity(k, v):
                        cleaned.append(v)
                    else:
                        rep = try_unit_repair(k, v)
                        cleaned.append(rep)
                if any(x is not None for x in cleaned):
                    out[k] = cleaned
            return out

        if not pl_items and pl_pages:
            pl_items = _v2_fallback(pl_pages[:5], 'pl')
        if not bs_items and bs_pages:
            bs_items = _v2_fallback(bs_pages[:5], 'bs')
        if not cf_items and cf_pages:
            cf_items = _v2_fallback(cf_pages[:5], 'cf')

        # Merge per-section dicts (sections own disjoint keys, so no conflict).
        # Each value is list[Optional[float]] aligned to [report_year, report_year-1].
        merged: dict[str, list] = {}
        for d in (pl_items, bs_items, cf_items):
            for k, vals in d.items():
                if k not in merged:
                    merged[k] = vals

        if not merged:
            rec['extraction_status'] = 'no_items_extracted'
            return rec

        rec['fiscal_years_covered'] = [report_year, report_year - 1]
        rec['line_items'] = {k: v for k, v in merged.items()
                              if any(x is not None for x in v)}

        if not rec['line_items']:
            rec['extraction_status'] = 'no_items_extracted'
            return rec

        critical = ('revenue', 'net_profit', 'total_assets', 'equity')
        n_critical = sum(1 for k in critical if k in rec['line_items'])
        if n_critical >= 3:
            rec['extraction_confidence'] = 'high'
        elif n_critical >= 1:
            rec['extraction_confidence'] = 'medium'
        else:
            rec['extraction_confidence'] = 'low'

        rec['extraction_status'] = 'success'
        return rec
    finally:
        try:
            pdf.close()
        except Exception:
            pass


def extract_one_pdf(pdf_path: str, symbol: str, report_year: int) -> dict:
    """Extract a single PDF into the per-PDF JSON record (v2: section-aware
    + unit detection)."""
    rec = {
        'symbol': symbol, 'report_year': report_year,
        'extraction_status': 'unknown',
        'consolidated_or_standalone': '',
        'fiscal_years_covered': [],
        'units': 'INR crore',
        'extraction_confidence': 'low',
        'line_items': {},
        'extraction_warnings': [],
    }
    try:
        import pdfplumber
    except ImportError:
        rec['extraction_status'] = 'pdfplumber_missing'
        return rec

    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as e:
        rec['extraction_status'] = 'open_failed'
        rec['extraction_warnings'].append(f"open: {type(e).__name__}: {e}")
        return rec

    try:
        # Find pages for each statement type. Prefer consolidated where
        # available — check for that keyword first.
        pl_cons = find_section_pages(pdf, [
            'consolidated statement of profit and loss',
            'consolidated profit and loss',
        ])
        pl_std = find_section_pages(pdf, [
            'standalone statement of profit and loss',
            'standalone profit and loss',
            'statement of profit and loss',
            'profit and loss account',
            'profit & loss account',
        ])
        bs_cons = find_section_pages(pdf, [
            'consolidated balance sheet',
        ])
        bs_std = find_section_pages(pdf, [
            'standalone balance sheet',
            'balance sheet as at',
            'balance sheet as on',
        ])
        cf_cons = find_section_pages(pdf, [
            'consolidated cash flow',
            'consolidated statement of cash flow',
        ])
        cf_std = find_section_pages(pdf, [
            'standalone cash flow',
            'cash flow statement',
            'statement of cash flow',
        ])

        # Choose consolidated if available, else standalone
        pl_pages = pl_cons or pl_std
        bs_pages = bs_cons or bs_std
        cf_pages = cf_cons or cf_std
        chose_consolidated = bool(pl_cons or bs_cons or cf_cons)
        rec['consolidated_or_standalone'] = (
            'consolidated' if chose_consolidated else 'standalone'
        )

        if not pl_pages and not bs_pages and not cf_pages:
            rec['extraction_status'] = 'no_sections_found'
            return rec

        # Extract per-section, only top 3 pages each (most statements span 1-2
        # pages — extras are usually notes)
        pl_items = extract_from_section_pages(pdf, pl_pages[:3], 'pl')
        bs_items = extract_from_section_pages(pdf, bs_pages[:3], 'bs')
        cf_items = extract_from_section_pages(pdf, cf_pages[:3], 'cf')

        line_items: dict[str, list[float]] = {}
        for d in (pl_items, bs_items, cf_items):
            for k, v in d.items():
                if k not in line_items:
                    line_items[k] = v

        if not line_items:
            rec['extraction_status'] = 'no_items_extracted'
            return rec

        rec['line_items'] = line_items

        critical = ('revenue', 'net_profit', 'total_assets', 'equity')
        n_critical = sum(1 for k in critical if k in line_items)
        if n_critical >= 3:
            rec['extraction_confidence'] = 'high'
        elif n_critical >= 1:
            rec['extraction_confidence'] = 'medium'
        else:
            rec['extraction_confidence'] = 'low'

        rec['fiscal_years_covered'] = [report_year, report_year - 1]
        rec['extraction_status'] = 'success'
        return rec
    finally:
        try:
            pdf.close()
        except Exception:
            pass


def _extract_worker(args):
    """Process-pool worker. Returns (sym, year, out_path, rec)."""
    sym, year, pdf_path, out_path = args
    try:
        rec = extract_one_pdf_v3(pdf_path, sym, year)
    except Exception as e:
        rec = {'symbol': sym, 'report_year': year,
               'extraction_status': 'exception',
               'extraction_warnings': [f"{type(e).__name__}: {e}"]}
    return sym, year, out_path, rec


def phase_4() -> None:
    section("PHASE 4 — DETAILED STATEMENT EXTRACTION (parallel v4)")
    if not os.path.exists(SELECTION_CSV):
        p(f"  ❌ {SELECTION_CSV} missing — run Phase 2 first")
        return
    sel = pd.read_csv(SELECTION_CSV)
    targets = []
    for _, r in sel.iterrows():
        sym = r['symbol']
        year = int(r['report_year'])
        pdf_path = _pdf_path(sym, year)
        out_path = os.path.join(EXTRACT_DIR, f"{sym}_{year}.json")
        if not os.path.exists(pdf_path):
            continue
        if os.path.exists(out_path):
            continue
        targets.append((sym, year, pdf_path, out_path))

    p(f"  PDFs to extract: {len(targets):,}")
    if not targets:
        p(f"  Nothing to extract.")
        return

    # Serial execution (single-threaded). Parallel attempts caused thermal +
    # macOS multiprocessing issues on this machine. Serial is steady at
    # ~250-300 PDFs/hr; total run ~22-25h.
    n_ok = n_low = n_no_sections = n_failed = 0
    t_loop = time.time()
    for i, (sym, year, pdf_path, out_path) in enumerate(targets, 1):
        if _should_stop:
            p(f"  [{ts()}] Stopping after {i - 1}")
            break
        try:
            rec = extract_one_pdf_v3(pdf_path, sym, year)
        except Exception as e:
            rec = {'symbol': sym, 'report_year': year,
                   'extraction_status': 'exception',
                   'extraction_warnings': [f"{type(e).__name__}: {e}"]}
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(rec, f, default=str)
        st = rec.get('extraction_status', '')
        conf = rec.get('extraction_confidence', '')
        if st == 'success' and conf == 'high':
            n_ok += 1
        elif st == 'success':
            n_low += 1
        elif st == 'no_sections_found':
            n_no_sections += 1
        else:
            n_failed += 1
        if i % 50 == 0 or i == len(targets):
            elapsed = time.time() - i
            rate = (time.time() - t_loop) / i
            remaining = (len(targets) - i) * rate
            p(f"  [{ts()}] {i}/{len(targets)}  high={n_ok} low={n_low} "
              f"no_sect={n_no_sections} fail={n_failed}  "
              f"ETA ~{fmt_eta(remaining)}")
            flush_log()

    p(f"\n  Phase 4 done.  high={n_ok} medium/low={n_low} "
      f"no_sections={n_no_sections} failed={n_failed}")


# ===========================================================================
# PHASE 5 — STANDARDIZE ACROSS STOCKS
# ===========================================================================
def phase_5() -> None:
    section("PHASE 5 — STANDARDIZATION")
    files = sorted(glob.glob(os.path.join(EXTRACT_DIR, "*.json")))
    p(f"  Extraction JSONs: {len(files):,}")
    if not files:
        return

    rows = []
    for f in files:
        try:
            with open(f, encoding='utf-8') as fh:
                rec = json.load(fh)
        except Exception:
            continue
        if rec.get('extraction_status') != 'success':
            continue
        sym = rec['symbol']
        years = rec.get('fiscal_years_covered') or []
        line_items = rec.get('line_items') or {}
        for key, vals in line_items.items():
            for i, val in enumerate(vals):
                if i >= len(years):
                    continue
                if val is None:
                    continue
                rows.append({
                    'symbol': sym,
                    'fiscal_year': int(years[i]),
                    'line_item': key,
                    'value': val,
                    'source_pdf_year': int(rec['report_year']),
                    'is_consolidated': rec.get('consolidated_or_standalone') == 'consolidated',
                    'confidence': rec.get('extraction_confidence', ''),
                })

    df = pd.DataFrame(rows)
    if df.empty:
        p(f"  No standardized rows produced.")
        return

    # Resolve duplicates: prefer newer source_pdf_year
    df = df.sort_values(['symbol', 'fiscal_year', 'line_item',
                          'source_pdf_year'],
                         ascending=[True, True, True, False])
    df = df.drop_duplicates(subset=['symbol', 'fiscal_year', 'line_item'],
                              keep='first')

    df.to_parquet(STANDARDIZED_PARQUET, index=False)
    p(f"  Standardized → {STANDARDIZED_PARQUET}")
    p(f"    rows: {len(df):,}  symbols: {df['symbol'].nunique()}  "
      f"years: {df['fiscal_year'].min()} → {df['fiscal_year'].max()}")
    p(f"  Line-item counts:")
    for k, v in df['line_item'].value_counts().items():
        p(f"    {k:25s}  {v:,}")


# ===========================================================================
# PHASE 6 — VALIDATE VS SCREENER
# ===========================================================================
def phase_6() -> None:
    section("PHASE 6 — CROSS-VALIDATE VS SCREENER")
    if not os.path.exists(STANDARDIZED_PARQUET):
        p(f"  ❌ {STANDARDIZED_PARQUET} missing — run Phase 5 first")
        return
    if not os.path.exists(SCREENER_PANEL):
        p(f"  ❌ {SCREENER_PANEL} missing — cannot validate")
        return
    bse = pd.read_parquet(STANDARDIZED_PARQUET)
    sc = pd.read_parquet(SCREENER_PANEL)
    # Screener has period like "Mar 2018" → fiscal_year 2018 (March-ending convention)
    sc = sc.copy()
    sc['fiscal_year'] = sc['period'].astype(str).str.extract(r'(\d{4})$').astype(float)
    sc = sc.dropna(subset=['fiscal_year'])
    sc['fiscal_year'] = sc['fiscal_year'].astype(int)
    # Map screener line items to canonical
    sc['canonical'] = sc['line_item'].apply(canonical_line_item)
    sc = sc.dropna(subset=['canonical', 'value'])
    sc_agg = (sc.groupby(['symbol', 'fiscal_year', 'canonical'])['value']
                .last().reset_index().rename(columns={'value': 'screener_value',
                                                       'canonical': 'line_item'}))

    merged = bse.merge(sc_agg, on=['symbol', 'fiscal_year', 'line_item'],
                        how='inner')
    if merged.empty:
        p(f"  No overlapping (symbol, fiscal_year, line_item) rows to validate.")
        return
    merged['pct_diff'] = ((merged['value'] - merged['screener_value']).abs()
                          / merged['screener_value'].abs().clip(lower=1e-6))
    def categorize(pct):
        if pct <= 0.05:
            return 'VERIFIED'
        if pct <= 0.10:
            return 'ACCEPTABLE'
        if pct <= 0.30:
            return 'FLAG'
        return 'ERROR'
    merged['status'] = merged['pct_diff'].apply(categorize)
    merged.to_csv(VALIDATION_CSV, index=False)
    p(f"  Validation report → {VALIDATION_CSV}")
    p(f"    Comparable rows: {len(merged):,}")
    for s, c in merged['status'].value_counts().items():
        p(f"    {s:12s}  {c:,}  ({c/len(merged)*100:.1f}%)")

    err = merged[merged['status'] == 'ERROR']
    if not err.empty:
        err.to_csv(MANUAL_REVIEW_CSV, index=False)
        p(f"  Manual review queue → {MANUAL_REVIEW_CSV}  ({len(err):,} errors)")


# ===========================================================================
# PHASE 7 — BUILD EXTENDED PANEL
# ===========================================================================
def phase_7() -> None:
    section("PHASE 7 — BUILD EXTENDED FUNDAMENTALS PANEL")
    bse = (pd.read_parquet(STANDARDIZED_PARQUET)
           if os.path.exists(STANDARDIZED_PARQUET) else pd.DataFrame())
    sc = (pd.read_parquet(SCREENER_PANEL)
          if os.path.exists(SCREENER_PANEL) else pd.DataFrame())

    if sc.empty:
        p(f"  ❌ no Screener panel to merge with")
        return

    sc = sc.copy()
    sc['fiscal_year'] = sc['period'].astype(str).str.extract(r'(\d{4})$').astype(float)
    sc = sc.dropna(subset=['fiscal_year'])
    sc['fiscal_year'] = sc['fiscal_year'].astype(int)
    sc['line_item_canonical'] = sc['line_item'].apply(canonical_line_item)
    sc = sc.dropna(subset=['line_item_canonical', 'value'])
    # Drop the raw line_item column before renaming to avoid duplicate names
    sc = sc.drop(columns=['line_item']).rename(
        columns={'line_item_canonical': 'line_item'})
    # Deduplicate (symbol, fiscal_year, line_item) by keeping last value
    sc = sc.sort_values(['symbol', 'fiscal_year', 'line_item'])
    sc = sc.drop_duplicates(subset=['symbol', 'fiscal_year', 'line_item'],
                              keep='last')
    sc_norm = sc[['symbol', 'fiscal_year', 'line_item', 'value']].copy()
    sc_norm['source'] = 'screener'
    sc_norm['confidence'] = 'screener'

    bse_norm = bse[['symbol', 'fiscal_year', 'line_item', 'value',
                     'confidence']].copy() if not bse.empty else pd.DataFrame()
    if not bse_norm.empty:
        bse_norm['source'] = 'bse'

    if bse_norm.empty:
        combined = sc_norm
    else:
        combined = pd.concat([bse_norm, sc_norm], ignore_index=True, sort=False)

    # Conflict resolution: prefer screener where both exist (cleaner)
    combined = combined.sort_values(['symbol', 'fiscal_year', 'line_item', 'source'],
                                       ascending=[True, True, True, False])
    combined = combined.drop_duplicates(subset=['symbol', 'fiscal_year', 'line_item'],
                                            keep='first')
    combined.to_parquet(EXTENDED_PARQUET, index=False)

    p(f"  Extended fundamentals → {EXTENDED_PARQUET}")
    p(f"    Total rows: {len(combined):,}")
    p(f"    Symbols: {combined['symbol'].nunique():,}")
    p(f"    Year range: {combined['fiscal_year'].min()} → "
      f"{combined['fiscal_year'].max()}")
    p(f"  Source distribution:")
    for s, c in combined['source'].value_counts().items():
        p(f"    {s:12s}  {c:,}")

    # Spot checks
    p(f"\n  Spot checks (expected approximate values):")
    spots = [
        ('RELIANCE', 2010, 'revenue', '~₹2,00,000 cr'),
        ('ITC', 2010, 'revenue', '~₹20,000 cr'),
        ('HDFCBANK', 2010, 'net_profit', '~₹3,000 cr'),
        ('SATYAMCOMP', 2008, 'revenue', '~₹8,500 cr (pre-fraud)'),
        ('DHFL', 2015, 'total_debt', '~₹40,000-50,000 cr'),
    ]
    for sym, fy, item, expected in spots:
        sub = combined[(combined['symbol'] == sym) &
                        (combined['fiscal_year'] == fy) &
                        (combined['line_item'] == item)]
        if not sub.empty:
            r = sub.iloc[0]
            p(f"    {sym} FY{fy} {item}: {r['value']:,.0f}  "
              f"(source={r['source']}, expected={expected})")
        else:
            p(f"    {sym} FY{fy} {item}: NOT FOUND  (expected={expected})")


# ===========================================================================
# Main
# ===========================================================================
PHASES = {
    '0': phase_0, '1': phase_1, '2': phase_2, '3': phase_3,
    '4': phase_4, '5': phase_5, '6': phase_6, '7': phase_7,
}
ALL_PHASES = ['0', '1', '2', '3', '4', '5', '6', '7']


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', default='all',
                          help='Phase ID(s) to run: 0, 1, 2, ..., 7, '
                                'or "all", or comma-separated like "0,1,2"')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    open_log(append=True)
    t_start = time.time()
    p("=" * 80)
    p(f"  BSE PIPELINE FULL")
    p(f"  Start: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    p(f"  PID: {os.getpid()}")
    p(f"  Phase argument: {args.phase}")
    p("=" * 80)

    if args.phase == 'all':
        phases_to_run = ALL_PHASES
    else:
        phases_to_run = [s.strip() for s in args.phase.split(',') if s.strip()]
        for ph in phases_to_run:
            if ph not in PHASES:
                p(f"  ❌ Unknown phase {ph!r} (valid: {sorted(PHASES.keys())})")
                close_log()
                return 1

    for ph in phases_to_run:
        if _should_stop:
            p(f"\n  Stopping before phase {ph}")
            break
        try:
            PHASES[ph]()
        except Exception:
            p(f"\n  EXCEPTION in phase {ph}:")
            p(traceback.format_exc())

    p(f"\n  Total elapsed: {fmt_eta(time.time() - t_start)}")
    p(f"  Log: {LOG_PATH}")
    close_log()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 80 + "\n  UNCAUGHT EXCEPTION\n" + "=" * 80 + "\n")
            f.write(traceback.format_exc())
        raise

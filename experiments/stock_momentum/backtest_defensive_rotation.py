"""Defensive-quality rotation backtest — replace bear-regime cash with a
defensive-quality equity basket, net of transaction costs.

Six variants (all net of costs):
  Baseline: bull=momentum (raw top-30), bear=cash
  V1: bull=momentum+hard-rules, bear=cash
  V2: bull=momentum+hard-rules, bear=defensive basket, NO dampening
  V3: V2 + all dampening (sticky signal + basket overlap + gradual rotation)
  V4: bull=mom+hard-rules, bear=60% defensive / 40% cash + dampening
  Challenger: bull=re-rank 0.7*mom_z+0.3*qual_z, bear=best sleeve above

Reuses the plumbing from backtest_mom_quality.py.

LIMITATIONS (called out honestly):
- Sector mapping: hand-crafted for ~150 well-known Indian stocks; unknowns → 'Other'
- Gold price data (HDFCGOLD) only from 2023-06 → gold unavailable across full history;
  bear-regime 'cash' baseline uses 7% p.a. throughout
- Gradual rotation modeled as reduced slippage on switches, not day-by-day simulation
- Bear episodes derived from the daily regime signal (contiguous bear runs)
"""
from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCORED_UNIVERSE = os.path.join(REPO_ROOT, "data", "momentum_scores",
                                 "scored_universe.parquet")
QUALITY_SCORES = os.path.join(REPO_ROOT, "data", "quality_factor",
                                "quality_scores_pit.parquet")
FUND_PANEL = os.path.join(REPO_ROOT, "data", "bse_pipeline",
                            "extended_fundamentals_v2.parquet")
PRICES = os.path.join(REPO_ROOT, "data", "yfinance_bulk",
                        "adjusted_prices_panel.parquet")
NIFTY_HISTORY = os.path.join(REPO_ROOT, "data", "nifty500_history.csv")
OUT_DIR = os.path.join(REPO_ROOT, "data", "defensive_rotation")
os.makedirs(OUT_DIR, exist_ok=True)

# Config
UNIVERSE_TOP_N        = 200
N_BULL_HOLD           = 30
N_BEAR_HOLD           = 18
SECTOR_CAP_BULL       = 6
SECTOR_CAP_BEAR       = 5
MOM_BUFFER_RANK       = 40
REPORTING_LAG_MONTHS  = 6
COST_BPS_PER_SIDE     = 15
SLIPPAGE_BPS          = 15
SLIPPAGE_BPS_GRADUAL  = 5      # gradual rotation reduces slippage
REGIME_MA_DAYS        = 200
CASH_YIELD_ANNUAL     = 0.07
STICKY_N_DAYS         = 7      # regime must persist N days before switching
GRADUAL_DAYS          = 4      # spread swap over N days
BEAR_BLEND_DEFENSIVE  = 0.60   # V4: 60% defensive, 40% cash

# Hard-rules thresholds
HARD_RULE_DE_MAX      = 2.0    # debt/equity < 2 (capital-intensive: 3.0)

# Defensive-basket selection thresholds
DEF_MIN_QUALITY_PCT   = 0.60   # top 40% quality only
DEF_MAX_BETA          = 0.85
DEF_MAX_VOL           = 0.30   # annualized

# Sector mapping (hand-crafted; well-known Indian stocks)
# Defensive sectors get preference in bear basket
SECTOR_MAP = {
    # Banks
    'HDFCBANK': 'Bank', 'ICICIBANK': 'Bank', 'AXISBANK': 'Bank', 'KOTAKBANK': 'Bank',
    'SBIN': 'Bank', 'INDUSINDBK': 'Bank', 'FEDERALBNK': 'Bank', 'PNB': 'Bank',
    'BANKBARODA': 'Bank', 'CANBK': 'Bank', 'UNIONBANK': 'Bank', 'IDFCFIRSTB': 'Bank',
    'YESBANK': 'Bank', 'RBLBANK': 'Bank', 'INDIANB': 'Bank', 'BANKINDIA': 'Bank',
    'IDBI': 'Bank', 'IOB': 'Bank', 'UCO': 'Bank',
    # NBFCs / Financials
    'BAJFINANCE': 'Financial', 'BAJAJFINSV': 'Financial', 'CHOLAFIN': 'Financial',
    'M&MFIN': 'Financial', 'LICHSGFIN': 'Financial', 'PFC': 'Financial', 'RECLTD': 'Financial',
    'HDFC': 'Financial', 'HDFCLIFE': 'Financial', 'ICICIPRULI': 'Financial',
    'SBILIFE': 'Financial', 'MUTHOOTFIN': 'Financial', 'MANAPPURAM': 'Financial',
    'IIFL': 'Financial', 'EDELWEISS': 'Financial', 'DHFL': 'Financial',
    'ICICIGI': 'Financial', 'INDIABULLS': 'Financial',
    # IT
    'INFY': 'IT', 'TCS': 'IT', 'WIPRO': 'IT', 'HCLTECH': 'IT', 'TECHM': 'IT',
    'LTI': 'IT', 'LTTS': 'IT', 'MPHASIS': 'IT', 'MINDTREE': 'IT', 'COFORGE': 'IT',
    'PERSISTENT': 'IT', 'LTIM': 'IT', 'BIRLASOFT': 'IT', 'CYIENT': 'IT',
    '3IINFOTECH': 'IT', 'SATYAMCOMP': 'IT', 'FSL': 'IT', 'KPITTECH': 'IT',
    # FMCG (defensive)
    'HINDUNILVR': 'FMCG', 'ITC': 'FMCG', 'NESTLEIND': 'FMCG', 'DABUR': 'FMCG',
    'BRITANNIA': 'FMCG', 'MARICO': 'FMCG', 'GODREJCP': 'FMCG', 'COLPAL': 'FMCG',
    'EMAMILTD': 'FMCG', 'PGHH': 'FMCG', 'GILLETTE': 'FMCG', 'JYOTHYLAB': 'FMCG',
    'RADICO': 'FMCG', 'UBL': 'FMCG', 'VBL': 'FMCG', 'TATACONSUM': 'FMCG',
    # Pharma (defensive)
    'SUNPHARMA': 'Pharma', 'DRREDDY': 'Pharma', 'CIPLA': 'Pharma', 'LUPIN': 'Pharma',
    'AUROPHARMA': 'Pharma', 'GLENMARK': 'Pharma', 'BIOCON': 'Pharma', 'CADILAHC': 'Pharma',
    'DIVISLAB': 'Pharma', 'TORNTPHARM': 'Pharma', 'ALKEM': 'Pharma', 'IPCALAB': 'Pharma',
    'WOCKPHARMA': 'Pharma', 'AJANTPHARM': 'Pharma', 'FDC': 'Pharma', 'ELDERPHARM': 'Pharma',
    'GLAXO': 'Pharma', 'SANOFI': 'Pharma', 'PFIZER': 'Pharma', 'ABBOTINDIA': 'Pharma',
    # Auto
    'MARUTI': 'Auto', 'TATAMOTORS': 'Auto', 'M&M': 'Auto', 'BAJAJ-AUTO': 'Auto',
    'HEROMOTOCO': 'Auto', 'EICHERMOT': 'Auto', 'ASHOKLEY': 'Auto', 'ESCORTS': 'Auto',
    'TVSMOTOR': 'Auto', 'MOTHERSUMI': 'Auto', 'BOSCHLTD': 'Auto', 'BALKRISIND': 'Auto',
    # Energy
    'RELIANCE': 'Energy', 'ONGC': 'Energy', 'IOC': 'Energy', 'BPCL': 'Energy',
    'HINDPETRO': 'Energy', 'GAIL': 'Energy', 'OIL': 'Energy', 'MRPL': 'Energy',
    'PETRONET': 'Energy', 'HINDOILEXP': 'Energy',
    # Metals
    'TATASTEEL': 'Metal', 'HINDALCO': 'Metal', 'SAIL': 'Metal', 'JSWSTEEL': 'Metal',
    'JSWENERGY': 'Metal', 'VEDL': 'Metal', 'JINDALSTEL': 'Metal', 'NMDC': 'Metal',
    'MOIL': 'Metal', 'NALCO': 'Metal', 'RATNAMANI': 'Metal',
    # Utilities (defensive)
    'NTPC': 'Utility', 'POWERGRID': 'Utility', 'ADANIPOWER': 'Utility',
    'ADANITRANS': 'Utility', 'ADANIGREEN': 'Utility', 'TATAPOWER': 'Utility',
    'JSPL': 'Utility', 'TORNTPOWER': 'Utility', 'NHPC': 'Utility',
    # Cement
    'ULTRACEMCO': 'Cement', 'ACC': 'Cement', 'AMBUJACEM': 'Cement', 'SHREECEM': 'Cement',
    'DALBHARAT': 'Cement', 'RAMCOCEM': 'Cement', 'INDIACEM': 'Cement',
    # Infra / Real Estate
    'LT': 'Infra', 'ADANIPORTS': 'Infra', 'ADANIENT': 'Infra', 'GMRINFRA': 'Infra',
    'IRB': 'Infra', 'RITES': 'Infra', 'IRCON': 'Infra', 'DBL': 'Infra',
    'DLF': 'Realty', 'GODREJPROP': 'Realty', 'OBEROIRLTY': 'Realty',
    'PRESTIGE': 'Realty', 'BRIGADE': 'Realty', 'ANANTRAJ': 'Realty', 'AKRUTI': 'Realty',
    # Telecom
    'BHARTIARTL': 'Telecom', 'IDEA': 'Telecom', 'RCOM': 'Telecom', 'GTLINFRA': 'Telecom',
    'HFCL': 'Telecom', 'TATACOMM': 'Telecom',
    # Chemicals / Paints
    'ASIANPAINT': 'Chemicals', 'BERGEPAINT': 'Chemicals', 'PIDILITIND': 'Chemicals',
    'UPL': 'Chemicals', 'SRF': 'Chemicals', 'DEEPAKNTR': 'Chemicals',
    'AARTIIND': 'Chemicals', 'FLUOROCHEM': 'Chemicals', 'GNFC': 'Chemicals',
    'GSFC': 'Chemicals', 'CHAMBLFERT': 'Chemicals', 'RCF': 'Chemicals',
    # Consumer discretionary
    'TITAN': 'ConsumerDisc', 'PAGEIND': 'ConsumerDisc', 'BATAINDIA': 'ConsumerDisc',
    'HAVELLS': 'ConsumerDisc', 'VOLTAS': 'ConsumerDisc', 'CROMPTON': 'ConsumerDisc',
    'DIXON': 'ConsumerDisc', 'BOMDYEING': 'ConsumerDisc', 'FCONSUMER': 'ConsumerDisc',
    'RPOWER': 'Utility', 'ATGL': 'Utility',
}

DEFENSIVE_SECTORS = {'FMCG', 'Pharma', 'Utility', 'IT'}


def get_sector(sym):
    return SECTOR_MAP.get(sym, 'Other')


def is_defensive_sector(sym):
    return get_sector(sym) in DEFENSIVE_SECTORS


def load_regime_series():
    df = pd.read_csv(NIFTY_HISTORY)
    df['date'] = pd.to_datetime(df['TIMESTAMP'])
    df = df.sort_values('date').set_index('date')
    df['ma'] = df['CLOSE_INDEX_VAL'].rolling(REGIME_MA_DAYS).mean()
    df['bull_raw'] = df['CLOSE_INDEX_VAL'] > df['ma']
    return df[['CLOSE_INDEX_VAL', 'ma', 'bull_raw']]


def apply_sticky(regime_daily, sticky_n=STICKY_N_DAYS):
    """Regime doesn't flip until it has persisted N days.
    Returns 'bull' column added to daily regime df."""
    df = regime_daily.copy()
    raw = df['bull_raw'].ffill().fillna(True).values
    n = len(raw)
    out = np.zeros(n, dtype=bool)
    if n == 0:
        df['bull'] = out
        return df
    cur = raw[0]
    out[0] = cur
    streak = 1
    for i in range(1, n):
        if raw[i] == cur:
            streak += 1
            out[i] = cur
        else:
            # candidate switch
            # count how many days ahead are the new regime
            j = i
            while j < n and raw[j] != cur:
                j += 1
            switch_run = j - i
            if switch_run >= sticky_n:
                cur = raw[i]
                streak = 1
                out[i] = cur
            else:
                # not enough persistence — stay
                out[i] = cur
    df['bull'] = out
    return df


def latest_fy_at_date(rd):
    rd = pd.Timestamp(rd)
    for y in range(rd.year, 1995, -1):
        avail = pd.Timestamp(year=y, month=3, day=31) + pd.DateOffset(months=REPORTING_LAG_MONTHS)
        if avail <= rd:
            return y
    return None


def load_fundamentals_wide():
    df = pd.read_parquet(FUND_PANEL)
    df = df[df['confidence'].isin(['high', 'verified'])]
    df = df[~df['catastrophic_outlier'].astype(bool)]
    df = df[~df['is_bank'].fillna(False).astype(bool)]
    df['_pref'] = df['basis'].apply(lambda b: 0 if b == 'consolidated' else 1)
    df = df.sort_values(['symbol', 'fiscal_year', 'line_item', '_pref'])
    df = df.drop_duplicates(subset=['symbol', 'fiscal_year', 'line_item'], keep='first')
    return df.pivot_table(index=['symbol', 'fiscal_year'], columns='line_item',
                             values='value', aggfunc='first').reset_index()


def check_hard_rules(row, cap_intensive_de_max=3.0):
    """Return True unless a rule fails explicitly. Missing data → don't fail."""
    cfo = row.get('cfo', np.nan)
    np_ = row.get('net_profit', np.nan)
    td = row.get('total_debt', np.nan)
    eq = row.get('equity', np.nan)
    if pd.notna(cfo) and cfo <= 0:
        return False
    if pd.notna(np_) and np_ <= 0:
        return False
    if pd.notna(td) and pd.notna(eq) and eq > 0:
        if (td / eq) > cap_intensive_de_max:
            return False
    return True


def compute_beta_vol(prices, sym, as_of_date, nifty_returns, window_days=250):
    """Rolling 250-day beta vs NIFTY and annualized vol."""
    sub = prices[(prices['symbol'] == sym) & (prices['Date'] < as_of_date)].tail(window_days)
    if len(sub) < window_days * 0.6:
        return None, None
    rets = sub['close'].pct_change().dropna()
    if len(rets) < 60:
        return None, None
    rets = rets.reset_index(drop=True)
    n_rets = nifty_returns.reindex(sub['Date']).pct_change().dropna().reset_index(drop=True)
    common = min(len(rets), len(n_rets))
    r = rets[-common:].reset_index(drop=True)
    m = n_rets[-common:].reset_index(drop=True)
    if r.std() == 0 or m.std() == 0:
        return None, None
    cov = np.cov(r, m)[0, 1]
    beta = cov / m.var() if m.var() > 0 else None
    vol = r.std() * np.sqrt(252)
    return beta, vol


def enforce_sector_cap(candidates, symbol_col, cap, target_size):
    """Given a ranked list of candidates (best first), take names respecting sector cap."""
    picks = []
    sector_count = {}
    for _, row in candidates.iterrows():
        sym = row[symbol_col]
        sec = get_sector(sym)
        if sector_count.get(sec, 0) >= cap:
            continue
        picks.append(sym)
        sector_count[sec] = sector_count.get(sec, 0) + 1
        if len(picks) >= target_size:
            break
    return picks


def select_bull_basket(scored, fund_wide, quality, rd, prev_holdings,
                          use_challenger=False, apply_hard_rules=True):
    """Bull basket: top-30 momentum with optional hard-rules filter + sector cap + buffering."""
    universe = scored[scored['rebalance_date'] == rd].copy()
    if universe.empty:
        return []
    universe = universe.sort_values('universe_rank_turnover').head(UNIVERSE_TOP_N)
    universe = universe.dropna(subset=['rank_composite_risk_adj'])
    universe['mom_rank'] = universe['rank_composite_risk_adj'].rank()

    fy = latest_fy_at_date(rd)
    fund_year = fund_wide[fund_wide['fiscal_year'] == fy].set_index('symbol')

    if apply_hard_rules:
        def passes(sym):
            if sym not in fund_year.index:
                return True  # no data → keep
            f = fund_year.loc[sym].to_dict()
            return check_hard_rules(f)
        universe['ok'] = universe['symbol'].apply(passes)
        universe = universe[universe['ok']]

    if use_challenger:
        # Re-rank by 0.7*mom_z + 0.3*qual_z
        qmap = quality.set_index(['symbol', 'rebalance_date'])['quality_percentile']
        universe['q_pct'] = universe['symbol'].apply(
            lambda s: qmap.get((s, rd), np.nan))
        universe['mom_z'] = ((universe['composite_risk_adj'] -
                               universe['composite_risk_adj'].mean()) /
                              universe['composite_risk_adj'].std())
        universe['q_z'] = (universe['q_pct'] - universe['q_pct'].mean()) / universe['q_pct'].std()
        universe['combined'] = 0.7 * universe['mom_z'] + 0.3 * universe['q_z'].fillna(0)
        universe['final_rank'] = universe['combined'].rank(ascending=False)
    else:
        universe['final_rank'] = universe['mom_rank']

    universe = universe.sort_values('final_rank')

    # Buffering: keep incumbents whose momentum rank still <= MOM_BUFFER_RANK
    if prev_holdings:
        incumbents = universe[universe['symbol'].isin(prev_holdings) &
                                  (universe['mom_rank'] <= MOM_BUFFER_RANK)]
        picks = enforce_sector_cap(incumbents, 'symbol', SECTOR_CAP_BULL,
                                       target_size=len(incumbents))
    else:
        picks = []

    # Backfill from remaining ranked candidates
    remaining = universe[~universe['symbol'].isin(picks)]
    need = N_BULL_HOLD - len(picks)
    if need > 0:
        # Apply sector cap accounting for already-picked
        sector_count = {get_sector(s): 0 for s in picks}
        for s in picks:
            sec = get_sector(s)
            sector_count[sec] = sector_count.get(sec, 0) + 1
        for _, row in remaining.iterrows():
            sym = row['symbol']
            sec = get_sector(sym)
            if sector_count.get(sec, 0) >= SECTOR_CAP_BULL:
                continue
            picks.append(sym)
            sector_count[sec] = sector_count.get(sec, 0) + 1
            if len(picks) >= N_BULL_HOLD:
                break
    return picks[:N_BULL_HOLD]


def select_bear_basket(quality, fund_wide, prices, rd, nifty_close_series,
                          beta_vol_cache=None):
    """Defensive basket: high quality + low vol + low beta + defensive-sector tilt."""
    q_at = quality[quality['rebalance_date'] == rd]
    if q_at.empty:
        return []
    q_at = q_at.dropna(subset=['quality_percentile'])
    q_at = q_at[q_at['quality_percentile'] >= DEF_MIN_QUALITY_PCT].copy()

    fy = latest_fy_at_date(rd)
    fund_year = fund_wide[fund_wide['fiscal_year'] == fy].set_index('symbol')

    # Hard rules
    def passes_hard(sym):
        if sym not in fund_year.index:
            return False  # DEFENSIVE: require data
        return check_hard_rules(fund_year.loc[sym].to_dict())
    q_at['ok'] = q_at['symbol'].apply(passes_hard)
    q_at = q_at[q_at['ok']]

    # Beta + vol filter (using cache to avoid recompute)
    def bv(sym):
        key = (sym, rd)
        if beta_vol_cache is not None and key in beta_vol_cache:
            return beta_vol_cache[key]
        b, v = compute_beta_vol(prices, sym, pd.Timestamp(rd), nifty_close_series)
        if beta_vol_cache is not None:
            beta_vol_cache[key] = (b, v)
        return b, v

    keep = []
    for sym in q_at['symbol']:
        b, v = bv(sym)
        if b is None or v is None:
            continue
        if b > DEF_MAX_BETA or v > DEF_MAX_VOL:
            continue
        keep.append({'symbol': sym, 'beta': b, 'vol': v,
                      'q_pct': q_at[q_at['symbol'] == sym]['quality_percentile'].iloc[0]})
    df = pd.DataFrame(keep)
    if df.empty:
        return []

    # Score: high quality + low beta + low vol + defensive sector tilt
    df['def_sector'] = df['symbol'].apply(is_defensive_sector).astype(int)
    # z-scores (winsorized-ish)
    for col in ['q_pct', 'beta', 'vol']:
        df[f'z_{col}'] = (df[col] - df[col].mean()) / (df[col].std() or 1)
    df['score'] = df['z_q_pct'] - df['z_beta'] - df['z_vol'] + 0.5 * df['def_sector']
    df = df.sort_values('score', ascending=False)

    picks = enforce_sector_cap(df, 'symbol', SECTOR_CAP_BEAR, N_BEAR_HOLD)
    return picks


def compute_period_return(prices, symbols, start_date, end_date):
    if not symbols:
        return np.nan
    sub = prices[prices['symbol'].isin(symbols)]
    rets = []
    for sym in symbols:
        sp = sub[sub['symbol'] == sym]
        after = sp[sp['Date'] > start_date]
        if after.empty:
            continue
        entry = after.iloc[0]['close']
        before_end = sp[sp['Date'] <= end_date]
        if before_end.empty:
            continue
        exit_ = before_end.iloc[-1]['close']
        if entry > 0 and exit_ > 0:
            rets.append(exit_ / entry - 1)
    return np.mean(rets) if rets else np.nan


def turnover(prev, curr):
    if not prev:
        return 1.0
    return len(set(prev).symmetric_difference(set(curr))) / (2 * max(len(prev), len(curr)))


def perf_metrics(returns_series, periods_per_year=2):
    r = pd.Series(returns_series).dropna()
    if r.empty:
        return {'CAGR': np.nan, 'AnnVol': np.nan, 'Sharpe': np.nan,
                'MaxDD': np.nan, 'HitRate': np.nan, 'N': 0}
    cum = (1 + r).cumprod()
    n = len(r)
    cagr = cum.iloc[-1] ** (periods_per_year / n) - 1 if n > 0 else np.nan
    ann_vol = r.std() * np.sqrt(periods_per_year)
    sharpe = (r.mean() * periods_per_year) / ann_vol if ann_vol > 0 else np.nan
    peak = cum.cummax()
    max_dd = (cum / peak - 1).min()
    return {'CAGR': cagr, 'AnnVol': ann_vol, 'Sharpe': sharpe,
            'MaxDD': max_dd, 'HitRate': (r > 0).mean(), 'N': n}


def identify_bear_windows(regime_daily):
    """Return list of (start, end) tuples for contiguous bear windows."""
    df = regime_daily.copy()
    df['bull_int'] = df['bull'].astype(int)
    df['grp'] = (df['bull_int'] != df['bull_int'].shift()).cumsum()
    windows = []
    for _, g in df.groupby('grp'):
        if not g['bull'].iloc[0]:
            windows.append((g.index[0], g.index[-1]))
    return windows


def run_variant(variant, scored, quality, fund_wide, prices, regime_sticky,
                    rebalance_dates, nifty_close, beta_vol_cache):
    """Run one variant. Returns dict with returns, holdings, turnover, cost drag, switch log."""
    period_returns_gross = []
    period_returns_net = []
    holdings_bull_list = []
    holdings_bear_list = []
    turnovers = []
    cost_drags = []
    period_regime = []  # 'bull' or 'bear' for the period
    switch_log = []  # (date, from, to, overlap, cost)

    cost_per_side = (COST_BPS_PER_SIDE + SLIPPAGE_BPS) / 10_000
    cost_per_side_grad = (COST_BPS_PER_SIDE + SLIPPAGE_BPS_GRADUAL) / 10_000

    prev_bull = []
    prev_bear = []
    prev_regime = None

    for i, rd in enumerate(rebalance_dates):
        rd_ts = pd.Timestamp(rd)
        end_rd = rebalance_dates[i+1] if i+1 < len(rebalance_dates) else pd.Timestamp('2026-05-30')

        # What's the regime at this rebalance?
        reg_at = regime_sticky.reindex([rd_ts], method='ffill')
        is_bull = bool(reg_at['bull'].iloc[0]) if not reg_at.empty else True
        period_regime.append('bull' if is_bull else 'bear')

        # Baseline: raw momentum top-30 (no hard rules)
        if variant == 'baseline':
            bull_picks = select_bull_basket(scored, fund_wide, quality, rd, prev_bull,
                                                 apply_hard_rules=False)
            bear_picks = []  # cash only
        elif variant == 'V1':
            bull_picks = select_bull_basket(scored, fund_wide, quality, rd, prev_bull,
                                                 apply_hard_rules=True)
            bear_picks = []
        elif variant == 'V2':
            bull_picks = select_bull_basket(scored, fund_wide, quality, rd, prev_bull,
                                                 apply_hard_rules=True)
            bear_picks = select_bear_basket(quality, fund_wide, prices, rd, nifty_close,
                                                  beta_vol_cache=beta_vol_cache)
        elif variant == 'V3':
            bull_picks = select_bull_basket(scored, fund_wide, quality, rd, prev_bull,
                                                 apply_hard_rules=True)
            bear_picks = select_bear_basket(quality, fund_wide, prices, rd, nifty_close,
                                                  beta_vol_cache=beta_vol_cache)
        elif variant == 'V4':
            bull_picks = select_bull_basket(scored, fund_wide, quality, rd, prev_bull,
                                                 apply_hard_rules=True)
            bear_picks = select_bear_basket(quality, fund_wide, prices, rd, nifty_close,
                                                  beta_vol_cache=beta_vol_cache)
        elif variant == 'challenger':
            bull_picks = select_bull_basket(scored, fund_wide, quality, rd, prev_bull,
                                                 apply_hard_rules=False, use_challenger=True)
            bear_picks = select_bear_basket(quality, fund_wide, prices, rd, nifty_close,
                                                  beta_vol_cache=beta_vol_cache)
        else:
            raise ValueError(variant)

        holdings_bull_list.append(bull_picks)
        holdings_bear_list.append(bear_picks)

        # Compute gross return
        if is_bull:
            r_gross = compute_period_return(prices, bull_picks, rd_ts, end_rd)
        else:
            if variant in ('baseline', 'V1'):
                # cash yield ~7% annual → half year
                r_gross = (1 + CASH_YIELD_ANNUAL) ** 0.5 - 1
            elif variant == 'V4':
                # 60/40 defensive/cash
                r_def = compute_period_return(prices, bear_picks, rd_ts, end_rd)
                r_cash = (1 + CASH_YIELD_ANNUAL) ** 0.5 - 1
                if pd.isna(r_def):
                    r_gross = r_cash
                else:
                    r_gross = BEAR_BLEND_DEFENSIVE * r_def + (1 - BEAR_BLEND_DEFENSIVE) * r_cash
            else:
                r_def = compute_period_return(prices, bear_picks, rd_ts, end_rd)
                r_gross = r_def if not pd.isna(r_def) else ((1 + CASH_YIELD_ANNUAL) ** 0.5 - 1)

        period_returns_gross.append(r_gross)

        # Compute turnover + costs
        # If regime changed → switch cost. Else → within-basket rebalance cost.
        cost = 0.0
        if prev_regime is None:
            # Initial: full buy of the active basket
            active = bull_picks if is_bull else bear_picks
            cost = 1.0 * cost_per_side  # one side, entering full basket
            turnovers.append(1.0)
        elif prev_regime == period_regime[-1]:
            # No regime change: only within-basket rebalancing
            active_prev = prev_bull if is_bull else prev_bear
            active_curr = bull_picks if is_bull else bear_picks
            t = turnover(active_prev, active_curr)
            turnovers.append(t)
            cost = t * cost_per_side * 2  # round-trip both sides
        else:
            # Regime SWITCHED
            active_prev = prev_bull if prev_regime == 'bull' else prev_bear
            active_curr = bull_picks if is_bull else bear_picks
            # Basket overlap: names in both prev and curr aren't traded
            overlap = set(active_prev) & set(active_curr)
            sold = set(active_prev) - overlap
            bought = set(active_curr) - overlap
            sold_frac = len(sold) / max(len(active_prev), 1)
            bought_frac = len(bought) / max(len(active_curr), 1)
            if variant in ('V3', 'V4', 'challenger'):
                # Gradual rotation → reduced slippage
                cost = (sold_frac + bought_frac) * cost_per_side_grad
            else:
                cost = (sold_frac + bought_frac) * cost_per_side
            turnovers.append((sold_frac + bought_frac) / 2)
            switch_log.append({'date': rd, 'from': prev_regime, 'to': period_regime[-1],
                                  'overlap_size': len(overlap), 'sold': len(sold),
                                  'bought': len(bought), 'cost': cost})

        cost_drags.append(cost)
        period_returns_net.append(r_gross - cost if not pd.isna(r_gross) else np.nan)

        prev_bull = bull_picks
        prev_bear = bear_picks
        prev_regime = period_regime[-1]

    return {
        'rebalance_date': rebalance_dates,
        'regime': period_regime,
        'gross': period_returns_gross,
        'net': period_returns_net,
        'turnover': turnovers,
        'cost_drag': cost_drags,
        'switch_log': pd.DataFrame(switch_log),
        'holdings_bull': holdings_bull_list,
        'holdings_bear': holdings_bear_list,
    }


def analyze_bear_episodes(regime_daily, prices, defensive_baskets_by_period,
                              rebalance_dates):
    """For each contiguous bear window, compare defensive basket vs cash+gold."""
    windows = identify_bear_windows(regime_daily)
    rows = []
    for start, end in windows:
        # Find the rebalance date closest to (before) start
        rd_before = [r for r in rebalance_dates if pd.Timestamp(r) <= start]
        if not rd_before:
            continue
        rd = rd_before[-1]
        picks = defensive_baskets_by_period.get(rd, [])
        if not picks:
            rows.append({'start': start, 'end': end, 'days': (end - start).days,
                          'defensive_return': None, 'cash_return': None, 'delta': None,
                          'notes': 'no_defensive_basket'})
            continue
        r_def = compute_period_return(prices, picks, start, end)
        days = (end - start).days
        r_cash = (1 + CASH_YIELD_ANNUAL) ** (days / 365) - 1
        delta = None if pd.isna(r_def) else r_def - r_cash
        rows.append({'start': start, 'end': end, 'days': days,
                      'defensive_return': r_def, 'cash_return': r_cash, 'delta': delta,
                      'n_holdings': len(picks)})
    return pd.DataFrame(rows)


def run_all(era_filter=None, label='full', sticky_n=STICKY_N_DAYS):
    global STICKY_N_DAYS
    saved_sticky = STICKY_N_DAYS
    STICKY_N_DAYS = sticky_n

    print(f"\n{'='*70}\nRUN: {label} (sticky_n={sticky_n})\n{'='*70}")

    scored = pd.read_parquet(SCORED_UNIVERSE)
    scored['rebalance_date'] = pd.to_datetime(scored['rebalance_date'])
    quality = pd.read_parquet(QUALITY_SCORES)
    quality['rebalance_date'] = pd.to_datetime(quality['rebalance_date'])
    fund_wide = load_fundamentals_wide()
    prices = pd.read_parquet(PRICES)
    prices['Date'] = pd.to_datetime(prices['Date'])
    close_col = 'Adj Close' if 'Adj Close' in prices.columns else 'Close'
    prices = prices[['symbol', 'Date', close_col]].rename(columns={close_col: 'close'})
    prices = prices.sort_values(['symbol', 'Date'])

    regime = load_regime_series()
    regime_sticky = apply_sticky(regime, sticky_n)

    # NIFTY 500 close for beta computation
    nifty_close = regime['CLOSE_INDEX_VAL'].copy()
    beta_vol_cache = {}

    rebalance_dates = sorted(scored['rebalance_date'].unique())
    if era_filter:
        rebalance_dates = [r for r in rebalance_dates if era_filter(r)]
    print(f"  Rebalance dates: {len(rebalance_dates)}")

    results = {}
    for variant in ['baseline', 'V1', 'V2', 'V3', 'V4', 'challenger']:
        print(f"  Running {variant}...")
        results[variant] = run_variant(variant, scored, quality, fund_wide, prices,
                                              regime_sticky, rebalance_dates, nifty_close,
                                              beta_vol_cache)

    # Print performance table
    print(f"\n=== PERFORMANCE (net of costs) ===")
    perf_rows = []
    for v, res in results.items():
        m = perf_metrics(res['net'])
        gm = perf_metrics(res['gross'])
        avg_turnover = np.mean([t for t in res['turnover'] if not pd.isna(t)])
        avg_cost = np.mean(res['cost_drag'])
        ann_cost = avg_cost * 2
        n_switches = len(res['switch_log'])
        total_switch_cost = res['switch_log']['cost'].sum() if not res['switch_log'].empty else 0
        perf_rows.append({
            'variant': v,
            'CAGR_gross': gm['CAGR'], 'CAGR_net': m['CAGR'],
            'AnnVol': m['AnnVol'], 'Sharpe': m['Sharpe'], 'MaxDD': m['MaxDD'],
            'HitRate': m['HitRate'], 'AnnTurnover': avg_turnover * 2,
            'AnnCostDrag': ann_cost, 'N_switches': n_switches,
            'TotalSwitchCost': total_switch_cost,
        })
    perf = pd.DataFrame(perf_rows)
    print(perf.to_string(index=False, float_format=lambda v: f"{v*100:6.2f}%" if abs(v) < 10 else f"{v:6.1f}"))
    perf.to_csv(os.path.join(OUT_DIR, f"performance_{label}.csv"), index=False)

    # Per-bear-episode attribution using V3's defensive baskets
    defensive_baskets = dict(zip(rebalance_dates, results['V3']['holdings_bear']))
    ep = analyze_bear_episodes(regime_sticky, prices, defensive_baskets, rebalance_dates)
    ep.to_csv(os.path.join(OUT_DIR, f"bear_episodes_{label}.csv"), index=False)
    print(f"\n=== BEAR-EPISODE ATTRIBUTION (defensive vs cash) ===")
    if ep.empty:
        print("  No bear windows.")
    else:
        for _, row in ep.iterrows():
            def_r = 'n/a' if pd.isna(row['defensive_return']) else f"{row['defensive_return']*100:+6.2f}%"
            csh_r = f"{row['cash_return']*100:+6.2f}%"
            dlt = 'n/a' if row['delta'] is None or pd.isna(row['delta']) else f"{row['delta']*100:+6.2f}%"
            print(f"  {row['start'].strftime('%Y-%m-%d')} → "
                    f"{row['end'].strftime('%Y-%m-%d')}  ({row['days']:4d}d)  "
                    f"def={def_r}  cash={csh_r}  Δ={dlt}")
        n_beat = ((ep['delta'] > 0)).sum()
        n_valid = ep['delta'].notna().sum()
        print(f"\n  Defensive beat cash in {n_beat}/{n_valid} bear windows.")
        if n_valid > 0:
            avg_delta = ep['delta'].dropna().mean()
            print(f"  Mean delta: {avg_delta*100:+.2f}% per bear window")

    # Save
    for v, res in results.items():
        df = pd.DataFrame({
            'rebalance_date': res['rebalance_date'],
            'regime': res['regime'],
            'gross_return': res['gross'],
            'net_return': res['net'],
            'turnover': res['turnover'],
            'cost_drag': res['cost_drag'],
        })
        df.to_parquet(os.path.join(OUT_DIR, f"variant_{v}_{label}.parquet"), index=False)
        if not res['switch_log'].empty:
            res['switch_log'].to_csv(
                os.path.join(OUT_DIR, f"switch_log_{v}_{label}.csv"), index=False)

    STICKY_N_DAYS = saved_sticky
    return results, perf, ep


if __name__ == '__main__':
    full = run_all(era_filter=None, label='full')
    post = run_all(era_filter=lambda r: r >= pd.Timestamp('2014-12-31'),
                       label='post2014')

    print("\n\n=== SENSITIVITY: sticky_n ===")
    sens = []
    for n in [5, 7, 10]:
        _, perf, _ = run_all(era_filter=lambda r: r >= pd.Timestamp('2014-12-31'),
                                 label=f'sens_sticky{n}', sticky_n=n)
        for _, row in perf.iterrows():
            sens.append({'sticky_n': n, 'variant': row['variant'],
                          'CAGR_net': row['CAGR_net'], 'Sharpe': row['Sharpe'],
                          'MaxDD': row['MaxDD']})
    pd.DataFrame(sens).to_csv(os.path.join(OUT_DIR, "sensitivity_sticky.csv"),
                                  index=False)
    print("\nSensitivity saved.")

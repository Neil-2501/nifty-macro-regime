"""V6: Persistence-gated defensive-quality sleeve overlaid on Config 7.

Runs Config 7 UNCHANGED via strategy.py, then post-processes its daily
positions/returns:
  - Identify stress-flat latches (nifty_position == 0 runs)
  - After N days of persistence, swap gold/cash return with defensive-basket
    daily return (or blend 50/50 with gold/cash)
  - Charge real basket trading costs + STCG tax on entries/exits

Config 7 baseline is preserved byte-for-byte when sleeve is disabled
(sleeve_alloc = 0).
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings('ignore')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reuse the defensive-basket selector
import backtest_defensive_rotation as brd

# Import production strategy
import strategy as prod

OUT_DIR = os.path.join(REPO_ROOT, "data", "defensive_sleeve_v6")
os.makedirs(OUT_DIR, exist_ok=True)

# Tax model — Indian STCG on equity held < 1 year
STCG_RATE_PRE_JUL2024 = 0.15
STCG_RATE_POST_JUL2024 = 0.20
STCG_CHANGE_DATE = pd.Timestamp('2024-07-23')

# Basket-side cost per side (real, not the 3 bps NIFTY ETF cost)
BASKET_COST_BPS_PER_SIDE = 30  # 15 brokerage/STT + 15 slippage


def load_all_data():
    """Fetch the same raw data as prod.strategy uses + our stock prices + universe."""
    print("Loading raw price data (yfinance + local CSVs)...", flush=True)
    WARMUP = "2006-01-01"
    END_FETCH = "2026-06-15"
    TICKERS = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS", "^TNX"]
    raw = yf.download(TICKERS, start=WARMUP, end=END_FETCH,
                        auto_adjust=True, progress=False)["Close"]
    raw.dropna(how='all', inplace=True)
    for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
        if col in raw.columns:
            raw[col] = raw[col].ffill()
    if "GOLDBEES.NS" in raw.columns:
        first_valid = raw["GOLDBEES.NS"].first_valid_index()
        if first_valid is not None:
            mask = raw.index >= first_valid
            raw.loc[mask, "GOLDBEES.NS"] = raw.loc[mask, "GOLDBEES.NS"].ffill()

    # Local NSE index CSVs (Mom30, Midcap 150, Smallcap 250)
    for csv_name, col in [
        ("data/midcap150_history.csv", "NIFTYMIDCAP150"),
        ("data/momentum30_history.csv", "NIFTYMOM30"),
        ("data/smallcap250_history.csv", "NIFTYSMALLCAP250"),
    ]:
        path = os.path.join(REPO_ROOT, csv_name)
        if os.path.exists(path):
            series = prod.load_nse_index_csv(path, col)
            raw[col] = series.reindex(raw.index).ffill()

    # Stock prices for the basket
    print("Loading stock price panel...", flush=True)
    prices = pd.read_parquet(os.path.join(REPO_ROOT, "data", "yfinance_bulk",
                                             "adjusted_prices_panel.parquet"))
    prices['Date'] = pd.to_datetime(prices['Date'])
    close_col = 'Adj Close' if 'Adj Close' in prices.columns else 'Close'
    prices = prices[['symbol', 'Date', close_col]].rename(columns={close_col: 'close'})
    prices = prices.sort_values(['symbol', 'Date'])

    # Quality + fundamentals + scored universe (needed for basket selection)
    quality = pd.read_parquet(os.path.join(REPO_ROOT, "data", "quality_factor",
                                              "quality_scores_pit.parquet"))
    quality['rebalance_date'] = pd.to_datetime(quality['rebalance_date'])
    fund_wide = brd.load_fundamentals_wide()
    scored = pd.read_parquet(brd.SCORED_UNIVERSE)
    scored['rebalance_date'] = pd.to_datetime(scored['rebalance_date'])

    return raw, prices, quality, fund_wide, scored


def run_config7(raw):
    """Run Config 7 UNCHANGED. Return the strategy result DataFrame."""
    print("Running Config 7 (unchanged, from strategy.py)...", flush=True)
    combiner = prod.make_combiner(True, False, use_momentum_gold=True,
                                       slow_stress_lock_days=5,
                                       panic_short_dd_threshold=0.15)
    s = prod.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                              long_target="NIFTYMOM30", long_cost_bps=6,
                              enable_v2=True, v2_dd_threshold=0.15, v2_days=60)
    r = s.run(raw).loc['2008-04-01':'2026-06-15']
    return r


def compute_defensive_basket_holdings(quality, fund_wide, prices, nifty_close):
    """For each rebalance date, compute the defensive basket (list of symbols)."""
    rebalance_dates = sorted(quality['rebalance_date'].unique())
    holdings = {}
    beta_vol_cache = {}
    for rd in rebalance_dates:
        picks = brd.select_bear_basket(quality, fund_wide, prices, rd, nifty_close,
                                              beta_vol_cache=beta_vol_cache)
        holdings[rd] = picks
    return holdings, rebalance_dates


def compute_daily_basket_returns(holdings, rebalance_dates, prices,
                                    date_index):
    """One value per day = equal-weighted return of the CURRENT-PERIOD basket.
    Zero on days when we're between rebalances or don't have prices."""
    # Prices as wide (symbol × date) for fast lookup
    price_wide = prices.pivot_table(index='Date', columns='symbol', values='close', aggfunc='last')
    price_wide = price_wide.reindex(date_index).ffill()
    daily_ret_wide = price_wide.pct_change().fillna(0)

    daily_basket_ret = pd.Series(0.0, index=date_index, name='basket_ret')
    for i, rd in enumerate(rebalance_dates):
        end = rebalance_dates[i+1] if i+1 < len(rebalance_dates) else date_index[-1]
        period_mask = (date_index > pd.Timestamp(rd)) & (date_index <= pd.Timestamp(end))
        picks = holdings.get(rd, [])
        if not picks:
            continue
        cols = [s for s in picks if s in daily_ret_wide.columns]
        if not cols:
            continue
        # Equal-weighted daily return
        basket_ret = daily_ret_wide.loc[period_mask, cols].mean(axis=1)
        daily_basket_ret.loc[period_mask] = basket_ret.values
    return daily_basket_ret, price_wide


def build_variant_daily_returns(cfg7_daily, daily_basket_ret, persistence_n,
                                   sleeve_alloc):
    """Post-process Config 7's daily returns with the persistence-gated sleeve.

    cfg7_daily columns needed: nifty_position, gold_position, nifty_return,
    gold_return, cash_return, strategy_return.

    Rule: identify stress-flat latches (nifty_position == 0.0 continuous runs).
    Within each latch:
      - Days 1..N: use Config 7's return for that day (no change)
      - Days N+1..end: swap the day's flat/gold return with:
          100% defensive: use basket_ret
          50/50:          use 0.5*basket_ret + 0.5*(cfg7_flat_return)

    Non-latch days (long or short): return unchanged.
    """
    df = cfg7_daily.copy()
    df['basket_ret'] = daily_basket_ret.reindex(df.index).fillna(0)
    df['sleeve_active'] = False
    df['days_in_latch'] = 0

    # A latch = contiguous run where nifty_position == 0
    is_flat = (df['nifty_position'] == 0.0).values
    latch_id = np.zeros(len(df), dtype=int)
    day_in_latch = np.zeros(len(df), dtype=int)
    cur_id = 0; cur_day = 0
    for i in range(len(df)):
        if is_flat[i]:
            if i == 0 or not is_flat[i-1]:
                cur_id += 1; cur_day = 1
            else:
                cur_day += 1
            latch_id[i] = cur_id
            day_in_latch[i] = cur_day
        else:
            cur_day = 0
    df['latch_id'] = latch_id
    df['days_in_latch'] = day_in_latch

    # Sleeve fires on days after persistence_n days in the current latch
    sleeve_days = (day_in_latch > persistence_n) & is_flat
    df['sleeve_active'] = sleeve_days

    # Compute the strategy return under the variant
    # Config 7's daily return already includes: nifty/mom30 * nifty_pos, gold * gold_pos,
    # cash yield on flat, minus costs. We need to REPLACE the gold+cash portion of the
    # return on sleeve_days with the basket return (net of basket costs and STCG).
    # cfg7_daily gives us 'strategy_return' as the composite. On sleeve days we want to
    # replace the "flat portion" — approximated as (strategy_return WITHOUT the long lane)
    # since nifty_position==0 during the latch.
    variant_ret = df['strategy_return'].values.copy()

    # On sleeve days, replace the day's return with sleeve return
    # sleeve return = basket_ret * alloc + (cfg7 flat return) * (1-alloc)
    # cfg7 flat return on a stress-flat day = whatever's in strategy_return (since nifty=0)
    # (already excludes long-side contribution because pos=0)
    for i in np.where(sleeve_days)[0]:
        basket_r = df['basket_ret'].iloc[i]
        original = variant_ret[i]  # gold or cash return that day, net of gold cost
        variant_ret[i] = sleeve_alloc * basket_r + (1 - sleeve_alloc) * original

    df['variant_return_gross'] = variant_ret

    # Basket cost + STCG on sleeve entries/exits
    # Simplified: at each transition from non-sleeve to sleeve, charge sleeve_alloc * cost_per_side
    # At each transition from sleeve to non-sleeve, charge sleeve_alloc * cost_per_side + STCG on gains
    # Assume all sleeve holdings are STCG (<1yr held), 15% pre Jul-24, 20% post.
    cost_per_side = BASKET_COST_BPS_PER_SIDE / 10_000
    df['variant_return_net'] = variant_ret.copy()

    # Track sleeve entries/exits + realized gains
    sleeve_active_arr = sleeve_days.copy()
    for i in range(1, len(df)):
        if sleeve_active_arr[i] and not sleeve_active_arr[i-1]:
            # entry — buy sleeve fraction
            df.iloc[i, df.columns.get_loc('variant_return_net')] -= sleeve_alloc * cost_per_side
        elif not sleeve_active_arr[i] and sleeve_active_arr[i-1]:
            # exit — sell sleeve fraction + STCG
            # Approximate STCG on the sleeve's cumulative return over the sleeve run
            # Find the sleeve run
            j = i - 1
            while j > 0 and sleeve_active_arr[j-1]:
                j -= 1
            run_returns = variant_ret[j:i]  # daily returns during sleeve run
            cum_run_ret = np.prod(1 + run_returns) - 1
            gain_frac = sleeve_alloc * cum_run_ret if cum_run_ret > 0 else 0
            stcg_rate = STCG_RATE_POST_JUL2024 if df.index[i] >= STCG_CHANGE_DATE else STCG_RATE_PRE_JUL2024
            tax = gain_frac * stcg_rate
            df.iloc[i, df.columns.get_loc('variant_return_net')] -= sleeve_alloc * cost_per_side + tax

    return df


def perf_metrics(returns_daily, label=''):
    r = pd.Series(returns_daily).dropna()
    if r.empty:
        return {'CAGR': np.nan, 'AnnVol': np.nan, 'Sharpe': np.nan,
                'MaxDD': np.nan, 'HitRate': np.nan, 'N_days': 0}
    cum = (1 + r).cumprod()
    days = len(r)
    years = days / 252
    cagr = cum.iloc[-1] ** (1/years) - 1 if years > 0 else np.nan
    ann_vol = r.std() * np.sqrt(252)
    sharpe = (r.mean() * 252) / ann_vol if ann_vol > 0 else np.nan
    max_dd = (cum / cum.cummax() - 1).min()
    return {'CAGR': cagr, 'AnnVol': ann_vol, 'Sharpe': sharpe,
            'MaxDD': max_dd, 'HitRate': (r > 0).mean(), 'N_days': days,
            'years': years}


def episode_attribution(cfg7_daily, variant_daily, persistence_n, sleeve_alloc):
    """For each stress-flat latch, report basket-vs-baseline delta."""
    df = variant_daily.copy()
    episodes = []
    latch_ids = df['latch_id'].unique()
    for lid in latch_ids:
        if lid == 0:
            continue
        mask = df['latch_id'] == lid
        sub = df[mask]
        if sub.empty:
            continue
        start = sub.index[0]
        end = sub.index[-1]
        days = len(sub)
        # Config 7 return over the episode (from cfg7_daily)
        cfg7_ret = (1 + cfg7_daily.loc[start:end, 'strategy_return']).prod() - 1
        # Variant return
        var_ret = (1 + sub['variant_return_net']).prod() - 1
        # Only apply sleeve if days > persistence_n
        sleeve_days = int(sub['sleeve_active'].sum())
        episodes.append({
            'latch_id': int(lid), 'start': start, 'end': end, 'days': days,
            'cfg7_return': cfg7_ret, 'variant_return': var_ret,
            'delta': var_ret - cfg7_ret, 'sleeve_days': sleeve_days,
        })
    return pd.DataFrame(episodes)


def slice_range(df, start, end):
    return df.loc[start:end]


def main():
    print("=" * 70)
    print("V6 PERSISTENCE-GATED DEFENSIVE SLEEVE")
    print("=" * 70)

    raw, prices, quality, fund_wide, scored = load_all_data()

    print(f"\nRaw data spans: {raw.index.min().date()} → {raw.index.max().date()}")
    print(f"NIFTYMOM30 last valid: {raw['NIFTYMOM30'].last_valid_index().date() if 'NIFTYMOM30' in raw else 'MISSING'}")

    cfg7 = run_config7(raw)
    print(f"Config 7 output range: {cfg7.index.min().date()} → {cfg7.index.max().date()}")
    print(f"Config 7 columns: {list(cfg7.columns)}")

    # Compute defensive basket per rebalance
    print("\nComputing defensive basket per rebalance date...", flush=True)
    nifty_close_regime = raw['^NSEI'].copy()
    holdings, rebalance_dates = compute_defensive_basket_holdings(
        quality, fund_wide, prices, nifty_close_regime)
    print(f"  {len(rebalance_dates)} rebalance dates, sample basket: {list(holdings[rebalance_dates[-1]])[:5]}...")

    # Daily basket returns
    daily_basket_ret, _ = compute_daily_basket_returns(holdings, rebalance_dates,
                                                              prices, cfg7.index)
    print(f"  Daily basket returns computed for {daily_basket_ret.ne(0).sum():,} non-zero days")

    # Full history + OOS windows
    windows = {
        'full': (cfg7.index.min(), pd.Timestamp('2026-05-11')),
        'oos':  (pd.Timestamp('2017-01-01'), pd.Timestamp('2026-05-11')),
    }

    all_variant_metrics = []
    all_episodes = []

    # Baseline (Config 7 unchanged)
    for w_label, (w_start, w_end) in windows.items():
        m = perf_metrics(slice_range(cfg7, w_start, w_end)['strategy_return'])
        all_variant_metrics.append({
            'variant': 'baseline_cfg7', 'window': w_label,
            'N': None, 'alloc': None, **m,
        })

    # 8 variants
    variants = [
        ('V6a', 0,  1.0),  ('V6b', 0,  0.5),
        ('V6c', 10, 1.0),  ('V6d', 10, 0.5),
        ('V6e', 20, 1.0),  ('V6f', 20, 0.5),
        ('V6g', 40, 1.0),  ('V6h', 40, 0.5),
    ]
    variant_dailies = {}
    for vlabel, N, alloc in variants:
        print(f"\nRunning {vlabel} (N={N}, alloc={alloc})...", flush=True)
        vd = build_variant_daily_returns(cfg7, daily_basket_ret, N, alloc)
        variant_dailies[vlabel] = vd
        for w_label, (w_start, w_end) in windows.items():
            sub = slice_range(vd, w_start, w_end)
            m_gross = perf_metrics(sub['variant_return_gross'])
            m_net = perf_metrics(sub['variant_return_net'])
            # Cost & tax drag = gross - net (annualized)
            days_sleeve = int(sub['sleeve_active'].sum())
            n_deployments = int((sub['sleeve_active'].astype(int).diff() > 0).sum())
            all_variant_metrics.append({
                'variant': vlabel, 'window': w_label, 'N': N, 'alloc': alloc,
                'CAGR': m_net['CAGR'], 'CAGR_gross': m_gross['CAGR'],
                'AnnVol': m_net['AnnVol'], 'Sharpe': m_net['Sharpe'],
                'MaxDD': m_net['MaxDD'], 'HitRate': m_net['HitRate'],
                'sleeve_days': days_sleeve, 'n_deployments': n_deployments,
                'cost_tax_drag_pp': (m_gross['CAGR'] - m_net['CAGR']) * 100
                                          if m_gross['CAGR'] is not None else np.nan,
                'N_days': m_net['N_days'],
            })
        # Per-episode attribution (full window)
        ep = episode_attribution(cfg7, vd, N, alloc)
        ep['variant'] = vlabel
        all_episodes.append(ep)

    metrics_df = pd.DataFrame(all_variant_metrics)
    metrics_df.to_csv(os.path.join(OUT_DIR, "metrics.csv"), index=False)

    ep_df = pd.concat(all_episodes, ignore_index=True) if all_episodes else pd.DataFrame()
    ep_df.to_csv(os.path.join(OUT_DIR, "episodes.csv"), index=False)

    # === REPORT ===
    print("\n" + "=" * 70)
    print("VARIANT PERFORMANCE")
    print("=" * 70)
    print(f"\nWindow labeling: 2025-12-31 rebalance → 2026-05-11 is PARTIAL (~4.5 months, NOT annualized).\n")

    baseline_full = metrics_df[(metrics_df['variant'] == 'baseline_cfg7') &
                                     (metrics_df['window'] == 'full')].iloc[0]
    baseline_oos = metrics_df[(metrics_df['variant'] == 'baseline_cfg7') &
                                    (metrics_df['window'] == 'oos')].iloc[0]

    for w_label in ['full', 'oos']:
        w_display = 'FULL (2008-2026)' if w_label == 'full' else 'OOS (2017-2026)'
        print(f"\n--- {w_display} ---")
        sub = metrics_df[metrics_df['window'] == w_label].copy()
        base = baseline_full if w_label == 'full' else baseline_oos
        sub['delta_CAGR_pp'] = (sub['CAGR'] - base['CAGR']) * 100
        sub['delta_Sharpe'] = sub['Sharpe'] - base['Sharpe']
        cols = ['variant', 'N', 'alloc', 'CAGR', 'Sharpe', 'MaxDD',
                'sleeve_days', 'n_deployments', 'cost_tax_drag_pp',
                'delta_CAGR_pp', 'delta_Sharpe']
        print(sub[cols].to_string(index=False,
                                       float_format=lambda v: f"{v*100:6.2f}%" if abs(v) < 5 else f"{v:6.1f}"))

    # Highlight winners
    full_variants = metrics_df[(metrics_df['window'] == 'full') &
                                     (metrics_df['variant'] != 'baseline_cfg7')].copy()
    full_variants['delta_CAGR_pp'] = (full_variants['CAGR'] - baseline_full['CAGR']) * 100
    full_variants['delta_Sharpe'] = full_variants['Sharpe'] - baseline_full['Sharpe']
    winners = full_variants[full_variants['delta_CAGR_pp'] > 0].sort_values(
        'delta_CAGR_pp', ascending=False)

    print("\n" + "=" * 70)
    print("WINNERS (full history, net after real costs + tax)")
    print("=" * 70)
    if winners.empty:
        print("  NONE — no persistence-gated variant beats Config 7 baseline after costs + tax.")
    else:
        for _, r in winners.iterrows():
            print(f"  {r['variant']} (N={int(r['N']) if pd.notna(r['N']) else 'n/a'}, "
                  f"alloc={r['alloc']*100:.0f}%): "
                  f"CAGR {r['CAGR']*100:.2f}% (Δ {r['delta_CAGR_pp']:+.2f}pp)  "
                  f"Sharpe {r['Sharpe']:.2f} (Δ {r['delta_Sharpe']:+.2f})")

    # Persistence-effect summary
    print("\n" + "=" * 70)
    print("DOES GATING HELP? (higher N = more selective)")
    print("=" * 70)
    for alloc in [1.0, 0.5]:
        alloc_pct = int(alloc * 100)
        print(f"\n  Allocation {alloc_pct}% defensive:")
        for n in [0, 10, 20, 40]:
            v = full_variants[(full_variants['N'] == n) & (full_variants['alloc'] == alloc)]
            if not v.empty:
                r = v.iloc[0]
                print(f"    N={n:3d}: CAGR {r['CAGR']*100:6.2f}% (Δ {r['delta_CAGR_pp']:+.2f}pp)  "
                      f"MaxDD {r['MaxDD']*100:.2f}%  sleeve_days={int(r['sleeve_days'])}  n_deploy={int(r['n_deployments'])}")

    # Save daily returns for each variant
    for vlabel, vd in variant_dailies.items():
        vd[['strategy_return', 'variant_return_gross', 'variant_return_net',
             'sleeve_active', 'basket_ret', 'days_in_latch']].to_parquet(
            os.path.join(OUT_DIR, f"daily_{vlabel}.parquet"))
    cfg7.to_parquet(os.path.join(OUT_DIR, "daily_baseline_cfg7.parquet"))

    print(f"\n\nAll outputs saved to: {OUT_DIR}")


if __name__ == '__main__':
    main()

"""Momentum-basket bake-off V2 — MOMENTUM-RANK then QUALITY-GATE (filter, not blend).

Iteration from momentum_basket_bakeoff.py:
  V1 (pure momentum) LOSES vs the Mom30 index in all 8 grid cells.
  V2 tries: rank by momentum, then FILTER OUT names that fail a quality gate;
            backfill from the next momentum names to reach N=30.
  Also test WIDER UNIVERSE (top-500 vs top-200).

Grid (12 momentum-basket variants):
  universe    ∈ {top-200, top-500}
  quality_gate ∈ {none, hard_rules, hard_rules+pct>=50}
  buffer      ∈ {45, 60}
Tune free params on 2008-2016 IS, lock, apply 2017-2026 OOS.

Everything else identical to V1: same overlay architecture, same defensive-basket
overlay ON (V7 basket_cash_blend N=40 50/50), same identity-check discipline.

IC1. Momentum swap OFF, defensive OFF  → reproduce Config 7 exactly
IC2. Momentum swap OFF, defensive ON   → reproduce V7 basket_cash_blend
IC3. Momentum swap ON with my_basket=Mom30 → reproduce cfg7_no_gold exactly

Slippage caveat (top-500 universe): real-world slippage on illiquid mid/small
caps likely > 30 bps/side. Flag broad-universe gains as "before extra slippage".
"""
from __future__ import annotations

import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backtest_defensive_rotation as brd    # check_hard_rules, latest_fy_at_date, load_fundamentals_wide
import defensive_sleeve_v6 as v6
import strategy as prod

OUT_DIR = os.path.join(REPO_ROOT, "data", "momentum_basket_bakeoff_v2")
os.makedirs(OUT_DIR, exist_ok=True)

MOM30_COST_BPS = 6
BASKET_COST_BPS_PER_SIDE = 30
DEFENSIVE_COST_BPS_PER_SIDE = 30
STCG_PRE  = 0.15
STCG_POST = 0.20
STCG_CHANGE_DATE = pd.Timestamp('2024-07-23')
TAX_RATE = 0.15

END_FULL = pd.Timestamp('2026-05-11')
IS_END   = pd.Timestamp('2016-12-31')
OOS_START = pd.Timestamp('2017-01-01')

DEFENSIVE_N = 40
DEFENSIVE_ALLOC = 0.5

N_HOLD = 30                              # basket size
DE_MAX = 2.0                             # hard-rules D/E cap
QUALITY_PCT_MIN = 0.50                   # top-half quality

ETF_PATTERNS = ['GOLD', 'SILVER', 'SILV', 'BEES', 'NIFTY', 'BANKN', 'LIQUID',
                'NAV', 'IETF', 'NIFTYIETF', 'GOLDIETF', 'SETFGOLD',
                'JGOLD', 'MAFANG', 'CPSE', 'PSU', 'MOM100']


def _is_etf(sym: str) -> bool:
    s = str(sym).upper()
    return any(p in s for p in ETF_PATTERNS)


# ----------------------------------------------------------------------------
# Config 7 native
# ----------------------------------------------------------------------------
def run_cfg7(raw, rotate_stress=True, use_g10_gate=True, use_momentum_gold=True):
    combiner = prod.make_combiner(
        rotate_stress=rotate_stress, rotate_panic=False,
        use_momentum_gold=use_momentum_gold, gold_gate_external=use_g10_gate,
        slow_stress_lock_days=5, panic_short_dd_threshold=0.15,
    )
    strat = prod.MacroStrategy(
        combiner, nifty_cost_bps=3, gold_cost_bps=5,
        long_target="NIFTYMOM30", long_cost_bps=MOM30_COST_BPS,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
    )
    return strat.run(raw).loc['2008-04-01':'2026-06-15']


# ----------------------------------------------------------------------------
# Quality-gated momentum basket selection
# ----------------------------------------------------------------------------
def build_gate_lookups(fund_wide, quality_scored):
    """Prepare per-fiscal-year fundamentals lookup + per-rebalance quality-percentile lookup.
    quality_scored is quality_scored_universe.parquet, which has `quality_score` and
    `rank_quality` (raw). We derive percentile within the subset of names that have
    a non-null quality_score at each rebalance.
    """
    fund_by_fy = {}
    for fy, grp in fund_wide.groupby('fiscal_year'):
        fund_by_fy[int(fy)] = grp.set_index('symbol')

    quality_by_rd = {}
    for rd, grp in quality_scored.groupby('rebalance_date'):
        sub = grp.dropna(subset=['quality_score']).copy()
        # Derive percentile from quality_score (higher = better). Rank ascending
        # then divide by n; top name gets ~1.0, bottom gets ~1/n.
        if not sub.empty:
            sub['q_pct_derived'] = sub['quality_score'].rank(pct=True, ascending=True)
            quality_by_rd[pd.Timestamp(rd)] = sub.set_index('symbol')

    return fund_by_fy, quality_by_rd


def passes_gate(sym, rd, fund_by_fy, quality_by_rd, gate_kind: str) -> bool:
    """gate_kind ∈ {'none', 'hard_rules', 'hard_rules_pct'}
    STRICT: missing data → fail (except 'none').
    """
    if gate_kind == 'none':
        return True

    fy = brd.latest_fy_at_date(rd)
    fund_year = fund_by_fy.get(int(fy))
    if fund_year is None or sym not in fund_year.index:
        return False
    hard_ok = brd.check_hard_rules(fund_year.loc[sym].to_dict(), cap_intensive_de_max=DE_MAX)
    if not hard_ok:
        return False

    if gate_kind == 'hard_rules':
        return True

    if gate_kind == 'hard_rules_pct':
        q_rd = quality_by_rd.get(pd.Timestamp(rd))
        if q_rd is None or sym not in q_rd.index:
            return False
        q_pct = q_rd.loc[sym].get('q_pct_derived', np.nan)
        if pd.isna(q_pct):
            return False
        return q_pct >= QUALITY_PCT_MIN

    raise ValueError(f'Unknown gate {gate_kind}')


def select_quality_gated_momentum(scored, quality_scored, fund_wide,
                                   rebalance_dates,
                                   universe: int, gate_kind: str, buf: int,
                                   N: int = N_HOLD):
    """Return {rebalance_date: {symbol: 1/N}}.

    universe   — top-N liquid (universe_rank_turnover <= universe)
    gate_kind  — 'none' | 'hard_rules' | 'hard_rules_pct'
    buf        — retain an incumbent if still ranked in top-`buf` momentum
                 within the eligible pool (post-universe, post-gate).
    """
    fund_by_fy, quality_by_rd = build_gate_lookups(fund_wide, quality_scored)
    baskets = {}
    prev_holdings = []      # ordered list preserving prior weight order

    for rd in rebalance_dates:
        rd_ts = pd.Timestamp(rd)
        sub = scored[scored['rebalance_date'] == rd_ts].copy()
        # Universe filter
        sub = sub[sub['universe_rank_turnover'] <= universe]
        # Exclude ETF-like names
        sub = sub[~sub['symbol'].map(_is_etf)]
        # Sort by momentum score DESC (best first)
        sub = sub.sort_values('composite_risk_adj', ascending=False).reset_index(drop=True)
        # Apply quality gate — walk down and keep passers
        sub['gate_ok'] = [passes_gate(s, rd_ts, fund_by_fy, quality_by_rd, gate_kind)
                          for s in sub['symbol']]
        eligible = sub[sub['gate_ok']].reset_index(drop=True)
        eligible['rank_local'] = np.arange(1, len(eligible) + 1)

        if len(eligible) < N:
            # very rare — pad with next non-gated names to reach N
            missing = N - len(eligible)
            fill = sub[~sub['gate_ok']].head(missing)['symbol'].tolist()
            picks = eligible['symbol'].tolist() + fill
        else:
            # Buffered incumbent retention
            elig_set = set(eligible['symbol'].tolist())
            buffer_set = set(eligible.head(buf)['symbol'].tolist())
            top_N_set = eligible.head(N)['symbol'].tolist()

            # Preserve prev holdings still in buffer + eligible; fill from top_N
            held = [s for s in prev_holdings if s in elig_set and s in buffer_set]
            new_names = [s for s in top_N_set if s not in held]
            picks = held + new_names
            picks = picks[:N]

        w = {s: 1.0 / len(picks) for s in picks}
        baskets[rd_ts] = w
        prev_holdings = picks

    return baskets


# ----------------------------------------------------------------------------
# Daily basket returns
# ----------------------------------------------------------------------------
def compute_basket_daily_returns(baskets: dict, prices_wide: pd.DataFrame,
                                 date_index: pd.DatetimeIndex):
    rebalance_dates = sorted(baskets.keys())
    daily_ret = pd.Series(0.0, index=date_index)
    turnover_by_reb = {}

    all_symbols = set()
    for w in baskets.values():
        all_symbols.update(w.keys())
    cols_all = [s for s in all_symbols if s in prices_wide.columns]
    all_ret = prices_wide[cols_all].pct_change().fillna(0)

    prev_w = pd.Series(dtype=float)
    for i, rd in enumerate(rebalance_dates):
        end = rebalance_dates[i+1] if i+1 < len(rebalance_dates) else date_index[-1] + pd.Timedelta(days=1)
        w = pd.Series(baskets[rd])
        all_syms = prev_w.index.union(w.index)
        pv = prev_w.reindex(all_syms).fillna(0)
        cv = w.reindex(all_syms).fillna(0)
        turnover_by_reb[rd] = float((pv - cv).abs().sum() / 2)
        prev_w = w

        period = (date_index > pd.Timestamp(rd)) & (date_index <= pd.Timestamp(end))
        if not period.any():
            continue
        cols = [s for s in w.index if s in all_ret.columns]
        if not cols:
            continue
        weights = pd.Series({s: w[s] for s in cols})
        weights = weights / weights.sum()
        basket_r = all_ret.loc[period, cols] @ weights
        daily_ret.loc[period] = basket_r.values

    return daily_ret, turnover_by_reb


# ----------------------------------------------------------------------------
# Swap into pretax + tax
# ----------------------------------------------------------------------------
def build_swap_pretax(cfg7, raw, my_basket_daily_ret, turnover_by_reb, rebalance_dates,
                       my_cost_bps_per_side: float):
    active = (cfg7['long_mom_default'] & ~cfg7['composition_swap_active']).astype(float)
    mom30_ret = raw['NIFTYMOM30'].reindex(cfg7.index).pct_change().fillna(0)

    mom30_pnl  = active.shift(1).fillna(0) * mom30_ret
    mom30_cost = active.diff().abs().fillna(0) * (MOM30_COST_BPS / 10_000)

    my_pnl     = active.shift(1).fillna(0) * my_basket_daily_ret.reindex(cfg7.index).fillna(0)
    my_entry_exit_cost = active.diff().abs().fillna(0) * (my_cost_bps_per_side / 10_000)

    my_rebal_cost = pd.Series(0.0, index=cfg7.index)
    for rd, tvr in turnover_by_reb.items():
        rd = pd.Timestamp(rd)
        candidate_days = cfg7.index[cfg7.index >= rd]
        if len(candidate_days) == 0:
            continue
        day = candidate_days[0]
        if active.loc[day] == 1.0:
            my_rebal_cost.loc[day] += 2 * tvr * (my_cost_bps_per_side / 10_000)

    new_pretax = cfg7['strategy_return_pretax'] - (mom30_pnl - mom30_cost) + (my_pnl - my_entry_exit_cost - my_rebal_cost)
    return new_pretax, active


def apply_annual_tax(daily_returns, tax_rate=TAX_RATE):
    out = daily_returns.copy()
    yrs = daily_returns.index.year
    annual = (1 + daily_returns).groupby(yrs).prod() - 1
    for y in annual.index:
        if annual[y] > 0:
            mask = (daily_returns.index.year == y)
            out.loc[mask] = daily_returns.loc[mask] * (1.0 - tax_rate)
    return out


# ----------------------------------------------------------------------------
# Defensive overlay (V7 basket_cash_blend — exact port)
# ----------------------------------------------------------------------------
def identify_latches(nifty_pos_series):
    is_flat = (nifty_pos_series == 0.0).values
    n = len(is_flat)
    latch_id = np.zeros(n, dtype=int)
    day_in_latch = np.zeros(n, dtype=int)
    cur_id, cur_day = 0, 0
    for i in range(n):
        if is_flat[i]:
            if i == 0 or not is_flat[i-1]:
                cur_id += 1; cur_day = 1
            else:
                cur_day += 1
            latch_id[i] = cur_id
            day_in_latch[i] = cur_day
        else:
            cur_day = 0
    return latch_id, day_in_latch, is_flat


def apply_defensive_overlay(base_daily_ret, defensive_basket_ret, latch_id, day_in_latch,
                             is_flat, N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC):
    ret = base_daily_ret.values.copy()
    basket = defensive_basket_ret.reindex(base_daily_ret.index).fillna(0).values
    active = is_flat & (day_in_latch > N)
    ret[active] = alloc * basket[active] + (1 - alloc) * base_daily_ret.values[active]

    cost_per_side = DEFENSIVE_COST_BPS_PER_SIDE / 10_000
    dates = base_daily_ret.index
    for i in range(1, len(ret)):
        if active[i] and not active[i-1]:
            ret[i] -= alloc * cost_per_side
        elif not active[i] and active[i-1]:
            j = i - 1
            while j > 0 and active[j-1]:
                j -= 1
            run = ret[j:i]
            cum = np.prod(1 + run) - 1
            gain_frac = alloc * cum if cum > 0 else 0
            rate = STCG_POST if dates[i] >= STCG_CHANGE_DATE else STCG_PRE
            tax = gain_frac * rate
            ret[i] -= alloc * cost_per_side + tax
    return pd.Series(ret, index=base_daily_ret.index), active.astype(int)


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def perf(r):
    r = pd.Series(r).dropna()
    if r.empty:
        return {'CAGR': np.nan, 'AnnVol': np.nan, 'Sharpe': np.nan,
                'MaxDD': np.nan, 'N': 0, 'years': 0}
    cum = (1 + r).cumprod()
    days = len(r); years = days / 252
    return {
        'CAGR': cum.iloc[-1] ** (1/years) - 1 if years > 0 else np.nan,
        'AnnVol': r.std() * np.sqrt(252),
        'Sharpe': (r.mean() * 252) / (r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
        'MaxDD': (cum / cum.cummax() - 1).min(),
        'N': days, 'years': years,
    }


def per_regime(nifty_pos_series, ret_series):
    is_bull  = nifty_pos_series == 1.0
    is_short = nifty_pos_series == -1.0
    is_flat  = nifty_pos_series == 0.0
    out = {}
    for name, mask in [('bull', is_bull), ('flat', is_flat), ('short', is_short)]:
        r = ret_series[mask.values]
        if len(r) > 0:
            out[name] = {
                'days': int(mask.sum()),
                'ann_ret': (1 + r).prod() ** (252 / len(r)) - 1 if len(r) > 0 else np.nan,
            }
    return out


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    print("=" * 78)
    print("MOMENTUM-BASKET V2 — quality-GATE (filter), plus universe expansion test")
    print("Defensive quality basket (V7 basket_cash_blend N=40 50/50) ON in all variants")
    print("=" * 78)

    print("\n[Loading data]", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data()

    # Load quality_scored_universe for wider universe (500 rows/rebalance)
    quality_scored = pd.read_parquet(os.path.join(REPO_ROOT, 'data', 'momentum_scores',
                                                    'quality_scored_universe.parquet'))
    quality_scored['rebalance_date'] = pd.to_datetime(quality_scored['rebalance_date'])

    print("\n[Data coverage]")
    for col in ['^NSEI', 'NIFTYMOM30', 'GOLDBEES.NS', '^INDIAVIX', 'INR=X']:
        if col in raw.columns:
            fv = raw[col].first_valid_index(); lv = raw[col].last_valid_index()
            print(f"  {col:14s} {fv.date() if fv is not None else '?'} → {lv.date() if lv is not None else '?'}")
    print(f"  scored_universe:         {scored['rebalance_date'].min().date()} → {scored['rebalance_date'].max().date()}  "
          f"(n_rebs={scored['rebalance_date'].nunique()}, rows/reb={scored.groupby('rebalance_date').size().max()})")
    print(f"  quality_scored_universe: {quality_scored['rebalance_date'].min().date()} → {quality_scored['rebalance_date'].max().date()}  "
          f"(rows/reb={quality_scored.groupby('rebalance_date').size().max()})")
    print(f"  fund_wide (fundamentals): {fund_wide['fiscal_year'].min()} → {fund_wide['fiscal_year'].max()}  "
          f"({fund_wide['symbol'].nunique()} symbols)")
    print(f"  stock prices panel:      {prices['Date'].min().date()} → {prices['Date'].max().date()}  "
          f"({prices['symbol'].nunique()} symbols)")

    print("\n[Running Config 7 native]", flush=True)
    cfg7_on      = run_cfg7(raw, rotate_stress=True,  use_g10_gate=True,  use_momentum_gold=True)
    cfg7_no_gold = run_cfg7(raw, rotate_stress=False, use_g10_gate=False, use_momentum_gold=False)

    m_baseline = perf(cfg7_on.loc[:END_FULL]['strategy_return'])
    print(f"  Config 7 baseline CAGR: {m_baseline['CAGR']*100:.4f}% "
          f"(target 16.52%; current-data reference)  Sh {m_baseline['Sharpe']:.4f}")

    print("\n[Building V7 defensive basket for overlay]", flush=True)
    def_holdings, def_reb_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    defensive_basket_ret, _ = v6.compute_daily_basket_returns(
        def_holdings, def_reb_dates, prices, cfg7_on.index)
    defensive_basket_ret = defensive_basket_ret.fillna(0)

    latch_id, day_in_latch, is_flat = identify_latches(cfg7_on['nifty_position'])

    prices_wide = prices.pivot_table(index='Date', columns='symbol', values='close', aggfunc='last')
    prices_wide = prices_wide.reindex(cfg7_on.index).ffill()

    # ==========================================================================
    # IDENTITY CHECKS
    # ==========================================================================
    print("\n" + "=" * 78)
    print("IDENTITY CHECKS (must pass before variants are believed)")
    print("=" * 78)
    # IC1
    ic1 = perf(cfg7_on.loc[:END_FULL]['strategy_return'])
    print(f"  IC1 (swap OFF, defensive OFF): CAGR {ic1['CAGR']*100:.4f}%  Sh {ic1['Sharpe']:.4f}  "
          f"(diff vs baseline: {(ic1['CAGR']-m_baseline['CAGR'])*100:+.6f}pp)")

    # IC2 — V7 basket_cash_blend recipe
    ic2_ret, _ = apply_defensive_overlay(
        cfg7_no_gold['strategy_return'], defensive_basket_ret,
        latch_id, day_in_latch, is_flat, N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC)
    ic2 = perf(ic2_ret.loc[:END_FULL])
    print(f"  IC2 (swap OFF, defensive ON):  CAGR {ic2['CAGR']*100:.4f}%  Sh {ic2['Sharpe']:.4f}  "
          f"(target 16.85% / 1.34; ΔCAGR {(ic2['CAGR']-0.1685)*100:+.4f}pp)")

    # IC3 — swap ON, my_basket = Mom30
    mom30_ret_series = raw['NIFTYMOM30'].reindex(cfg7_on.index).pct_change().fillna(0)
    ic3_pretax, _ = build_swap_pretax(
        cfg7_no_gold, raw,
        my_basket_daily_ret=mom30_ret_series,
        turnover_by_reb={}, rebalance_dates=[],
        my_cost_bps_per_side=MOM30_COST_BPS)
    ic3_ret = apply_annual_tax(ic3_pretax.fillna(0))
    ic3 = perf(ic3_ret.loc[:END_FULL])
    m_nogold = perf(cfg7_no_gold.loc[:END_FULL]['strategy_return'])
    diff3 = (ic3['CAGR'] - m_nogold['CAGR']) * 100
    print(f"  IC3 (swap identity):           CAGR {ic3['CAGR']*100:.4f}%  Sh {ic3['Sharpe']:.4f}  "
          f"(target cfg7_no_gold {m_nogold['CAGR']*100:.4f}%; ΔCAGR {diff3:+.6f}pp)")
    if abs(diff3) > 1e-3:
        print("  ⚠ IC3 drift > 1e-3 pp — investigate")
    else:
        print("  ✓ All identity checks OK")

    # ==========================================================================
    # GRID
    # ==========================================================================
    print("\n" + "=" * 78)
    print("GRID: universe × gate × buffer  (12 momentum-basket variants)")
    print("Tune on 2008-2016 IS Sharpe → lock → apply full + OOS")
    print("=" * 78)

    reb_dates = sorted(scored['rebalance_date'].unique())
    grid = []
    for universe in [200, 500]:
        for gate_kind in ['none', 'hard_rules', 'hard_rules_pct']:
            for buf in [45, 60]:
                grid.append((universe, gate_kind, buf))

    grid_results = []
    grid_cache = {}
    grid_baskets = {}      # for diagnostic

    for universe, gate_kind, buf in grid:
        label = f"U{universe}_{gate_kind}_buf{buf}"
        # Build baskets
        baskets = select_quality_gated_momentum(
            scored, quality_scored, fund_wide, reb_dates,
            universe=universe, gate_kind=gate_kind, buf=buf, N=N_HOLD)
        grid_baskets[label] = baskets

        daily_ret, turnover_by_reb = compute_basket_daily_returns(baskets, prices_wide, cfg7_on.index)
        new_pretax, active_mask = build_swap_pretax(
            cfg7_no_gold, raw, daily_ret, turnover_by_reb, reb_dates,
            my_cost_bps_per_side=BASKET_COST_BPS_PER_SIDE)
        new_ret_swap = apply_annual_tax(new_pretax.fillna(0))
        final_ret, def_active = apply_defensive_overlay(
            new_ret_swap, defensive_basket_ret, latch_id, day_in_latch, is_flat,
            N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC)
        grid_cache[label] = (final_ret, active_mask, turnover_by_reb)

        is_mask = final_ret.index <= IS_END
        m_is = perf(final_ret[is_mask])
        m_full = perf(final_ret.loc[:END_FULL])
        oos_mask = (final_ret.index >= OOS_START) & (final_ret.index <= END_FULL)
        m_oos = perf(final_ret[oos_mask])

        avg_turnover = float(np.mean(list(turnover_by_reb.values())[1:])) if len(turnover_by_reb) > 1 else 0.0
        # Avg holding period (semi-annual = 126 trading days, scaled by turnover)
        avg_hold_days = 126 / max(avg_turnover, 0.01)

        grid_results.append({
            'variant': label, 'universe': universe, 'gate': gate_kind, 'buf': buf,
            'IS_CAGR': m_is['CAGR'], 'IS_Sharpe': m_is['Sharpe'],
            'FULL_CAGR': m_full['CAGR'], 'FULL_Sharpe': m_full['Sharpe'], 'FULL_MaxDD': m_full['MaxDD'],
            'OOS_CAGR': m_oos['CAGR'], 'OOS_Sharpe': m_oos['Sharpe'], 'OOS_MaxDD': m_oos['MaxDD'],
            'avg_turnover_per_reb': avg_turnover,
            'avg_hold_days': avg_hold_days,
        })

    grid_df = pd.DataFrame(grid_results)
    grid_df.to_csv(os.path.join(OUT_DIR, 'grid_metrics.csv'), index=False)

    # Lock winner by IS Sharpe
    winner_idx = grid_df['IS_Sharpe'].idxmax()
    winner = grid_df.loc[winner_idx]
    print(f"\n  LOCKED (best IS Sharpe): {winner['variant']}  IS Sh {winner['IS_Sharpe']:.3f}")

    # Print full grid
    print(f"\n  {'variant':30s} {'IS Sh':>6s} {'FULL CAGR':>10s} {'FULL Sh':>7s} "
          f"{'OOS CAGR':>10s} {'OOS Sh':>7s} {'FULL DD':>8s} {'avgT':>5s} {'avg_hold':>8s}")
    for _, r in grid_df.iterrows():
        mark = ' ←' if r['variant'] == winner['variant'] else '  '
        print(f"  {r['variant']:30s} {r['IS_Sharpe']:>6.3f} "
              f"{r['FULL_CAGR']*100:>9.2f}% {r['FULL_Sharpe']:>7.3f} "
              f"{r['OOS_CAGR']*100:>9.2f}% {r['OOS_Sharpe']:>7.3f} "
              f"{r['FULL_MaxDD']*100:>+7.2f}% {r['avg_turnover_per_reb']*100:>4.0f}% "
              f"{r['avg_hold_days']:>7.0f}d{mark}")

    # ==========================================================================
    # HEADLINE: R1 vs 3 momentum variants (one per gate, best universe/buffer)
    # ==========================================================================
    print("\n" + "=" * 78)
    print("HEADLINE — R1 vs quality-gated momentum baskets")
    print("Show BEST-IS variant PER gate (across universe×buffer for that gate)")
    print("=" * 78)
    print("  R1 = Config 7 + quality-defensive basket_cash_blend + Mom30 INDEX bull")

    # Best per gate (by IS Sharpe)
    best_per_gate = {}
    for g in ['none', 'hard_rules', 'hard_rules_pct']:
        gsub = grid_df[grid_df['gate'] == g]
        best_row = gsub.loc[gsub['IS_Sharpe'].idxmax()]
        best_per_gate[g] = best_row
        print(f"  M[{g:16s}] = {best_row['variant']}")

    # Assemble final variants
    variants_final = {
        'R1': ic2_ret.loc[:END_FULL],
        'M_none':          grid_cache[best_per_gate['none']['variant']][0].loc[:END_FULL],
        'M_hard_rules':    grid_cache[best_per_gate['hard_rules']['variant']][0].loc[:END_FULL],
        'M_hard_rules_pct': grid_cache[best_per_gate['hard_rules_pct']['variant']][0].loc[:END_FULL],
    }

    for label in ['FULL 2008-2026', 'OOS 2017-2026']:
        w_start = cfg7_on.index.min() if 'FULL' in label else OOS_START
        w_end   = END_FULL
        print(f"\n--- {label} ---")
        print(f"  {'variant':20s} {'CAGR':>8s} {'ΔCAGR':>8s} {'Sharpe':>7s} {'ΔSh':>7s} "
              f"{'MaxDD':>8s} {'ΔMaxDD':>8s} {'AnnVol':>7s}")
        base_r = perf(variants_final['R1'].loc[w_start:w_end])
        for lbl, ser in variants_final.items():
            r = perf(ser.loc[w_start:w_end])
            print(f"  {lbl:20s} {r['CAGR']*100:>7.2f}% {(r['CAGR']-base_r['CAGR'])*100:>+7.2f}pp "
                  f"{r['Sharpe']:>7.2f} {r['Sharpe']-base_r['Sharpe']:>+7.2f} "
                  f"{r['MaxDD']*100:>+7.2f}% {(r['MaxDD']-base_r['MaxDD'])*100:>+7.2f}pp "
                  f"{r['AnnVol']*100:>6.2f}%")

    # ==========================================================================
    # Diagnostics on WINNER + best-of-hard-rules-pct (for illustration)
    # ==========================================================================
    print("\n" + "=" * 78)
    print(f"DIAGNOSTICS — LOCKED WINNER: {winner['variant']}")
    print("=" * 78)
    _, _, winner_turnover = grid_cache[winner['variant']]
    tv = list(winner_turnover.values())[1:]
    print(f"  Avg / med / max turnover per rebalance: {np.mean(tv)*100:.0f}% / "
          f"{np.median(tv)*100:.0f}% / {np.max(tv)*100:.0f}%")
    print(f"  Approx annual cost drag (rebalance turnover only): "
          f"{2 * np.mean(tv) * 2 * BASKET_COST_BPS_PER_SIDE:.0f} bps/yr")
    print(f"  Avg holding period: {126/max(np.mean(tv),0.01):.0f} trading days")

    latest_baskets = grid_baskets[winner['variant']]
    latest_rd = sorted(latest_baskets.keys())[-1]
    top = list(latest_baskets[latest_rd].keys())[:10]
    print(f"\n  Latest basket ({latest_rd.date()}, first 10):")
    print(f"    {', '.join(top)}")

    # Also show how many names each gate accepted at latest rebalance
    print(f"\n  Gate-eligibility at {latest_rd.date()} (top-500 universe):")
    fund_by_fy, quality_by_rd = build_gate_lookups(fund_wide, quality_scored)
    latest_sub = scored[scored['rebalance_date'] == latest_rd].copy()
    latest_sub = latest_sub[latest_sub['universe_rank_turnover'] <= 500]
    latest_sub = latest_sub[~latest_sub['symbol'].map(_is_etf)]
    for g in ['none', 'hard_rules', 'hard_rules_pct']:
        gate_ok = sum(passes_gate(s, latest_rd, fund_by_fy, quality_by_rd, g)
                          for s in latest_sub['symbol'])
        print(f"    {g:16s}: {gate_ok:3d} / {len(latest_sub):3d} pass")

    # ==========================================================================
    # REGIME ATTRIBUTION
    # ==========================================================================
    print("\n" + "=" * 78)
    print("REGIME ATTRIBUTION — FULL history (annualized returns)")
    print("=" * 78)
    print(f"  {'state':10s} {'days':>6s}   " + '   '.join(f'{k:>14s}' for k in variants_final.keys()))
    reg_by_var = {k: per_regime(cfg7_on['nifty_position'].loc[:END_FULL], v)
                    for k, v in variants_final.items()}
    for st in ['bull', 'flat', 'short']:
        days = reg_by_var['R1'].get(st, {}).get('days', 0)
        row = f"  {st:10s} {days:>6d}   "
        for k in variants_final.keys():
            ar = reg_by_var[k].get(st, {}).get('ann_ret', np.nan)
            row += f"   {ar*100:>+12.2f}%"
        print(row)

    # ==========================================================================
    # VERDICT — 3 blunt questions
    # ==========================================================================
    print("\n" + "=" * 78)
    print("VERDICT — 3 blunt questions")
    print("=" * 78)
    for label in ['FULL 2008-2026', 'OOS 2017-2026']:
        w_start = cfg7_on.index.min() if 'FULL' in label else OOS_START
        w_end   = END_FULL
        r1  = perf(variants_final['R1'].loc[w_start:w_end])
        pm  = perf(variants_final['M_none'].loc[w_start:w_end])
        qm  = perf(variants_final['M_hard_rules'].loc[w_start:w_end])
        qmp = perf(variants_final['M_hard_rules_pct'].loc[w_start:w_end])
        print(f"\n[{label}]")
        print(f"  Q1. Does GATING (hard_rules) beat PURE momentum?")
        print(f"      hard_rules vs none:  ΔCAGR {(qm['CAGR']-pm['CAGR'])*100:+.2f}pp  "
              f"ΔSh {qm['Sharpe']-pm['Sharpe']:+.2f}  ΔMaxDD {(qm['MaxDD']-pm['MaxDD'])*100:+.2f}pp")
        print(f"      +pct>=50 vs none:    ΔCAGR {(qmp['CAGR']-pm['CAGR'])*100:+.2f}pp  "
              f"ΔSh {qmp['Sharpe']-pm['Sharpe']:+.2f}  ΔMaxDD {(qmp['MaxDD']-pm['MaxDD'])*100:+.2f}pp")

        # Q2 — universe effect (fix gate to best, compare U200 vs U500)
        best_gate = best_per_gate  # dict
        for g in ['none', 'hard_rules', 'hard_rules_pct']:
            u200_rows = grid_df[(grid_df['gate']==g) & (grid_df['universe']==200)]
            u500_rows = grid_df[(grid_df['gate']==g) & (grid_df['universe']==500)]
            if u200_rows.empty or u500_rows.empty:
                continue
            best_u200 = u200_rows.loc[u200_rows['IS_Sharpe'].idxmax()]
            best_u500 = u500_rows.loc[u500_rows['IS_Sharpe'].idxmax()]
            r_u200 = perf(grid_cache[best_u200['variant']][0].loc[w_start:w_end])
            r_u500 = perf(grid_cache[best_u500['variant']][0].loc[w_start:w_end])
            print(f"  Q2. Universe effect [{g:16s}]: U500 vs U200  "
                  f"ΔCAGR {(r_u500['CAGR']-r_u200['CAGR'])*100:+.2f}pp  "
                  f"ΔSh {r_u500['Sharpe']-r_u200['Sharpe']:+.2f}")

        print(f"  Q3. Does ANY gated basket beat R1 (Mom30 INDEX)?")
        winners_vs_r1 = []
        for k, ser in variants_final.items():
            if k == 'R1':
                continue
            p = perf(ser.loc[w_start:w_end])
            dcagr = (p['CAGR'] - r1['CAGR']) * 100
            dsh   = p['Sharpe'] - r1['Sharpe']
            ddd   = (p['MaxDD'] - r1['MaxDD']) * 100
            verdict = "✓ WINS" if (dcagr > 0.15 and dsh > 0) else "✗ loses"
            print(f"      {k:20s}: ΔCAGR {dcagr:+.2f}pp  ΔSh {dsh:+.2f}  ΔMaxDD {ddd:+.2f}pp   {verdict}")

    print(f"\nOutputs → {OUT_DIR}")


if __name__ == '__main__':
    main()

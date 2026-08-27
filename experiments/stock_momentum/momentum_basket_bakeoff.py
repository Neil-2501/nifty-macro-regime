"""Momentum-basket bake-off — REPLACE the NIFTYMOM30 index (bull-side) with a
self-picked momentum basket, while keeping the QUALITY DEFENSIVE basket
(V7 basket_cash_blend, N=40) ON on the defensive side.

Architecture (mirrors V7 native):
  1. Run Config 7 native (strategy.py) → get PRE-TAX return + Mom30-active mask
  2. Reconstruct Config 7's Mom30 lane exactly:
        pnl_mom30  = w_long_mom.shift(1) * mom30_ret
        cost_mom30 = w_long_mom.diff().abs() * 6bps
  3. Build MY momentum basket from scored_universe.parquet:
        semi-annual rebalance, top-N by rank_composite_risk_adj,
        buffered (retain if in top-`buf`), equal or turnover-weighted
  4. Compute my basket lane on the SAME active mask:
        pnl_my  = w_long_mom.shift(1) * my_basket_daily_ret
        cost_my = 30bps entry/exit + 60bps × internal-rebalance turnover
  5. new_pretax = cfg7_pretax - (pnl_mom30 - cost_mom30) + (pnl_my - cost_my)
  6. new_return = apply_annual_tax(new_pretax, tax_rate=0.15)  ← matches Config 7
  7. Overlay quality defensive basket on stress-flat days > N=40 (EXACT V7 recipe)

Bull-day active mask = long_mom_default & ~composition_swap_active
   → V2 recovery windows (NIFTY 50) are LEFT UNCHANGED. Only Mom30 days swap.

Identity checks (both MUST pass before any variant is reported):
  IC1. Momentum swap OFF, defensive OFF  → reproduce Config 7 (target 16.52%)
  IC2. Momentum swap OFF, defensive ON   → reproduce V7 basket_cash_blend (16.85%)
  IC3. Momentum swap ON with my_basket = Mom30 identity → reproduce 16.52%
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

import defensive_sleeve_v6 as v6
import strategy as prod

OUT_DIR = os.path.join(REPO_ROOT, "data", "momentum_basket_bakeoff")
os.makedirs(OUT_DIR, exist_ok=True)

MOM30_COST_BPS = 6                     # Config 7's cost for Mom30 index (per side)
BASKET_COST_BPS_PER_SIDE = 30          # Self-picked basket, per side
DEFENSIVE_COST_BPS_PER_SIDE = 30       # Defensive basket, per side (V7 recipe)
STCG_PRE  = 0.15
STCG_POST = 0.20
STCG_CHANGE_DATE = pd.Timestamp('2024-07-23')
TAX_RATE = 0.15                        # Config 7 flat annual haircut

END_FULL = pd.Timestamp('2026-05-11')
IS_END   = pd.Timestamp('2016-12-31')
OOS_START = pd.Timestamp('2017-01-01')

DEFENSIVE_N = 40                       # V7 locked (basket_cash_blend)
DEFENSIVE_ALLOC = 0.5                  # V7 locked (50/50 basket/cash)


# ----------------------------------------------------------------------------
# Config 7 native runs
# ----------------------------------------------------------------------------
def run_cfg7(raw, rotate_stress: bool = True, use_g10_gate: bool = True,
             use_momentum_gold: bool = True):
    combiner = prod.make_combiner(
        rotate_stress=rotate_stress,
        rotate_panic=False,
        use_momentum_gold=use_momentum_gold,
        gold_gate_external=use_g10_gate,
        slow_stress_lock_days=5,
        panic_short_dd_threshold=0.15,
    )
    strat = prod.MacroStrategy(
        combiner, nifty_cost_bps=3, gold_cost_bps=5,
        long_target="NIFTYMOM30", long_cost_bps=MOM30_COST_BPS,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
    )
    return strat.run(raw).loc['2008-04-01':'2026-06-15']


# ----------------------------------------------------------------------------
# Momentum basket construction (semi-annual, buffered)
# ----------------------------------------------------------------------------
ETF_PATTERNS = ['GOLD', 'SILVER', 'SILV', 'BEES', 'NIFTY', 'BANKN', 'LIQUID',
                'NAV', 'IETF', 'NIFTYIETF', 'GOLDIETF', 'SETFGOLD',
                'JGOLD', 'MAFANG', 'CPSE', 'PSU', 'MOM100']
UNIVERSE_TOP_N = 200


def _is_etf(sym: str) -> bool:
    s = str(sym).upper()
    return any(p in s for p in ETF_PATTERNS)


def select_momentum_basket(scored, rebalance_dates, N: int, buf: int,
                           weighting: str = 'equal',
                           turnover_col: str = 'avg_60d_turnover_rupees'):
    """Return {rebalance_date: {symbol: weight}}.
    N       — target basket size
    buf     — retain incumbent if still ranked ≤ buf (buf must be >= N)
    weighting — 'equal' or 'turnover_weighted' (proxy for cap-weight)

    Universe: top-UNIVERSE_TOP_N liquid names per rebalance, ETF-like names excluded.
    """
    if buf < N:
        raise ValueError(f'buf ({buf}) must be >= N ({N})')

    baskets = {}
    prev_holdings = set()

    for rd in rebalance_dates:
        sub = scored[scored['rebalance_date'] == rd].copy()
        # Universe filter: top-N liquid + drop ETF-like names
        sub = sub[sub['universe_rank_turnover'] <= UNIVERSE_TOP_N]
        sub = sub[~sub['symbol'].map(_is_etf)]
        # Re-rank composite within the filtered universe
        sub = sub.sort_values('composite_risk_adj', ascending=False)
        sub['rank_local'] = np.arange(1, len(sub) + 1)
        # Only look at first `buf` names in the ranking
        candidates = sub.head(buf)['symbol'].tolist()
        top_N     = sub.head(N)['symbol'].tolist()

        # Buffered replacement: keep incumbent if still in candidates,
        # fill remaining slots with top_N ordering.
        held = [s for s in prev_holdings if s in candidates]
        new_names = [s for s in top_N if s not in held]
        picks = held + new_names
        picks = picks[:N]     # cap at N

        # If we didn't have enough holdover, this fills from top_N
        # If we had extra holdovers (>N), we trimmed to N by insertion order

        # Weight assignment
        if weighting == 'equal':
            w = {s: 1.0 / len(picks) for s in picks}
        elif weighting == 'turnover_weighted':
            pool = sub[sub['symbol'].isin(picks)].copy()
            pool = pool.set_index('symbol').reindex(picks)
            tvr  = pool[turnover_col].fillna(pool[turnover_col].median()).clip(lower=1)
            wts  = tvr / tvr.sum()
            w = wts.to_dict()
        else:
            raise ValueError(f'Unknown weighting {weighting}')

        baskets[pd.Timestamp(rd)] = w
        prev_holdings = set(picks)

    return baskets


def compute_basket_daily_returns(baskets: dict, prices_wide: pd.DataFrame,
                                 date_index: pd.DatetimeIndex):
    """Compute daily basket return and per-day turnover fraction.
    Returns:
      daily_ret       — pd.Series aligned to date_index
      turnover_by_reb — dict {rebalance_date: turnover_fraction ∈ [0,1]}
                        (sum(|Δweight|)/2)
    """
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

        # Turnover at this rebalance vs previous
        all_syms = prev_w.index.union(w.index)
        pv = prev_w.reindex(all_syms).fillna(0)
        cv = w.reindex(all_syms).fillna(0)
        turnover_by_reb[rd] = float((pv - cv).abs().sum() / 2)
        prev_w = w

        # Period: days AFTER rebalance up to next
        period = (date_index > pd.Timestamp(rd)) & (date_index <= pd.Timestamp(end))
        if not period.any():
            continue
        cols = [s for s in w.index if s in all_ret.columns]
        if not cols:
            continue
        weights = pd.Series({s: w[s] for s in cols})
        weights = weights / weights.sum()  # renormalize if some stocks missing
        basket_r = all_ret.loc[period, cols] @ weights
        daily_ret.loc[period] = basket_r.values

    return daily_ret, turnover_by_reb


# ----------------------------------------------------------------------------
# Overlay computations
# ----------------------------------------------------------------------------
def build_swap_pretax(cfg7, raw, my_basket_daily_ret, turnover_by_reb, rebalance_dates,
                       my_cost_bps_per_side: float):
    """Return NEW pretax daily return series with Mom30 lane swapped for my basket.

    Steps:
      1. active_mask = long_mom_default & ~composition_swap_active (bull-days on Mom30)
      2. mom30_pnl  = active.shift(1) * mom30_ret
      3. mom30_cost = active.diff().abs() * (Mom30_cost / 10000)
      4. my_pnl     = active.shift(1) * my_basket_daily_ret
      5. my_entry_exit_cost = active.diff().abs() * (my_cost / 10000)
      6. my_rebal_cost      = at each rebalance date if we're active,
                              charge 2 * turnover_frac * (my_cost / 10000)
      7. new_pretax = cfg7_pretax - (mom30_pnl - mom30_cost) + (my_pnl - my_entry_exit_cost - my_rebal_cost)
    """
    active = (cfg7['long_mom_default'] & ~cfg7['composition_swap_active']).astype(float)
    mom30_ret = raw['NIFTYMOM30'].reindex(cfg7.index).pct_change().fillna(0)

    mom30_pnl  = active.shift(1).fillna(0) * mom30_ret
    mom30_cost = active.diff().abs().fillna(0) * (MOM30_COST_BPS / 10_000)

    my_pnl     = active.shift(1).fillna(0) * my_basket_daily_ret.reindex(cfg7.index).fillna(0)
    my_entry_exit_cost = active.diff().abs().fillna(0) * (my_cost_bps_per_side / 10_000)

    # Rebalance cost only fires when active on the rebalance date
    my_rebal_cost = pd.Series(0.0, index=cfg7.index)
    for rd, tvr in turnover_by_reb.items():
        # Find the trading day on or after rd
        rd = pd.Timestamp(rd)
        candidate_days = cfg7.index[cfg7.index >= rd]
        if len(candidate_days) == 0:
            continue
        day = candidate_days[0]
        if active.loc[day] == 1.0:
            # tvr is one-sided (sum|Δ|/2); cost per side = my_cost_bps_per_side
            # both sides charged → 2 * tvr * bps
            my_rebal_cost.loc[day] += 2 * tvr * (my_cost_bps_per_side / 10_000)

    new_pretax = cfg7['strategy_return_pretax'] - (mom30_pnl - mom30_cost) + (my_pnl - my_entry_exit_cost - my_rebal_cost)
    return new_pretax, active


def apply_annual_tax(daily_returns, tax_rate=TAX_RATE):
    """Match strategy.apply_annual_tax exactly."""
    out = daily_returns.copy()
    yrs = daily_returns.index.year
    annual = (1 + daily_returns).groupby(yrs).prod() - 1
    for y in annual.index:
        if annual[y] > 0:
            mask = (daily_returns.index.year == y)
            out.loc[mask] = daily_returns.loc[mask] * (1.0 - tax_rate)
    return out


# ----------------------------------------------------------------------------
# Defensive basket overlay (V7 basket_cash_blend recipe — exact port)
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
    """V7 basket_cash_blend recipe (exact port from backtest_bakeoff_v7_native).
    On days_in_latch > N (basket active), replace daily return with
       alloc * defensive_basket_ret + (1-alloc) * base_daily_ret
    Charge 30bps entry/exit + STCG (15/20) on exit gains.
    """
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
    return pd.Series(ret, index=base_daily_ret.index, name='ret'), active.astype(int)


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


def per_regime_attribution(nifty_pos_series, ret_series):
    """Bull / stress-flat / panic-short annualized returns."""
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
                'ann_vol': r.std() * np.sqrt(252),
            }
    return out


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    print("=" * 78)
    print("MOMENTUM-BASKET BAKE-OFF — REPLACE Mom30 INDEX with self-picked basket")
    print("Defensive quality basket (V7 basket_cash_blend, N=40, 50/50) ON in all variants")
    print("=" * 78)

    print("\n[Loading data]", flush=True)
    raw, prices, quality, fund_wide, scored = v6.load_all_data()

    print("\n[Data coverage]")
    for col in ['^NSEI', 'NIFTYMOM30', 'GOLDBEES.NS', '^INDIAVIX', 'INR=X', '^TNX']:
        if col in raw.columns:
            fv = raw[col].first_valid_index()
            lv = raw[col].last_valid_index()
            print(f"  {col:14s} {fv.date() if fv is not None else '?'} → {lv.date() if lv is not None else '?'}")
    print(f"  scored_universe rebalances: {scored['rebalance_date'].min().date()} → {scored['rebalance_date'].max().date()} "
          f"(n={scored['rebalance_date'].nunique()})")
    print(f"  stock prices panel:  {prices['Date'].min().date()} → {prices['Date'].max().date()}  "
          f"({prices['symbol'].nunique()} symbols)")

    # ---- Native runs ----
    print("\n[Running Config 7 native]", flush=True)
    cfg7_on       = run_cfg7(raw, rotate_stress=True,  use_g10_gate=True,  use_momentum_gold=True)
    cfg7_no_gold  = run_cfg7(raw, rotate_stress=False, use_g10_gate=False, use_momentum_gold=False)
    print(f"  cfg7_on:       {cfg7_on.index.min().date()} → {cfg7_on.index.max().date()}  N={len(cfg7_on)}")

    # ---- Baseline reconciliation ----
    m_baseline = perf(cfg7_on.loc[:END_FULL]['strategy_return'])
    print(f"\n  [Baseline reconciliation] Config 7 CAGR {m_baseline['CAGR']*100:.2f}% "
          f"(target 16.52%)  Sh {m_baseline['Sharpe']:.2f}  MaxDD {m_baseline['MaxDD']*100:.2f}%")
    if abs(m_baseline['CAGR'] - 0.1652) > 0.005:
        print("  ⚠ Baseline drifted from 16.52% — investigate before proceeding!")

    # ---- Defensive basket (for V7 basket_cash_blend overlay) ----
    print("\n[Building V7 defensive basket]", flush=True)
    def_holdings, def_reb_dates = v6.compute_defensive_basket_holdings(
        quality, fund_wide, prices, raw['^NSEI'].copy())
    defensive_basket_ret, _ = v6.compute_daily_basket_returns(
        def_holdings, def_reb_dates, prices, cfg7_on.index)
    defensive_basket_ret = defensive_basket_ret.fillna(0)
    print(f"  Defensive basket: {len(def_reb_dates)} rebalances, non-zero days {(defensive_basket_ret != 0).sum():,}")

    # Latches for defensive overlay
    latch_id, day_in_latch, is_flat = identify_latches(cfg7_on['nifty_position'])

    # ==========================================================================
    # IDENTITY CHECK 1 — swap OFF, defensive OFF → should equal Config 7 exactly
    # ==========================================================================
    print("\n" + "=" * 78)
    print("IDENTITY CHECK 1 — momentum swap OFF, defensive OFF")
    print("=" * 78)
    ic1_ret = cfg7_on.loc[:END_FULL]['strategy_return']
    ic1 = perf(ic1_ret)
    print(f"  CAGR {ic1['CAGR']*100:.4f}%  Sh {ic1['Sharpe']:.4f}  MaxDD {ic1['MaxDD']*100:.2f}%")
    print(f"  Diff vs Config 7: {(ic1['CAGR'] - m_baseline['CAGR']) * 100:.6f}pp")
    assert abs(ic1['CAGR'] - m_baseline['CAGR']) < 1e-9, "IC1 baseline mismatch"

    # ==========================================================================
    # IDENTITY CHECK 2 — swap OFF, defensive ON (V7 basket_cash_blend N=40)
    # ==========================================================================
    print("\n" + "=" * 78)
    print("IDENTITY CHECK 2 — momentum swap OFF, defensive ON (V7 basket_cash_blend)")
    print("=" * 78)
    # V7 recipe: use cfg7_no_gold as base for the defensive overlay
    ic2_ret, _ = apply_defensive_overlay(
        cfg7_no_gold['strategy_return'], defensive_basket_ret,
        latch_id, day_in_latch, is_flat,
        N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC)
    m_ic2 = perf(ic2_ret.loc[:END_FULL])
    print(f"  CAGR {m_ic2['CAGR']*100:.4f}%  Sh {m_ic2['Sharpe']:.4f}  MaxDD {m_ic2['MaxDD']*100:.2f}%")
    print(f"  Target: V7 basket_cash_blend = 16.85% CAGR / 1.34 Sh / -13.92% MaxDD")
    print(f"  Diff vs V7: ΔCAGR {(m_ic2['CAGR'] - 0.1685) * 100:+.4f}pp  ΔSh {m_ic2['Sharpe'] - 1.34:+.4f}")

    # ==========================================================================
    # IDENTITY CHECK 3 — swap ON with my_basket = Mom30 (should return baseline)
    # ==========================================================================
    print("\n" + "=" * 78)
    print("IDENTITY CHECK 3 — swap ON with my_basket = Mom30 identity")
    print("=" * 78)
    mom30_ret_series = raw['NIFTYMOM30'].reindex(cfg7_on.index).pct_change().fillna(0)
    # Build the swap on cfg7_no_gold (same base as M variant); with my_basket=Mom30
    # and my_cost=6bps this should EXACTLY recover cfg7_no_gold.strategy_return.
    ic3_pretax, _ = build_swap_pretax(
        cfg7_no_gold, raw,
        my_basket_daily_ret=mom30_ret_series,
        turnover_by_reb={},                # no internal rebalances
        rebalance_dates=[],
        my_cost_bps_per_side=MOM30_COST_BPS,   # same 6bps as Config 7
    )
    ic3_ret = apply_annual_tax(ic3_pretax.fillna(0))
    m_ic3 = perf(ic3_ret.loc[:END_FULL])
    m_no_gold = perf(cfg7_no_gold.loc[:END_FULL]['strategy_return'])
    print(f"  IC3 CAGR:            {m_ic3['CAGR']*100:.4f}%  Sh {m_ic3['Sharpe']:.4f}  MaxDD {m_ic3['MaxDD']*100:.2f}%")
    print(f"  cfg7_no_gold target: {m_no_gold['CAGR']*100:.4f}%  Sh {m_no_gold['Sharpe']:.4f}  MaxDD {m_no_gold['MaxDD']*100:.2f}%")
    diff_cagr = (m_ic3['CAGR'] - m_no_gold['CAGR']) * 100
    diff_sh   = m_ic3['Sharpe'] - m_no_gold['Sharpe']
    print(f"  Diff: ΔCAGR {diff_cagr:+.6f}pp  ΔSh {diff_sh:+.6f}")
    if abs(diff_cagr) > 1e-3:
        print("  ⚠ IC3 drift > 1e-3 pp CAGR — check swap reconstruction")
    else:
        print("  ✓ IC3 within 1e-3 pp of cfg7_no_gold baseline")

    # ==========================================================================
    # REPLICA vs INDEX check
    # ==========================================================================
    print("\n" + "=" * 78)
    print("REPLICA vs ACTUAL NIFTYMOM30 INDEX")
    print("=" * 78)
    replica = pd.read_parquet(os.path.join(REPO_ROOT, 'data', 'momentum_scores',
                                            'our_mom30_replica.parquet'))
    replica['rebalance_date'] = pd.to_datetime(replica['rebalance_date'])
    # Build baskets from replica
    replica_baskets = {}
    for rd, grp in replica.groupby('rebalance_date'):
        w = {s: 1.0/len(grp) for s in grp['symbol'].tolist()}
        replica_baskets[pd.Timestamp(rd)] = w

    # Build wide prices for fast lookup
    prices_wide = prices.pivot_table(index='Date', columns='symbol', values='close', aggfunc='last')
    prices_wide = prices_wide.reindex(cfg7_on.index).ffill()
    replica_daily, _ = compute_basket_daily_returns(
        replica_baskets, prices_wide, cfg7_on.index)

    # Compare over 2008-2024 (avoid partial 2025-26)
    period_end = pd.Timestamp('2024-12-31')
    period_start = pd.Timestamp('2009-01-01')  # avoid data warm-up
    period = (cfg7_on.index >= period_start) & (cfg7_on.index <= period_end)
    idx_ret = mom30_ret_series[period].dropna()
    rep_ret = replica_daily[period].dropna()
    # Align
    common = idx_ret.index.intersection(rep_ret.index)
    idx_ret = idx_ret.loc[common]; rep_ret = rep_ret.loc[common]
    idx_ret = idx_ret.replace([np.inf, -np.inf], 0).fillna(0)
    rep_ret = rep_ret.replace([np.inf, -np.inf], 0).fillna(0)
    idx_cagr = (1 + idx_ret).prod() ** (252 / len(idx_ret)) - 1
    rep_cagr = (1 + rep_ret).prod() ** (252 / len(rep_ret)) - 1
    tracking_diff_bps = (rep_ret - idx_ret).std() * np.sqrt(252) * 10_000
    corr = idx_ret.corr(rep_ret)
    print(f"  Period: {common[0].date()} → {common[-1].date()} ({len(common)} days)")
    print(f"  Actual NIFTYMOM30 CAGR:  {idx_cagr*100:.2f}%")
    print(f"  Replica top-30 EW CAGR:  {rep_cagr*100:.2f}%")
    print(f"  Tracking-error (ann):    {tracking_diff_bps:.0f} bps")
    print(f"  Daily-return correlation: {corr:.3f}")
    tracking_ok = abs(rep_cagr - idx_cagr) < 0.04 and corr > 0.60
    if tracking_ok:
        print(f"  ✓ Replica tracks index within reason — momentum-basket comparison is sound")
    else:
        print(f"  ⚠ Replica diverges significantly from actual index — self-picked basket ≠ index proxy")

    if not tracking_ok:
        print("\n⚠ HALTING: replica does not track index. Do NOT interpret grid results as index-vs-basket.")
        # Still continue to run the grid for user visibility but with a caveat.

    # ==========================================================================
    # BUILD 8 GRID VARIANTS (equal/turnover × N=20/30 × buf=40/55)
    # ==========================================================================
    print("\n" + "=" * 78)
    print("GRID: 8 momentum-basket variants (weighting × N × buffer)")
    print("Tune on 2008-2016 IS → lock → apply to full + OOS")
    print("=" * 78)

    reb_dates = sorted(scored['rebalance_date'].unique())
    grid = []
    for weighting in ['equal', 'turnover_weighted']:
        for N in [20, 30]:
            for buf in [40, 55]:
                grid.append((weighting, N, buf))

    grid_results = []
    grid_variants_cache = {}     # (w,N,buf) → new_daily_return (post-tax + defensive)

    for weighting, N, buf in grid:
        label = f"{weighting}_N{N}_buf{buf}"
        # Build baskets
        baskets = select_momentum_basket(scored, reb_dates, N=N, buf=buf,
                                          weighting=weighting)
        daily_ret, turnover_by_reb = compute_basket_daily_returns(baskets, prices_wide, cfg7_on.index)

        # Swap Mom30 → my basket in pretax, using cfg7_no_gold as base so that
        # stress-flat days = cash (matches V7 basket_cash_blend base).
        # Bull-day behavior is identical between cfg7_on and cfg7_no_gold, so the
        # swap operates on the same set of days.
        new_pretax, active_mask = build_swap_pretax(
            cfg7_no_gold, raw, daily_ret, turnover_by_reb, reb_dates,
            my_cost_bps_per_side=BASKET_COST_BPS_PER_SIDE)
        new_ret_swap = apply_annual_tax(new_pretax.fillna(0))
        # Defensive overlay on top (exact V7 basket_cash_blend recipe)
        final_ret, def_active = apply_defensive_overlay(
            new_ret_swap, defensive_basket_ret, latch_id, day_in_latch, is_flat,
            N=DEFENSIVE_N, alloc=DEFENSIVE_ALLOC)

        grid_variants_cache[(weighting, N, buf)] = (final_ret, active_mask, turnover_by_reb)

        # IS metrics for tuning
        is_mask = final_ret.index <= IS_END
        m_is = perf(final_ret[is_mask])
        # Full + OOS
        m_full = perf(final_ret.loc[:END_FULL])
        oos_mask = (final_ret.index >= OOS_START) & (final_ret.index <= END_FULL)
        m_oos = perf(final_ret[oos_mask])

        # Annual turnover fraction (average across rebalances)
        avg_turnover = float(np.mean(list(turnover_by_reb.values()))) if turnover_by_reb else 0.0

        grid_results.append({
            'variant': label, 'weighting': weighting, 'N': N, 'buf': buf,
            'IS_CAGR': m_is['CAGR'], 'IS_Sharpe': m_is['Sharpe'],
            'FULL_CAGR': m_full['CAGR'], 'FULL_Sharpe': m_full['Sharpe'], 'FULL_MaxDD': m_full['MaxDD'],
            'OOS_CAGR': m_oos['CAGR'], 'OOS_Sharpe': m_oos['Sharpe'], 'OOS_MaxDD': m_oos['MaxDD'],
            'avg_turnover_per_reb': avg_turnover,
        })

    grid_df = pd.DataFrame(grid_results)
    grid_df.to_csv(os.path.join(OUT_DIR, 'grid_metrics.csv'), index=False)

    # Lock winner by IS Sharpe
    winner_idx = grid_df['IS_Sharpe'].idxmax()
    winner = grid_df.loc[winner_idx]
    print(f"\n  LOCKED (IS best-Sharpe): {winner['variant']}  "
          f"IS Sharpe {winner['IS_Sharpe']:.3f}")

    # Print grid table
    print(f"\n  {'variant':32s} {'IS Sh':>7s} {'FULL CAGR':>10s} {'FULL Sh':>7s} {'OOS CAGR':>10s} {'OOS Sh':>7s} {'MaxDD':>7s} {'avgT':>6s}")
    for _, r in grid_df.iterrows():
        marker = ' ←' if r['variant'] == winner['variant'] else '  '
        print(f"  {r['variant']:32s} {r['IS_Sharpe']:>7.3f} "
              f"{r['FULL_CAGR']*100:>9.2f}% {r['FULL_Sharpe']:>7.3f} "
              f"{r['OOS_CAGR']*100:>9.2f}% {r['OOS_Sharpe']:>7.3f} "
              f"{r['FULL_MaxDD']*100:>+6.2f}% {r['avg_turnover_per_reb']*100:>5.0f}%{marker}")

    # ==========================================================================
    # HEADLINE: R0 vs R1 vs M
    # ==========================================================================
    print("\n" + "=" * 78)
    print("HEADLINE — R0 vs R1 vs M (defensive quality basket ON in R1 & M)")
    print("=" * 78)
    print("  R0 = Config 7 baseline (Mom30 index bull, G10 gold defensive)")
    print("  R1 = Config 7 + quality-defensive basket_cash_blend (Mom30 INDEX on bull)")
    print(f"  M  = Config 7 + quality-defensive + MOMENTUM BASKET on bull  ({winner['variant']})")

    winner_ret, _, winner_turnover = grid_variants_cache[
        (winner['weighting'], int(winner['N']), int(winner['buf']))]

    variants_final = {
        'R0': cfg7_on['strategy_return'].loc[:END_FULL],
        'R1': ic2_ret.loc[:END_FULL],
        'M':  winner_ret.loc[:END_FULL],
    }

    for label in ['FULL 2008-2026', 'OOS 2017-2026']:
        w_start = cfg7_on.index.min() if 'FULL' in label else OOS_START
        w_end   = END_FULL
        print(f"\n--- {label} ---")
        print(f"  {'variant':6s} {'CAGR':>8s} {'ΔCAGR':>8s} {'Sharpe':>7s} {'ΔSh':>7s} "
              f"{'MaxDD':>8s} {'ΔMaxDD':>8s} {'AnnVol':>7s}")
        base_row = perf(variants_final['R0'].loc[w_start:w_end])
        for lbl, ser in variants_final.items():
            r = perf(ser.loc[w_start:w_end])
            print(f"  {lbl:6s} {r['CAGR']*100:>7.2f}% {(r['CAGR']-base_row['CAGR'])*100:>+7.2f}pp "
                  f"{r['Sharpe']:>7.2f} {r['Sharpe']-base_row['Sharpe']:>+7.2f} "
                  f"{r['MaxDD']*100:>+7.2f}% {(r['MaxDD']-base_row['MaxDD'])*100:>+7.2f}pp "
                  f"{r['AnnVol']*100:>6.2f}%")

    # ---- Turnover & cost drag ----
    print("\n" + "=" * 78)
    print(f"MOMENTUM BASKET DIAGNOSTICS — {winner['variant']}")
    print("=" * 78)
    winner_baskets = select_momentum_basket(
        scored, reb_dates, N=int(winner['N']), buf=int(winner['buf']),
        weighting=winner['weighting'])
    if len(winner_turnover) > 0:
        turnovers = list(winner_turnover.values())
        # First rebalance has 100% turnover from empty
        turnovers_ex_first = turnovers[1:] if len(turnovers) > 1 else turnovers
        print(f"  Avg turnover per rebalance (ex-first): {np.mean(turnovers_ex_first)*100:.0f}%")
        print(f"  Median turnover per rebalance: {np.median(turnovers_ex_first)*100:.0f}%")
        print(f"  Max turnover per rebalance:    {np.max(turnovers_ex_first)*100:.0f}%")
        print(f"  Rebalance-cost drag (approx): {np.mean(turnovers_ex_first)*2*BASKET_COST_BPS_PER_SIDE:.0f} bps × 2/yr = "
              f"{2 * np.mean(turnovers_ex_first) * 2 * BASKET_COST_BPS_PER_SIDE:.0f} bps/yr")
    latest_rd = reb_dates[-1]
    latest_basket = winner_baskets[pd.Timestamp(latest_rd)]
    print(f"\n  Latest basket ({latest_rd.date() if hasattr(latest_rd,'date') else latest_rd}, top-10 by weight):")
    top = sorted(latest_basket.items(), key=lambda x: -x[1])[:10]
    for sym, w in top:
        print(f"    {sym:16s} {w*100:.2f}%")

    # ---- Regime attribution ----
    print("\n" + "=" * 78)
    print("REGIME ATTRIBUTION (FULL history)")
    print("=" * 78)
    reg_R0 = per_regime_attribution(cfg7_on['nifty_position'].loc[:END_FULL],
                                        variants_final['R0'])
    reg_R1 = per_regime_attribution(cfg7_on['nifty_position'].loc[:END_FULL],
                                        variants_final['R1'])
    reg_M  = per_regime_attribution(cfg7_on['nifty_position'].loc[:END_FULL],
                                        variants_final['M'])
    print(f"  {'state':10s} {'days':>6s}   {'R0':>12s}   {'R1':>12s}   {'M':>12s}")
    for st in ['bull', 'flat', 'short']:
        d = reg_R0.get(st, {}).get('days', 0)
        r0 = reg_R0.get(st, {}).get('ann_ret', np.nan)
        r1 = reg_R1.get(st, {}).get('ann_ret', np.nan)
        rm = reg_M.get(st, {}).get('ann_ret', np.nan)
        print(f"  {st:10s} {d:>6d}   {r0*100:>+10.2f}%   {r1*100:>+10.2f}%   {rm*100:>+10.2f}%")

    # ---- VERDICT ----
    print("\n" + "=" * 78)
    print("VERDICT — Does self-picked momentum basket beat cheap Mom30 index?")
    print("=" * 78)
    for label in ['FULL 2008-2026', 'OOS 2017-2026']:
        w_start = cfg7_on.index.min() if 'FULL' in label else OOS_START
        w_end   = END_FULL
        r1_perf = perf(variants_final['R1'].loc[w_start:w_end])
        m_perf  = perf(variants_final['M'].loc[w_start:w_end])
        dcagr = (m_perf['CAGR'] - r1_perf['CAGR']) * 100
        dsh   = m_perf['Sharpe'] - r1_perf['Sharpe']
        ddd   = (m_perf['MaxDD'] - r1_perf['MaxDD']) * 100
        print(f"\n  [{label}]  M vs R1: ΔCAGR {dcagr:+.2f}pp  ΔSh {dsh:+.2f}  ΔMaxDD {ddd:+.2f}pp")
        if dcagr > 0.15 and dsh > 0:
            print(f"    → Momentum basket WINS marginally after real costs.")
        elif dcagr > 0 and dsh > -0.02:
            print(f"    → Momentum basket about tied — not clearly worth the cost.")
        else:
            print(f"    → Momentum basket LOSES vs cheap Mom30 index. Keep the index.")

    print(f"\nOutputs → {OUT_DIR}")


if __name__ == '__main__':
    main()

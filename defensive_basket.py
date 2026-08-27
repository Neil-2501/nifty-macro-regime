"""Defensive quality basket — production overlay for MacroStrategy.

Ships ON by default in production (enable_defensive_basket=True in MacroStrategy).
Setting enable=False reproduces plain Config 7 exactly (byte-identical strategy_return).

RUNTIME: loads two small precomputed artifacts and overlays the basket on
Config 7's daily return series on stress-flat days beyond the persistence gate.

REBUILD: `build_defensive_basket.py` at repo root regenerates the artifacts
from source fundamentals + quality + stock-price panel.

Recipe (V7 basket_cash_blend, N=40 50/50 — locked from bake-off):
  - Basket = 18 equal-weight defensive-quality names, semi-annual rebalance
    (top-200 liquid, quality_percentile ≥ 0.60, hard rules cfo>0/np>0/D/E<3,
     beta ≤ 0.85, vol ≤ 0.30, defensive-sector tilt bonus, sector cap 5)
  - Persistence gate: hold cash for the first 40 days of every stress-flat latch
  - On days 41+ of an active latch: blend 50% basket + 50% cash (Config 7's cash return)
  - Entry/exit: 30 bps × alloc (0.5 × 30bps = 15 bps) per side
  - STCG at exit: 15% pre-2024-07-23, 20% after (short-term cap gains, held <1yr)

Result vs Config 7 baseline (post-tax, 2008-04 → 2026-05-11):
  Config 7:  16.52% CAGR / Sharpe 0.81 / MaxDD -12.78%
  R1 (+basket): 16.85% CAGR / Sharpe 0.83 / MaxDD -13.92%
  Delta: +0.33pp CAGR, +0.02 Sharpe, -1.13pp MaxDD (marginal, Sharpe-neutral)

Data files loaded at runtime:
  data/defensive_basket_daily_returns.parquet  (~4700 rows, one float per trading day)
  data/defensive_basket_holdings.parquet       (~650 rows, symbol×rebalance×weight)
Both are tiny and shipped with the repo.
"""
from __future__ import annotations

import os
import warnings

import numpy as np
import pandas as pd


REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(REPO_ROOT, "data")

DAILY_RETURNS_PATH = os.path.join(DATA_DIR, "defensive_basket_daily_returns.parquet")
HOLDINGS_PATH      = os.path.join(DATA_DIR, "defensive_basket_holdings.parquet")


class DefensiveBasketOverlay:
    """Post-processing overlay on MacroStrategy.run() output.

    Modifies `strategy_return` on days_in_latch > N of every stress-flat latch
    (where stress-flat is defined as nifty_position == 0.0).

    Parameters
    ----------
    persistence_days : int, default 40
        Wait this many days into a stress-flat latch before deploying the basket.
        Locked from bake-off: N=40 was the OOS best.
    alloc : float, default 0.5
        Fraction of the flat-day return replaced with basket return on active days.
        Locked from bake-off: 0.5 (50/50 basket/cash) was the best-Sharpe alloc.
    cost_bps_per_side : float, default 30
        Real basket trading cost per side (brokerage + STT + exchange + GST + slippage).
    stcg_rate_pre : float, default 0.15
    stcg_rate_post : float, default 0.20
        Short-term capital gains tax on realized basket gains at exit.
    stcg_change_date : pd.Timestamp
        Date the STCG rate stepped from 15% to 20% (India, 2024-07-23).
    daily_returns : pd.Series or None
        Pre-computed daily basket return series (aligned to trading days). If None,
        loads from `data/defensive_basket_daily_returns.parquet`.
    """

    def __init__(self,
                 persistence_days: int = 40,
                 alloc: float = 0.5,
                 cost_bps_per_side: float = 30.0,
                 stcg_rate_pre: float = 0.15,
                 stcg_rate_post: float = 0.20,
                 stcg_change_date: pd.Timestamp = pd.Timestamp('2024-07-23'),
                 daily_returns: pd.Series | None = None):
        self.persistence_days = persistence_days
        self.alloc = alloc
        self.cost_per_side = cost_bps_per_side / 10_000.0
        self.stcg_rate_pre = stcg_rate_pre
        self.stcg_rate_post = stcg_rate_post
        self.stcg_change_date = stcg_change_date
        self._daily_returns = daily_returns
        self._holdings = None

    @property
    def daily_returns(self) -> pd.Series:
        if self._daily_returns is None:
            if not os.path.exists(DAILY_RETURNS_PATH):
                raise FileNotFoundError(
                    f"Defensive basket daily returns not found at {DAILY_RETURNS_PATH}. "
                    f"Run `python build_defensive_basket.py` to generate, or set "
                    f"enable_defensive_basket=False in MacroStrategy.")
            df = pd.read_parquet(DAILY_RETURNS_PATH)
            # Expected columns: date-index and one 'ret' column
            if 'ret' in df.columns:
                self._daily_returns = df['ret']
            else:
                self._daily_returns = df.iloc[:, 0]
            self._daily_returns.index = pd.to_datetime(self._daily_returns.index)
        return self._daily_returns

    @property
    def holdings(self) -> pd.DataFrame:
        if self._holdings is None:
            if os.path.exists(HOLDINGS_PATH):
                self._holdings = pd.read_parquet(HOLDINGS_PATH)
        return self._holdings

    def _identify_latches(self, nifty_position: pd.Series):
        """Return (latch_id, day_in_latch, is_flat) arrays aligned to nifty_position."""
        is_flat = (nifty_position == 0.0).values
        n = len(is_flat)
        latch_id = np.zeros(n, dtype=int)
        day_in_latch = np.zeros(n, dtype=int)
        cur_id, cur_day = 0, 0
        for i in range(n):
            if is_flat[i]:
                if i == 0 or not is_flat[i-1]:
                    cur_id += 1
                    cur_day = 1
                else:
                    cur_day += 1
                latch_id[i] = cur_id
                day_in_latch[i] = cur_day
            else:
                cur_day = 0
        return latch_id, day_in_latch, is_flat

    def apply(self, strategy_return: pd.Series, nifty_position: pd.Series) -> pd.Series:
        """Return a new strategy_return series with the overlay applied.

        strategy_return : Config 7's post-tax daily strategy return (already annually-taxed)
        nifty_position  : nifty_position from Config 7 output (used to identify stress-flat latches)

        Both series must share the same DatetimeIndex.
        """
        if not strategy_return.index.equals(nifty_position.index):
            raise ValueError("strategy_return and nifty_position must share the same index")

        latch_id, day_in_latch, is_flat = self._identify_latches(nifty_position)
        basket = self.daily_returns.reindex(strategy_return.index).fillna(0).values
        ret = strategy_return.values.copy()

        active = is_flat & (day_in_latch > self.persistence_days)
        # Blend: on active days, alloc*basket + (1-alloc)*cfg7_flat_return
        ret[active] = self.alloc * basket[active] + (1 - self.alloc) * strategy_return.values[active]

        # Entry / exit cost + STCG at exit
        dates = strategy_return.index
        for i in range(1, len(ret)):
            if active[i] and not active[i-1]:
                # Entry — buy alloc fraction of basket
                ret[i] -= self.alloc * self.cost_per_side
            elif not active[i] and active[i-1]:
                # Exit — sell + realize STCG on cumulative basket gain
                j = i - 1
                while j > 0 and active[j-1]:
                    j -= 1
                run_returns = ret[j:i]
                cum = np.prod(1 + run_returns) - 1
                gain_frac = self.alloc * cum if cum > 0 else 0.0
                rate = self.stcg_rate_post if dates[i] >= self.stcg_change_date else self.stcg_rate_pre
                tax = gain_frac * rate
                ret[i] -= self.alloc * self.cost_per_side + tax

        return pd.Series(ret, index=strategy_return.index, name=strategy_return.name)


def load_default_overlay() -> DefensiveBasketOverlay:
    """Instantiate overlay with default locked parameters and preloaded artifacts."""
    return DefensiveBasketOverlay()

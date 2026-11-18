"""Daily forward paper-trading runner for Strategy v2.3.

Run once per NSE trading day after the 3:30 pm close (scheduled for 3:35 pm IST).
It:
  1. downloads the same market data the backtest uses, up to today
  2. refuses to trade if any input is missing or stale
  3. runs the unchanged production strategy (strategy.py) and reads today's decision
  4. marks the paper portfolio to today's prices, works out the trades needed to reach
     today's target, and records everything in paper_trading/

Decision timing: a decision made at today's close is held from today's close until the
next decision (the post-close session, 3:40-4:00 pm, trades at the closing price).

Files written (all under paper_trading/):
  ledger.csv          one row per trading day: market inputs, decision, portfolio value
  trades.csv          every paper trade: ticker, side, quantity, price, cost
  state/<date>.json   holdings after that day's trades (reruns on the same day start
                      from the previous day's file, so a rerun never double-trades)
  logs/               output of scheduled runs

Missed days: if the Mac was off or asleep on earlier trading days, the next run first
catches them up in date order, each one using only data up to that day's close, so the
ledger has one row for every trading day.

Usage:
  python paper_trade.py              normal daily run (catches up missed days first)
  python paper_trade.py --dry-run    show today's decision and trades, write nothing
  python paper_trade.py --force      run even before 3:30 pm (prices not final)

All returns are before tax; tax is worked out once a year.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import warnings

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO_ROOT)

import strategy as prod                       # noqa: E402
from defensive_basket import (                # noqa: E402
    DefensiveBasketOverlay, DAILY_RETURNS_PATH, HOLDINGS_PATH)

# ── Settings ────────────────────────────────────────────────────────────────
PAPER_DIR = os.path.join(REPO_ROOT, "paper_trading")
STATE_DIR = os.path.join(PAPER_DIR, "state")
LEDGER_PATH = os.path.join(PAPER_DIR, "ledger.csv")
TRADES_PATH = os.path.join(PAPER_DIR, "trades.csv")

STARTING_CAPITAL = 1_000_000.0                # ₹10 lakh notional
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MARKET_CLOSE = dt.time(15, 30)
POST_CLOSE_END = dt.time(16, 0)

# Instruments actually traded
MOM30_ETF = "MOM30IETF.NS"     # ICICI Prudential Nifty 200 Momentum 30 ETF
NIFTY_ETF = "NIFTYBEES.NS"     # NIFTY 50 (held in the 60-day post-bear recovery window)
GOLD_ETF = "GOLDBEES.NS"
CASH_ETF = "LIQUIDCASE.NS"     # liquid ETF whose price accrues the interest daily
NIFTY_INDEX = "^NSEI"          # NIFTY futures short is recorded at the index price

# Trading cost per side in bps — the same figures the backtest charges
COST_BPS = {MOM30_ETF: 6, NIFTY_ETF: 3, GOLD_ETF: 5, CASH_ETF: 0, NIFTY_INDEX: 3}
BASKET_COST_BPS = 30

# Signal inputs that must have a bar dated today before the runner will trade
REQUIRED_FRESH = ["^NSEI", "^INDIAVIX", "INR=X", "GOLDBEES.NS"]

# Same raw-data recipe as the backtest (experiments/stock_momentum/defensive_sleeve_v6.py)
SIGNAL_TICKERS = ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "GOLDBEES.NS", "^TNX"]
WARMUP = "2006-01-01"


# ── Strategy (identical configuration to the published v2.3) ───────────────
def build_strategy(overlay: DefensiveBasketOverlay) -> prod.MacroStrategy:
    combiner = prod.make_combiner(rotate_stress=True, rotate_panic=False, use_momentum_gold=True,
                                  slow_stress_lock_days=5, panic_short_dd_threshold=0.15)
    return prod.MacroStrategy(combiner, nifty_cost_bps=3, gold_cost_bps=5,
                              long_target="NIFTYMOM30", long_cost_bps=6,
                              enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
                              defensive_basket_overlay=overlay)


def load_signal_data(today: dt.date):
    """Download the backtest's raw inputs through today.
    Returns (raw, valid): valid marks which values are real bars, before any carry-forward."""
    end = (today + dt.timedelta(days=1)).isoformat()          # yfinance end is exclusive
    raw = yf.download(SIGNAL_TICKERS, start=WARMUP, end=end,
                      auto_adjust=True, progress=False)["Close"]
    raw.dropna(how="all", inplace=True)
    valid = raw.notna()
    for col in ["CL=F", "^NSEI", "INR=X", "^INDIAVIX", "^TNX"]:
        if col in raw.columns:
            raw[col] = raw[col].ffill()
    first_valid = raw["GOLDBEES.NS"].first_valid_index()
    mask = raw.index >= first_valid
    raw.loc[mask, "GOLDBEES.NS"] = raw.loc[mask, "GOLDBEES.NS"].ffill()
    mom = prod.load_nse_index_csv(os.path.join(REPO_ROOT, "data", "momentum30_history.csv"), "NIFTYMOM30")
    raw["NIFTYMOM30"] = mom.reindex(raw.index).ffill()      # only affects backtest returns, not decisions
    return raw, valid


# ── Defensive basket ─────────────────────────────────────────────────────────
def next_rebalance_due(last_rebalance: pd.Timestamp) -> pd.Timestamp:
    """Basket is re-picked at the end of every June and December."""
    if last_rebalance.month <= 6:
        return pd.Timestamp(last_rebalance.year, 12, 31)
    return pd.Timestamp(last_rebalance.year + 1, 6, 30)


def current_basket(today: pd.Timestamp):
    """Latest basket holdings on or before today, and any warning."""
    h = pd.read_parquet(HOLDINGS_PATH)
    h["rebalance_date"] = pd.to_datetime(h["rebalance_date"])
    past = h[h["rebalance_date"] <= today]
    if past.empty:
        return [], None, "no defensive basket rebalance on or before today"
    rd = past["rebalance_date"].max()
    syms = sorted(past.loc[past["rebalance_date"] == rd, "symbol"])
    warning = None
    due = next_rebalance_due(rd)
    if today > due:
        warning = (f"defensive basket rebuild overdue (last {rd.date()}, due {due.date()}): "
                   f"run build_defensive_basket.py; basket treated as unavailable")
        syms = []
    return syms, rd, warning


def build_overlay(index: pd.DatetimeIndex, basket_live: bool) -> DefensiveBasketOverlay:
    """Overlay whose availability is extended past the saved artifact's last date
    (the current holdings stay in force until the next rebalance)."""
    df = pd.read_parquet(DAILY_RETURNS_PATH)
    df.index = pd.to_datetime(df.index)
    avail = df["basket_available"].astype(bool).reindex(index)
    after = index > df.index.max()
    avail[after] = basket_live
    rets = df["ret"].reindex(index).fillna(0.0)
    return DefensiveBasketOverlay(daily_returns=rets, basket_available=avail.fillna(False).astype(bool))


# ── Decision → target weights ───────────────────────────────────────────────
def target_weights(row: pd.Series, basket_syms: list[str], basket_alloc: float) -> tuple[dict, str, float]:
    """Translate today's strategy row into portfolio weights held from today's close.
    Returns (weights by ticker, label, short fraction of portfolio)."""
    pos = float(row["nifty_position"])
    if pos == 1.0:
        if bool(row["v2_active"]):
            return {NIFTY_ETF: 1.0}, "LONG NIFTY 50 (post-bear recovery window)", 0.0
        return {MOM30_ETF: 1.0}, "LONG MOMENTUM 30", 0.0
    if pos == -1.0:
        return {CASH_ETF: 1.0}, "SHORT NIFTY 50 (panic short)", 1.0
    # Flat: idle money in cash + idle gold; basket takes half when active
    gold_frac = float(row["idle_gold_weight"])           # 0.25 when gold is above its 200-day average
    w: dict[str, float] = {}
    idle = 1.0
    label = "FLAT"
    if bool(row["defensive_basket_active"]) and basket_syms:
        per = basket_alloc / len(basket_syms)
        for s in basket_syms:
            w[f"{s}.NS"] = per
        idle = 1.0 - basket_alloc
        label = f"FLAT + DEFENSIVE BASKET ({len(basket_syms)} stocks)"
    if gold_frac > 0:
        w[GOLD_ETF] = idle * gold_frac
        label += " + IDLE GOLD"
    w[CASH_ETF] = w.get(CASH_ETF, 0.0) + idle * (1.0 - gold_frac)
    return w, label, 0.0


# ── Portfolio state ─────────────────────────────────────────────────────────
def load_previous_state(today: dt.date) -> dict:
    """Most recent saved state strictly before today (so reruns don't double-trade)."""
    os.makedirs(STATE_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(STATE_DIR) if f.endswith(".json") and f[:10] < today.isoformat())
    if not files:
        return {"date": None, "cash": STARTING_CAPITAL, "units": {}, "short_units": 0.0,
                "short_ref_price": None, "targets": {}, "basket_rebalance": None, "value": STARTING_CAPITAL}
    with open(os.path.join(STATE_DIR, files[-1])) as f:
        return json.load(f)


def fetch_prices(tickers: list[str], today: dt.date) -> tuple[dict, list[str]]:
    """Latest price dated today for each ticker; returns (prices, stale tickers)."""
    if not tickers:
        return {}, []
    start = (today - dt.timedelta(days=10)).isoformat()
    end = (today + dt.timedelta(days=1)).isoformat()
    d = yf.download(sorted(set(tickers)), start=start, end=end, auto_adjust=False,
                    progress=False, group_by="column")["Close"]
    if isinstance(d, pd.Series):
        d = d.to_frame(tickers[0])
    prices, stale = {}, []
    for t in tickers:
        s = d[t].dropna() if t in d.columns else pd.Series(dtype=float)
        if s.empty or s.index[-1].date() != today:
            stale.append(t)
        if not s.empty:
            prices[t] = float(s.iloc[-1])
    return prices, stale


def last_bars(valid: pd.DataFrame, day: dt.date) -> dict:
    """Date of each ticker's last real (not carried-forward) bar on or before day."""
    v = valid.loc[:pd.Timestamp(day)]
    out = {}
    for t in v.columns:
        idx = v.index[v[t].to_numpy()]
        out[t] = idx[-1].date() if len(idx) else None
    return out


def process_day(day: dt.date, raw: pd.DataFrame, valid: pd.DataFrame, state: dict,
                now: dt.datetime, notes: list[str]):
    """Work out one trading day's decision and paper trades, starting from `state`.
    Only data up to and including `day` is used, so a caught-up day gets the same
    decision a live run that evening would have made.
    Returns (status, result): status is "ok", "holiday" or "stale"."""
    last_bar = last_bars(valid, day)
    if last_bar.get("^NSEI") != day:
        return "holiday", f"No NIFTY 50 bar for {day} (last {last_bar.get('^NSEI')})"
    # NSE-traded inputs must be dated that day. VIX and USD/INR may be up to 3 days old
    # (FX holidays, late updates); the backtest carries those forward the same way.
    stale, carried = [], []
    for t in REQUIRED_FRESH:
        lb = last_bar.get(t)
        if lb == day:
            continue
        if t in ("^INDIAVIX", "INR=X") and lb is not None and (day - lb).days <= 3:
            carried.append(f"{t} from {lb}")
        else:
            stale.append(f"{t} last {lb}")
    if stale:
        return "stale", f"STALE DATA for {day}, no trade: {', '.join(stale)}"
    if carried:
        notes.append("carried forward: " + ", ".join(carried))

    # Strategy decision, from data up to this day only
    ts = pd.Timestamp(day)
    raw_d = raw.loc[:ts]
    basket_syms, basket_rd, basket_warn = current_basket(ts)
    if basket_warn:
        notes.append(basket_warn)
    overlay = build_overlay(raw_d.index, basket_live=bool(basket_syms))
    res = build_strategy(overlay).run(raw_d)
    row = res.loc[ts]
    weights, label, short_frac = target_weights(row, basket_syms, overlay.alloc)

    # Mark the existing portfolio to this day's closing prices
    held = list(state["units"].keys())
    need = sorted(set(held) | set(weights) | {NIFTY_INDEX, CASH_ETF})
    prices, stale_px = fetch_prices(need, day)
    missing = [t for t in need if t not in prices]
    if missing:
        return "stale", f"NO PRICE for {day}, no trade: {', '.join(missing)}"
    if stale_px:
        notes.append("price not dated that day (using last available): " + ", ".join(stale_px))

    cash = float(state["cash"])
    if state["short_units"]:
        cash += state["short_units"] * (state["short_ref_price"] - prices[NIFTY_INDEX])
    value = cash + sum(q * prices[t] for t, q in state["units"].items())
    prev_value = float(state["value"])
    day_ret = value / prev_value - 1 if state["date"] else 0.0

    # Trades: change a position only when its target weight changes or the basket list changes
    prev_targets = state.get("targets", {})
    basket_changed = str(basket_rd.date() if basket_rd is not None else None) != str(state.get("basket_rebalance"))
    new_units = dict(state["units"])
    trades = []
    total_cost = 0.0
    for t in sorted(set(weights) | set(new_units)):
        if t == CASH_ETF:
            continue
        w_new = weights.get(t, 0.0)
        is_basket = t.endswith(".NS") and t not in COST_BPS
        if abs(w_new - prev_targets.get(t, 0.0)) < 1e-9 and not (is_basket and basket_changed and w_new > 0):
            continue
        bps = BASKET_COST_BPS if is_basket else COST_BPS.get(t, 0)
        # size net of trading cost so a full allocation never overdraws cash
        tgt = math.floor(w_new * value / (prices[t] * (1 + bps / 10_000))) if w_new > 0 else 0
        qty = tgt - new_units.get(t, 0)
        if qty == 0:
            continue
        cost = abs(qty) * prices[t] * bps / 10_000
        cash -= qty * prices[t] + cost
        total_cost += cost
        trades.append(dict(date=day.isoformat(), ticker=t, side="BUY" if qty > 0 else "SELL",
                           qty=int(qty), price=round(prices[t], 4), value=round(qty * prices[t], 2),
                           cost=round(cost, 2)))
        new_units[t] = tgt
    # Cash ETF absorbs everything not invested elsewhere (whole units)
    cash_px = prices[CASH_ETF]
    cash_target = new_units.get(CASH_ETF, 0) + math.floor(cash / cash_px) if cash > 0 else \
        new_units.get(CASH_ETF, 0) - math.ceil(-cash / cash_px)
    cash_target = max(cash_target, 0)                 # never hold a negative number of units
    cash_qty = cash_target - new_units.get(CASH_ETF, 0)
    if cash_qty:
        cash -= cash_qty * cash_px
        trades.append(dict(date=day.isoformat(), ticker=CASH_ETF, side="BUY" if cash_qty > 0 else "SELL",
                           qty=int(cash_qty), price=round(cash_px, 4), value=round(cash_qty * cash_px, 2),
                           cost=0.0))
        new_units[CASH_ETF] = cash_target
    new_units = {t: q for t, q in new_units.items() if q}
    # Short leg: re-sized only when it switches on or off
    if short_frac > 0 and not state["short_units"]:
        short_units = short_frac * value / prices[NIFTY_INDEX]
        cost = short_units * prices[NIFTY_INDEX] * COST_BPS[NIFTY_INDEX] / 10_000
        cash -= cost
        total_cost += cost
        trades.append(dict(date=day.isoformat(), ticker="NIFTY FUT", side="SELL", qty=round(short_units, 4),
                           price=prices[NIFTY_INDEX], value=round(-short_units * prices[NIFTY_INDEX], 2),
                           cost=round(cost, 2)))
    elif short_frac == 0 and state["short_units"]:
        short_units = 0.0
        cost = state["short_units"] * prices[NIFTY_INDEX] * COST_BPS[NIFTY_INDEX] / 10_000
        cash -= cost
        total_cost += cost
        trades.append(dict(date=day.isoformat(), ticker="NIFTY FUT", side="BUY", qty=round(state["short_units"], 4),
                           price=prices[NIFTY_INDEX], value=round(state["short_units"] * prices[NIFTY_INDEX], 2),
                           cost=round(cost, 2)))
    else:
        short_units = state["short_units"]
    value_after = cash + sum(q * prices[t] for t, q in new_units.items())

    new_state = {"date": day.isoformat(), "cash": cash, "units": new_units, "short_units": short_units,
                 "short_ref_price": prices[NIFTY_INDEX] if short_units else None,   # short P&L settles daily
                 "targets": weights,
                 "basket_rebalance": str(basket_rd.date()) if basket_rd is not None else None,
                 "value": value_after, "prices": {t: prices[t] for t in need}}
    ledger_row = {
        "date": day.isoformat(), "run_time_ist": f"{now:%Y-%m-%d %H:%M}",
        "nifty50": round(float(raw.loc[ts, "^NSEI"]), 2), "india_vix": round(float(raw.loc[ts, "^INDIAVIX"]), 2),
        "usd_inr": round(float(raw.loc[ts, "INR=X"]), 4), "goldbees": round(float(raw.loc[ts, "GOLDBEES.NS"]), 2),
        "decision": label, "nifty_position": float(row["nifty_position"]),
        "recovery_window": bool(row["v2_active"]), "basket_active": bool(row["defensive_basket_active"]),
        "idle_gold_frac": float(row["idle_gold_weight"]),
        "value_before_trades": round(value, 2), "day_return_pct": round(day_ret * 100, 4),
        "n_trades": len(trades), "trade_cost": round(total_cost, 2), "value_after_trades": round(value_after, 2),
        "notes": " | ".join(notes),
    }
    return "ok", dict(state=new_state, ledger_row=ledger_row, trades=trades, label=label, weights=weights,
                      short_frac=short_frac, value=value, value_after=value_after, day_ret=day_ret,
                      total_cost=total_cost, notes=notes)


def report(day: dt.date, r: dict, header: str) -> None:
    print(f"\n── {day} {header} ──")
    print(f"Decision: {r['label']}")
    for t, w in sorted(r["weights"].items(), key=lambda x: -x[1]):
        print(f"  {t:16s} {w*100:6.2f}%")
    if r["short_frac"]:
        print(f"  NIFTY futures short {r['short_frac']*100:.0f}% of portfolio")
    print(f"Portfolio before trades ₹{r['value']:,.0f}  (day {r['day_ret']*100:+.2f}%)   "
          f"after trades ₹{r['value_after']:,.0f}")
    if r["trades"]:
        print(f"Trades ({len(r['trades'])}, cost ₹{r['total_cost']:,.0f}):")
        for tr in r["trades"]:
            print(f"  {tr['side']:4s} {abs(tr['qty']):>10} {tr['ticker']:16s} @ {tr['price']:>10,.2f}")
    else:
        print("No trades.")
    for n in r["notes"]:
        print(f"NOTE: {n}")


def save_day(day: dt.date, r: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, f"{day.isoformat()}.json"), "w") as f:
        json.dump(r["state"], f, indent=1, sort_keys=True)
    ledger = pd.read_csv(LEDGER_PATH) if os.path.exists(LEDGER_PATH) else pd.DataFrame()
    if not ledger.empty:
        ledger = ledger[ledger["date"] != day.isoformat()]
    ledger = pd.concat([ledger, pd.DataFrame([r["ledger_row"]])]).sort_values("date")
    ledger.to_csv(LEDGER_PATH, index=False)
    tr = pd.read_csv(TRADES_PATH) if os.path.exists(TRADES_PATH) else pd.DataFrame()
    if not tr.empty:
        tr = tr[tr["date"] != day.isoformat()]
    tr = pd.concat([tr, pd.DataFrame(r["trades"])])
    if not tr.empty:
        tr = tr.sort_values("date", kind="stable")
    tr.to_csv(TRADES_PATH, index=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show decisions and trades, write nothing")
    ap.add_argument("--force", action="store_true", help="run even before the 3:30 pm close")
    args = ap.parse_args(argv)

    now = dt.datetime.now(IST)
    today = now.date()
    print(f"Paper-trading run {now:%Y-%m-%d %H:%M} IST")
    do_today = now.time() >= MARKET_CLOSE or args.force

    raw, valid = load_signal_data(today)
    state = load_previous_state(today)

    # 1. Catch up: every NSE trading day after the last saved day and before today
    missed = []
    if state["date"]:
        last = pd.Timestamp(state["date"])
        nifty_days = valid.index[valid["^NSEI"].to_numpy()]
        missed = [d.date() for d in nifty_days if last < d < pd.Timestamp(today)]
    if missed:
        print(f"\nCatching up {len(missed)} missed trading day(s): {missed[0]} to {missed[-1]}")
    for d in missed:
        notes = [f"caught up on {today} (Mac was off or asleep at 3:35 pm that day)"]
        status, r = process_day(d, raw, valid, state, now, notes)
        if status == "holiday":
            continue
        if status == "stale":
            print(r)
            print("Catch-up stopped here; later days depend on this one. Nothing more done.")
            return 2
        report(d, r, "caught up")
        if not args.dry_run:
            save_day(d, r)
        state = r["state"]

    # 2. Today
    if not do_today:
        print("\nMarket has not closed yet (before 3:30 pm); today not done. Use --force to override.")
        return 0 if missed else 1
    notes = []
    if now.time() > POST_CLOSE_END:
        notes.append(f"ran at {now:%H:%M}, after the post-close session; trades recorded at the close")
    status, r = process_day(today, raw, valid, state, now, notes)
    if status == "holiday":
        print(f"\n{r}: market holiday or data not published yet. Nothing done for today.")
        return 0
    if status == "stale":
        print(f"\n{r}")
        return 2
    report(today, r, "today")
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0
    save_day(today, r)
    print(f"\nWritten: {os.path.relpath(LEDGER_PATH, REPO_ROOT)}, {os.path.relpath(TRADES_PATH, REPO_ROOT)}, "
          f"state/ files")
    return 0


if __name__ == "__main__":
    sys.exit(main())

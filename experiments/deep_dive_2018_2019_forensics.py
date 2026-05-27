"""
deep_dive_2018_2019_forensics.py — REAL forensics on 2018 and 2019.

Two questions to answer concretely:
  Q1. If Mom30 was +21% on 2019 LONG days, why is the 2019 strategy only +1.14%?
      Where is the money going?
  Q2. Slow-stress force-flatted multiple times in 2019. Is the fix a 3-day
      confirmation? Test the rule, year by year, on the full strategy
      (separate from panic-short confirmation).

Approach:
  - Run baseline C1 with daily logging
  - For each year:
      * decompose annual return by state (LONG-mom, LONG-V2, FLAT-cash,
        FLAT-gold, SHORT) showing P&L contribution in pp
      * compare to "what NIFTY did on each of those days" (opportunity cost)
  - Enumerate every slow-stress firing 2018-2025 with conditions + outcomes
  - Test slow-stress with 3-day persistence requirement
  - Test removing slow-stress entirely (oracle) for 2018-2019 only

NOTE: this is SLOW-STRESS specifically, NOT panic-short. The 2-day panic-short
confirmation test from before is a completely different thing.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

from strategy_lab import (
    MacroStrategyLab, RegimeFilter, SignalCombiner,
    USDINRSignal, IndiaVIXSignal, SlowStressSignal, PanicShortSignal,
    _load_data, metrics, apply_annual_tax, build_rbi_repo_rate_series,
)


# ---- Confirmed slow-stress signal (3-day persistence) ----------------------

class SlowStressConfirmedSignal(SlowStressSignal):
    """Same conditions as SlowStressSignal, but requires N consecutive days of
    firing before issuing a flat. Once flat is issued, behaves like the base
    SlowStress (single-day fires on subsequent days continue to flat).
    """
    name = "slow_stress_confirmed"
    def __init__(self, confirm_days=3, **kwargs):
        super().__init__(**kwargs)
        self.confirm_days = confirm_days
    def compute(self, data):
        # Build the raw daily firing series
        inr_w = data["INR=X"].pct_change(self.inr_window) > self.inr_threshold
        vix   = data["^INDIAVIX"]
        z     = (vix - vix.rolling(self.vix_z_window).mean()) / vix.rolling(self.vix_z_window).std()
        mom   = vix - vix.shift(self.vix_mom_window)
        raw_fires = (inr_w & (z > self.vix_z_threshold) & (mom > 0)).fillna(False)
        # Require confirm_days consecutive raw fires
        consec = raw_fires.rolling(self.confirm_days, min_periods=self.confirm_days).sum()
        confirmed = (consec >= self.confirm_days).fillna(False)
        s = pd.Series(0.0, index=data.index, name=self.name)
        s[confirmed] = -1.0
        return s


# ---- Skip-slow-stress signal (for oracle test) -----------------------------

class SlowStressOracleSignal(SlowStressSignal):
    """Same conditions as SlowStressSignal, but suppressed entirely during
    `skip_years`. Used to estimate upper bound of removing slow-stress in
    bad years."""
    name = "slow_stress_oracle"
    def __init__(self, skip_years=(), **kwargs):
        super().__init__(**kwargs)
        self.skip_years = set(skip_years)
    def compute(self, data):
        s = super().compute(data)
        if self.skip_years:
            mask = data.index.year.isin(self.skip_years)
            s.loc[mask] = 0.0
        return s


# ---- Build a combiner with a custom slow-stress instance -------------------

def build_combiner(slow_stress_signal):
    rf = RegimeFilter(window=100)
    c = SignalCombiner(regime_filter=rf,
                       rotate_to_gold_on_stress_flat=True,
                       rotate_to_gold_on_panic_short=False,
                       rotate_with_momentum=True,
                       gold_gate_external=True)
    c.add_entry(USDINRSignal(window=10, threshold=0.01), weight=1.5)
    c.add_entry(IndiaVIXSignal(window=10, threshold=0.20), weight=1.5)
    c.add_exit_no_cooldown(slow_stress_signal)
    c.add_short(PanicShortSignal(vix_level=25, vix_spike=0.50, window=10, dma=100),
                hold=False, max_hold_days=60, exit_ma_fast=5, exit_ma_slow=20)
    return c


def run_strategy(slow_stress_signal, raw, start, end, log_path=None):
    combiner = build_combiner(slow_stress_signal)
    s = MacroStrategyLab(
        combiner,
        target="^NSEI", gold_target="GOLDBEES.NS",
        long_target="NIFTYMOM30", long_cost_bps=6,
        nifty_cost_bps=3, gold_cost_bps=5,
        cash_yield_haircut_bps=100,
        apply_tax=True, tax_rate=0.15,
        enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
        recovery_latch=None, recovery_allocation="mom_gold_blend",
        vol_target_annual=0.15, vol_window=60,
        log_path=log_path,
    )
    result = s.run(raw)
    if isinstance(result, tuple):
        df, diag = result
    else:
        df = result; diag = {}
    return df.loc[start:end], diag


def state_decomposition(df, raw, year):
    """Decompose annual pretax return by state. Returns a dict of contributions."""
    yr = df[df.index.year == year]
    mom_r = raw["NIFTYMOM30"].pct_change().reindex(yr.index).fillna(0.0)
    nif_r = raw["^NSEI"].pct_change().reindex(yr.index).fillna(0.0)
    gold_r = raw["GOLDBEES.NS"].pct_change().reindex(yr.index).fillna(0.0).clip(-0.5, 0.5)

    np_ = yr["nifty_position"]
    gp_ = yr["gold_position"]

    long_mask  = (np_ == 1.0)
    short_mask = (np_ == -1.0)
    gold_mask  = (np_ == 0.0) & (gp_ == 1.0)
    flat_mask  = (np_ == 0.0) & (gp_ == 0.0)

    # On each LONG day, the held asset is Mom30 (C1 has no V2 in 2018-2019)
    # but check anyway: any LONG day where the strategy was actually following
    # V2 would hold NIFTY. We approximate by assuming Mom30 on LONG.
    pretax = yr["strategy_return_pretax"]
    # Decompose ACTUAL P&L on each subset (strategy_return_pretax)
    cum_long  = float((1 + pretax[long_mask]).prod() - 1)
    cum_flat  = float((1 + pretax[flat_mask]).prod() - 1)
    cum_gold  = float((1 + pretax[gold_mask]).prod() - 1)
    cum_short = float((1 + pretax[short_mask]).prod() - 1)
    cum_total = float((1 + pretax).prod() - 1)

    # NIFTY's return on each subset (opportunity cost vs. flat days)
    nifty_on_long  = float((1 + nif_r[long_mask]).prod()  - 1)
    nifty_on_flat  = float((1 + nif_r[flat_mask]).prod()  - 1)
    nifty_on_gold  = float((1 + nif_r[gold_mask]).prod()  - 1)
    nifty_on_short = float((1 + nif_r[short_mask]).prod() - 1)
    nifty_full     = float((1 + nif_r).prod() - 1)

    mom_on_long  = float((1 + mom_r[long_mask]).prod()  - 1)
    mom_on_flat  = float((1 + mom_r[flat_mask]).prod()  - 1)
    mom_full     = float((1 + mom_r).prod() - 1)

    gold_on_gold = float((1 + gold_r[gold_mask]).prod() - 1)

    return {
        "year": year,
        "n_long": int(long_mask.sum()),
        "n_short": int(short_mask.sum()),
        "n_gold": int(gold_mask.sum()),
        "n_flat": int(flat_mask.sum()),
        "n_total": len(yr),
        "cum_long":  cum_long, "cum_short": cum_short, "cum_gold": cum_gold,
        "cum_flat":  cum_flat, "cum_total": cum_total,
        "nifty_on_long":  nifty_on_long,  "nifty_on_short": nifty_on_short,
        "nifty_on_gold":  nifty_on_gold,  "nifty_on_flat":  nifty_on_flat,
        "nifty_full":     nifty_full,
        "mom_on_long":    mom_on_long,    "mom_on_flat":    mom_on_flat,
        "mom_full":       mom_full,
        "gold_on_gold":   gold_on_gold,
    }


def list_slow_stress_firings(raw, start, end):
    """Return DataFrame of all slow-stress firing days with conditions + outcomes."""
    inr_w = raw["INR=X"].pct_change(20)
    vix = raw["^INDIAVIX"]
    z = (vix - vix.rolling(90).mean()) / vix.rolling(90).std()
    vix_mom5 = vix - vix.shift(5)
    fires = (inr_w > 0.01) & (z > 1.5) & (vix_mom5 > 0)
    fires = fires.fillna(False)

    # Group consecutive firing days into "runs"
    nifty = raw["^NSEI"]
    nifty_20d_fwd = nifty.shift(-20) / nifty - 1
    nifty_60d_fwd = nifty.shift(-60) / nifty - 1
    df = pd.DataFrame({
        "fire": fires, "inr_20d": inr_w, "vix_z90": z, "vix_mom5": vix_mom5,
        "nifty_20d_fwd": nifty_20d_fwd, "nifty_60d_fwd": nifty_60d_fwd,
    })
    df = df.loc[start:end]
    fire_days = df[df["fire"]].copy()

    # Tag each firing with the length of its run
    fire_idx = list(fire_days.index)
    all_idx = list(df.index)
    run_lengths = []
    for d in fire_idx:
        i = all_idx.index(d)
        # Look back for consecutive fires
        consec = 1
        j = i - 1
        while j >= 0 and df["fire"].iloc[j]:
            consec += 1
            j -= 1
        run_lengths.append(consec)
    fire_days["run_length_at_this_day"] = run_lengths
    return fire_days


def main():
    START, END = "2008-04-01", "2025-12-31"
    raw = _load_data()

    print("\n[1/4] Running baseline C1 ...", file=sys.stderr)
    base_ss = SlowStressSignal(inr_window=20, inr_threshold=0.01,
                               vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
    df_base, _ = run_strategy(base_ss, raw, START, END)

    print("[2/4] Running C1 with slow-stress 3-day confirmation ...", file=sys.stderr)
    conf_ss = SlowStressConfirmedSignal(confirm_days=3, inr_window=20, inr_threshold=0.01,
                                        vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
    df_conf, _ = run_strategy(conf_ss, raw, START, END)

    print("[3/4] Running C1 with slow-stress 2-day confirmation ...", file=sys.stderr)
    conf2_ss = SlowStressConfirmedSignal(confirm_days=2, inr_window=20, inr_threshold=0.01,
                                         vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
    df_conf2, _ = run_strategy(conf2_ss, raw, START, END)

    print("[4/4] Running C1 with slow-stress disabled in 2018-2019 (oracle) ...", file=sys.stderr)
    oracle_ss = SlowStressOracleSignal(skip_years=(2018, 2019), inr_window=20, inr_threshold=0.01,
                                       vix_z_window=90, vix_z_threshold=1.5, vix_mom_window=5)
    df_oracle, _ = run_strategy(oracle_ss, raw, START, END)

    out = []
    def p(s=""): print(s); out.append(s)

    p("\n" + "=" * 140)
    p("  DEEP-DIVE FORENSICS — 2018 and 2019")
    p("=" * 140)
    p()
    p("  Two questions:")
    p("    Q1. If Mom30 was +21% on 2019 LONG days, why is the 2019 strategy only +1.14%?")
    p("    Q2. Does a 3-day slow-stress persistence requirement fix 2019 without breaking other years?")
    p()

    # ===== Q1: where the money went in 2018 and 2019 =====
    p("=" * 140)
    p("  Q1. WHERE THE MONEY WENT — annual P&L decomposition by STATE")
    p("=" * 140)
    p()
    p("  cum_long  = compounded strategy P&L on days strategy was LONG (held Mom30)")
    p("  cum_flat  = compounded strategy P&L on days strategy was FLAT (cash yield)")
    p("  cum_gold  = compounded strategy P&L on days strategy held GOLD (stress-flat + G10 gate)")
    p("  cum_short = compounded strategy P&L on days strategy was SHORT")
    p("  cum_total = full-year strategy P&L (must equal annual return)")
    p()
    p("  *** Mom30 / NIFTY on each subset shows what the UNDERLYING asset did ***")
    p("  *** during those days — not the strategy's return.                    ***")
    p()
    for y in [2018, 2019]:
        d = state_decomposition(df_base, raw, y)
        p(f"  {y}: total {d['n_total']} trading days")
        p(f"      LONG  days={d['n_long']:>3}    strategy_cum={d['cum_long']*100:+7.2f}%   "
          f"Mom30_on_long={d['mom_on_long']*100:+7.2f}%   NIFTY_on_long={d['nifty_on_long']*100:+7.2f}%")
        p(f"      FLAT  days={d['n_flat']:>3}    strategy_cum={d['cum_flat']*100:+7.2f}%   "
          f"Mom30_on_flat={d['mom_on_flat']*100:+7.2f}%   NIFTY_on_flat={d['nifty_on_flat']*100:+7.2f}%")
        p(f"      GOLD  days={d['n_gold']:>3}    strategy_cum={d['cum_gold']*100:+7.2f}%   "
          f"gold_on_gold ={d['gold_on_gold']*100:+7.2f}%   NIFTY_on_gold={d['nifty_on_gold']*100:+7.2f}%")
        p(f"      SHORT days={d['n_short']:>3}    strategy_cum={d['cum_short']*100:+7.2f}%   "
          f"NIFTY_on_short={d['nifty_on_short']*100:+7.2f}%")
        p(f"      TOTAL              strategy_cum={d['cum_total']*100:+7.2f}%   "
          f"NIFTY_full   ={d['nifty_full']*100:+7.2f}%   Mom30_full   ={d['mom_full']*100:+7.2f}%")
        # Multiplicative check: (1+long)(1+flat)(1+gold)(1+short) should ≈ (1+total)
        check = (1+d['cum_long'])*(1+d['cum_flat'])*(1+d['cum_gold'])*(1+d['cum_short']) - 1
        p(f"      Check: (1+L)(1+F)(1+G)(1+S)-1 = {check*100:+7.2f}%  vs total {d['cum_total']*100:+7.2f}%")
        # Opportunity cost: what NIFTY did on non-long days
        if d['n_long'] < d['n_total']:
            # NIFTY return outside LONG days
            non_long_nif = (1 + d['nifty_full']) / (1 + d['nifty_on_long']) - 1
            p(f"      → NIFTY return on NON-LONG days (flat+gold+short): {non_long_nif*100:+7.2f}%")
        p()

    # ===== Slow-stress firings detail =====
    p("=" * 140)
    p("  SLOW-STRESS FIRINGS — 2017 through 2025 (showing 2018-2019 and other years)")
    p("=" * 140)
    p()
    fires = list_slow_stress_firings(raw, "2017-01-01", "2025-12-31")
    p(f"  {'Date':<12} {'INR 20d':>9} {'VIX z90':>9} {'VIX 5d mom':>11} {'Run len':>8} "
      f"{'NIFTY 20d fwd':>14} {'NIFTY 60d fwd':>14}")
    p("  " + "-"*12 + " " + "-"*9 + " " + "-"*9 + " " + "-"*11 + " " + "-"*8 + " " + "-"*14 + " " + "-"*14)
    for d, row in fires.iterrows():
        inr = row["inr_20d"]*100 if pd.notna(row["inr_20d"]) else 0
        vz = row["vix_z90"] if pd.notna(row["vix_z90"]) else 0
        vm = row["vix_mom5"] if pd.notna(row["vix_mom5"]) else 0
        rl = int(row["run_length_at_this_day"])
        f20 = row["nifty_20d_fwd"]*100 if pd.notna(row["nifty_20d_fwd"]) else 0
        f60 = row["nifty_60d_fwd"]*100 if pd.notna(row["nifty_60d_fwd"]) else 0
        p(f"  {d.strftime('%Y-%m-%d')} {inr:>+7.2f}% {vz:>+8.2f} {vm:>+10.2f} {rl:>8d} "
          f"{f20:>+12.2f}% {f60:>+12.2f}%")
    # Per-year fire counts
    by_year = fires.groupby(fires.index.year).size()
    p()
    p(f"  Per-year fire counts: {dict(by_year)}")
    # Counts of run_length=1 vs ≥2 vs ≥3 fires
    p(f"  Total firings: {len(fires)}")
    p(f"  Of which run_length=1 (1-day spikes):     {(fires['run_length_at_this_day']==1).sum()}")
    p(f"  Of which run_length=2:                    {(fires['run_length_at_this_day']==2).sum()}")
    p(f"  Of which run_length≥3 (persistent):       {(fires['run_length_at_this_day']>=3).sum()}")
    p()

    # ===== Q2: slow-stress confirmation test =====
    p("=" * 140)
    p("  Q2. SLOW-STRESS 3-DAY CONFIRMATION — test on FULL strategy")
    p("=" * 140)
    p()
    p("  The rule: slow-stress only force-flats AFTER 3 consecutive raw firings.")
    p("  Once confirmed, it continues to flat on subsequent firing days (no cooldown reset).")
    p()
    p(f"  {'Variant':<25} {'CAGR':>9} {'Sharpe':>8} {'Calmar':>8} {'MaxDD':>9} {'ΔCAGR vs base':>14}")
    p("  " + "-"*25 + " " + "-"*9 + " " + "-"*8 + " " + "-"*8 + " " + "-"*9 + " " + "-"*14)
    base_m = metrics(df_base["strategy_return"])
    for name, df in [("C1 baseline (1-day)", df_base),
                     ("C1 + 2-day confirm",  df_conf2),
                     ("C1 + 3-day confirm",  df_conf),
                     ("C1 + skip SS 2018-19 (oracle)", df_oracle)]:
        m = metrics(df["strategy_return"])
        dc = m["cagr"] - base_m["cagr"]
        if name == "C1 baseline (1-day)":
            p(f"  {name:<25} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {'—':>14}")
        else:
            p(f"  {name:<25} {m['cagr']*100:+7.2f}% {m['sharpe']:>8.3f} {m['calmar']:>8.2f} {m['max_dd']*100:+8.2f}% {dc*100:+13.2f}pp")
    p()

    # Year-by-year
    p("=" * 140)
    p("  YEAR-BY-YEAR comparison (post-tax)")
    p("=" * 140)
    years = sorted(set(df_base.index.year))
    p(f"  {'Year':<6} {'C1 base':>9} {'+2d conf':>9} {'+3d conf':>9} {'SS oracle 18-19':>16} {'NIFTY':>9}")
    p("  " + "-"*6 + " " + "-"*9 + " " + "-"*9 + " " + "-"*9 + " " + "-"*16 + " " + "-"*9)
    nifty_close = raw["^NSEI"].loc[START:END]
    for y in years:
        s_base = df_base["strategy_return"][df_base.index.year == y]
        s_c2 = df_conf2["strategy_return"][df_conf2.index.year == y]
        s_c3 = df_conf["strategy_return"][df_conf.index.year == y]
        s_or = df_oracle["strategy_return"][df_oracle.index.year == y]
        b = float((1+s_base).prod()-1)*100
        c2v = float((1+s_c2).prod()-1)*100
        c3v = float((1+s_c3).prod()-1)*100
        ov = float((1+s_or).prod()-1)*100
        ny = nifty_close[nifty_close.index.year == y]
        nv = float(ny.iloc[-1]/ny.iloc[0]-1)*100 if len(ny)>1 else 0
        p(f"  {y:<6} {b:>+7.2f}% {c2v:>+7.2f}% {c3v:>+7.2f}% {ov:>+14.2f}% {nv:>+7.2f}%")
    p()

    # 2018-19 specific
    p("=" * 140)
    p("  2018+2019 COMPOUND — what each variant does on the two bad years")
    p("=" * 140)
    for name, df in [("C1 baseline", df_base),
                     ("C1 + 2-day confirm", df_conf2),
                     ("C1 + 3-day confirm", df_conf),
                     ("C1 + skip SS 2018-19", df_oracle)]:
        s = df["strategy_return"][df.index.year.isin([2018,2019])]
        cum = float((1+s).prod()-1)*100
        p(f"  {name:<25} 2018+19 cum = {cum:+6.2f}%")
    p()

    # COVID and 2008 sanity check
    p("=" * 140)
    p("  SANITY: does 3-day confirmation break COVID (2020) or GFC (2008)?")
    p("=" * 140)
    for y in [2008, 2013, 2018, 2020]:
        s_base = df_base["strategy_return"][df_base.index.year == y]
        s_conf = df_conf["strategy_return"][df_conf.index.year == y]
        b = float((1+s_base).prod()-1)*100
        c = float((1+s_conf).prod()-1)*100
        p(f"  {y}: baseline {b:+7.2f}%   3-day-confirm {c:+7.2f}%   Δ {c-b:+5.2f}pp")
    p()

    txt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results", "deep_dive_2018_2019_forensics.txt")
    with open(txt, "w") as f:
        f.write("\n".join(out))
    print(f"\nSaved to {txt}", file=sys.stderr)


if __name__ == "__main__":
    main()

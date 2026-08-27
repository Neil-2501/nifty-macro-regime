"""
readme_audit.py — comprehensive audit of README.md numeric claims against
actual strategy execution and existing results files.

Runs v2.1 baseline on:
  (a) 2008-04-01 to 2025-12-31 (as cited in README headline)
  (b) 2008-04-01 to latest available (extended OOS)

Verifies all numeric claims, year-by-year table, crisis windows, and
pre-computed results files (walk-forward, vol scaling, cross-country).
Checks plot existence + cross-references all test script paths.

Output: results/readme_audit_v21_full_sample.txt (raw run data)
        + audit findings printed to stdout for compilation into report.
"""

import os
import re
import sys
import pickle

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import strategy as s
from strategy_lab import _load_data

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(REPO_ROOT, "results")
PLOTS_DIR = os.path.join(REPO_ROOT, "plots")
IMAGES_DIR = os.path.join(REPO_ROOT, "images")
README = os.path.join(REPO_ROOT, "README.md")


def run_v21(raw, sd, ed):
    """v2.1 baseline (Config 7 with G10 gold rotation on stress-flat days).
    Explicitly disables the v2.2 defensive basket so this function truly
    audits the v2.1-era numbers claimed in the pre-v2.2 README.
    For v2.2 R1 numbers use `run_r1` (not in this legacy script)."""
    combiner = s.make_combiner(True, False, use_momentum_gold=True,
                               slow_stress_lock_days=5,
                               panic_short_dd_threshold=0.15)
    strat = s.MacroStrategy(combiner, target="^NSEI", gold_target="GOLDBEES.NS",
                            nifty_cost_bps=3, gold_cost_bps=5,
                            long_target="NIFTYMOM30", long_cost_bps=6,
                            apply_tax=True, tax_rate=0.15,
                            enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
                            enable_defensive_basket=False)
    df = strat.run(raw).loc[sd:ed]
    # Also pretax variant for sanity
    strat_pre = s.MacroStrategy(combiner, target="^NSEI", gold_target="GOLDBEES.NS",
                                nifty_cost_bps=3, gold_cost_bps=5,
                                long_target="NIFTYMOM30", long_cost_bps=6,
                                apply_tax=False,
                                enable_v2=True, v2_dd_threshold=0.15, v2_days=60,
                                enable_defensive_basket=False)
    df_pre = strat_pre.run(raw).loc[sd:ed]
    return df, df_pre


def metrics_pack(ret_series, label=""):
    m = s.metrics(ret_series)
    cum = float(((1 + ret_series).cumprod().iloc[-1] - 1) * 100)
    vol = float(ret_series.std() * np.sqrt(252) * 100)
    return {
        "label": label,
        "cagr_pct": round(m["cagr"] * 100, 4),
        "sharpe": round(m["sharpe"], 4),
        "sortino": round(m["sortino"], 4) if pd.notna(m["sortino"]) else np.nan,
        "calmar": round(m["calmar"], 4) if pd.notna(m["calmar"]) else np.nan,
        "vol_pct": round(vol, 4),
        "max_dd_pct": round(m["max_dd"] * 100, 4),
        "cum_return_pct": round(cum, 4),
    }


def apply_lt_tax_annual_net(series, tax_rate=0.10):
    """Apply 10% LT cap gains annual-net (matching apply_annual_tax convention)."""
    return s.apply_annual_tax(series.fillna(0.0), tax_rate=tax_rate)


def severity(deviation, val_type="pct"):
    """Classify deviation magnitude.
    val_type 'pct' for percentages (e.g. CAGR), 'ratio' for ratios (e.g. Sharpe).
    Cosmetic: |deviation| <= 0.01; material: 0.01-0.10; critical: >0.10."""
    abs_dev = abs(deviation)
    if abs_dev <= 0.01:
        return "cosmetic"
    if abs_dev <= 0.10:
        return "material"
    return "critical"


def main():
    print("=" * 120)
    print("  README AUDIT — v2.1 baseline against current codebase")
    print("=" * 120)

    raw = _load_data()
    end_date_extended = min(raw["^NSEI"].dropna().index.max(),
                            raw["NIFTYMOM30"].dropna().index.max()).strftime("%Y-%m-%d")

    # ========================================================================
    # PART 1a — v2.1 baseline 2008-2025 (README's claimed sample)
    # ========================================================================
    SD = "2008-04-01"
    ED_25 = "2025-12-31"
    print(f"\nRunning v2.1 baseline {SD} to {ED_25} ...")
    df_25, df_25_pre = run_v21(raw, SD, ED_25)

    m25 = metrics_pack(df_25["strategy_return"], "Strategy v2.1 2008-2025 post-tax")
    m25_pre = metrics_pack(df_25_pre["strategy_return"], "Strategy v2.1 2008-2025 pre-tax")

    # NIFTY 50 B&H post-tax (10% LT cap gains)
    nifty = raw["^NSEI"].dropna()
    nifty_ret = nifty.pct_change().loc[SD:ED_25].fillna(0.0)
    nifty_posttax_ret = apply_lt_tax_annual_net(nifty_ret, tax_rate=0.10)
    nifty_pre = metrics_pack(nifty_ret, "NIFTY B&H 2008-2025 pre-tax")
    nifty_post = metrics_pack(nifty_posttax_ret, "NIFTY B&H 2008-2025 post-10%LT")

    print(f"\nv2.1 STRATEGY 2008-2025 (post-tax):")
    for k, v in m25.items():
        if k != "label":
            print(f"  {k}: {v}")
    print(f"\nv2.1 STRATEGY 2008-2025 (pre-tax):")
    for k, v in m25_pre.items():
        if k != "label":
            print(f"  {k}: {v}")
    print(f"\nNIFTY B&H 2008-2025 (pre-tax):")
    for k, v in nifty_pre.items():
        if k != "label":
            print(f"  {k}: {v}")
    print(f"\nNIFTY B&H 2008-2025 (post-10%LT):")
    for k, v in nifty_post.items():
        if k != "label":
            print(f"  {k}: {v}")

    # ========================================================================
    # PART 1b — Verify headline claims
    # ========================================================================
    print("\n" + "=" * 120)
    print("  CLAIMED vs ACTUAL — headline numbers")
    print("=" * 120)
    claims = [
        ("Strategy CAGR (post-tax)", 16.75, m25["cagr_pct"], "pct"),
        ("Strategy Sharpe (RF=6%)", 0.84, m25["sharpe"], "ratio"),
        ("Strategy Sortino", 1.01, m25["sortino"], "ratio"),
        ("Strategy Calmar", 1.31, m25["calmar"], "ratio"),
        ("Strategy ann. vol", 12.16, m25["vol_pct"], "pct"),
        ("Strategy MaxDD", -12.78, m25["max_dd_pct"], "pct"),
        ("Strategy cum return", 1623.6, m25["cum_return_pct"], "pct"),
        ("Strategy pre-tax CAGR", 19.93, m25_pre["cagr_pct"], "pct"),
        ("NIFTY B&H post-tax CAGR", 8.37, nifty_post["cagr_pct"], "pct"),
        ("NIFTY B&H Sharpe", 0.20, nifty_post["sharpe"], "ratio"),
        ("NIFTY B&H MaxDD", -51.72, nifty_post["max_dd_pct"], "pct"),
        ("NIFTY B&H cum return", 338.5, nifty_post["cum_return_pct"], "pct"),
        ("NIFTY pre-tax CAGR", 9.73, nifty_pre["cagr_pct"], "pct"),
    ]
    print(f"  {'Metric':<35} {'CLAIMED':>10} {'ACTUAL':>10} {'DEV':>10}  SEVERITY")
    print("  " + "-"*35 + " " + "-"*10 + " " + "-"*10 + " " + "-"*10 + "  " + "-"*9)
    audit_rows = []
    for label, claimed, actual, vtype in claims:
        dev = actual - claimed
        sev = severity(dev, vtype)
        print(f"  {label:<35} {claimed:>10.4f} {actual:>10.4f} {dev:>+10.4f}  {sev}")
        audit_rows.append({"metric": label, "claimed": claimed, "actual": actual,
                           "deviation": round(dev, 4), "severity": sev})

    # ========================================================================
    # PART 1c — Extended through latest data
    # ========================================================================
    print(f"\n{'='*120}")
    print(f"  EXTENDED RUN through {end_date_extended}")
    print(f"{'='*120}")
    df_ext, df_ext_pre = run_v21(raw, SD, end_date_extended)
    m_ext = metrics_pack(df_ext["strategy_return"],
                          f"Strategy v2.1 2008-{end_date_extended} post-tax")
    print(f"\nv2.1 STRATEGY {SD} to {end_date_extended} (post-tax):")
    for k, v in m_ext.items():
        if k != "label":
            print(f"  {k}: {v}")

    # 2026 YTD claims
    nifty_ext = raw["^NSEI"].dropna()
    nifty_ext_ret = nifty_ext.pct_change().loc[SD:end_date_extended].fillna(0.0)
    nifty_ext_post = apply_lt_tax_annual_net(nifty_ext_ret, tax_rate=0.10)

    sub_2026 = df_ext[df_ext.index.year == 2026]["strategy_return"]
    nifty_2026 = nifty_ext[nifty_ext.index.year == 2026]
    strat_2026_ret = float((1 + sub_2026).prod() - 1) * 100
    nifty_2026_ret = float(nifty_2026.iloc[-1] / nifty_2026.iloc[0] - 1) * 100

    # March 2026 specifically
    march_strat = df_ext.loc["2026-03-01":"2026-03-31"]["strategy_return"]
    march_nifty = nifty_ext.loc["2026-03-01":"2026-03-31"]
    march_strat_ret = float((1 + march_strat).prod() - 1) * 100
    march_nifty_ret = float(march_nifty.iloc[-1] / march_nifty.iloc[0] - 1) * 100

    print(f"\n2026 YTD (through {end_date_extended}):")
    print(f"  Strategy 2026 YTD: {strat_2026_ret:+.4f}%")
    print(f"  NIFTY 50 B&H 2026 YTD: {nifty_2026_ret:+.4f}%")
    print(f"  March 2026 Strategy: {march_strat_ret:+.4f}%")
    print(f"  March 2026 NIFTY: {march_nifty_ret:+.4f}%")

    claims_2026 = [
        ("Strategy 2026 YTD", 2.0, strat_2026_ret, "pct"),
        ("NIFTY 2026 YTD", -8.9, nifty_2026_ret, "pct"),
        ("March 2026 Strategy", 0.33, march_strat_ret, "pct"),
        ("March 2026 NIFTY", -10.19, march_nifty_ret, "pct"),
    ]
    print(f"\n  {'2026 metric':<28} {'CLAIMED':>10} {'ACTUAL':>10} {'DEV':>10}  SEVERITY")
    print("  " + "-"*28 + " " + "-"*10 + " " + "-"*10 + " " + "-"*10 + "  " + "-"*9)
    for label, claimed, actual, vtype in claims_2026:
        dev = actual - claimed
        sev = severity(dev, vtype)
        print(f"  {label:<28} {claimed:>10.4f} {actual:>10.4f} {dev:>+10.4f}  {sev}")
        audit_rows.append({"metric": label, "claimed": claimed, "actual": actual,
                           "deviation": round(dev, 4), "severity": sev})

    # ========================================================================
    # PART 1d — Year-by-year verification
    # ========================================================================
    print(f"\n{'='*120}")
    print("  YEAR-BY-YEAR — claimed vs actual")
    print(f"{'='*120}")

    # Compute actual yearly returns
    def yearly_returns(series):
        return {y: float((1 + series[series.index.year == y]).prod() - 1) * 100
                for y in sorted(set(series.index.year))}

    yr_strat = yearly_returns(df_25["strategy_return"])
    yr_nifty_post = yearly_returns(nifty_posttax_ret)

    # README year-by-year table (lines 346-363)
    readme_yearly = {
        2008: (3.8, -37.6),  2009: (76.5, 67.0),  2010: (19.0, 16.2),
        2011: (-3.2, -24.6), 2012: (25.4, 24.7),  2013: (1.5, 6.2),
        2014: (30.2, 27.9),  2015: (0.6, -4.1),   2016: (19.0, 2.8),
        2017: (27.6, 25.5),  2018: (-6.1, 2.9),   2019: (4.7, 10.9),
        2020: (46.3, 13.8),  2021: (40.2, 21.6),  2022: (1.4, 4.0),
        2023: (23.9, 17.9),  2024: (20.9, 8.0),   2025: (5.2, 9.5),
    }
    print(f"\n  {'Year':<6} {'Claim S':>8} {'Actual S':>9} {'Dev S':>8}  "
          f"{'Claim N':>8} {'Actual N':>9} {'Dev N':>8}")
    print("  " + "-"*6 + " " + "-"*8 + " " + "-"*9 + " " + "-"*8 + "  "
          + "-"*8 + " " + "-"*9 + " " + "-"*8)
    yearly_audit = []
    for y in sorted(readme_yearly.keys()):
        cs, cn = readme_yearly[y]
        as_ = yr_strat.get(y, np.nan)
        an = yr_nifty_post.get(y, np.nan)
        ds = as_ - cs
        dn = an - cn
        print(f"  {y:<6} {cs:>+7.2f}% {as_:>+7.4f}% {ds:>+7.2f} "
              f"{cn:>+7.2f}% {an:>+7.4f}% {dn:>+7.2f}")
        yearly_audit.append({
            "year": y, "readme_strategy_pct": cs, "actual_strategy_pct": round(as_, 4),
            "deviation_strategy": round(ds, 4),
            "readme_nifty_pct": cn, "actual_nifty_pct": round(an, 4),
            "deviation_nifty": round(dn, 4)})

    # ========================================================================
    # PART 1e — Crisis windows
    # ========================================================================
    print(f"\n{'='*120}")
    print("  CRISIS WINDOWS — claimed vs actual")
    print(f"{'='*120}")

    crisis_windows = [
        ("GFC", "2008-09-01", "2009-03-31", 2.1, -30.8),
        ("Euro debt", "2011-07-01", "2011-12-31", 1.0, -18.1),
        ("Taper Tantrum", "2013-05-01", "2013-09-30", -0.3, -2.9),
        ("NBFC / IL&FS", "2018-08-01", "2018-11-30", -0.5, -3.8),
        ("COVID Crash", "2020-02-01", "2020-05-31", 16.8, -17.8),
        ("Russia 2022", "2022-02-01", "2022-06-30", -1.7, -8.1),
        ("Momentum sell-off 2025-26", "2025-10-01", "2026-04-30", 1.6, 5.5),
    ]
    print(f"\n  {'Crisis':<30} {'Window':<26} {'Claim S':>9} {'Actual S':>10} "
          f"{'Claim N':>9} {'Actual N':>10}")
    print("  " + "-"*30 + " " + "-"*26 + " " + "-"*9 + " " + "-"*10 + " "
          + "-"*9 + " " + "-"*10)
    crisis_audit = []
    for name, sd, ed, claim_s, claim_n in crisis_windows:
        s_sub = df_ext.loc[sd:ed]["strategy_return"]
        n_sub = nifty_ext.loc[sd:ed]
        if len(s_sub) < 2 or len(n_sub) < 2:
            actual_s = actual_n = np.nan
        else:
            actual_s = float((1 + s_sub).prod() - 1) * 100
            actual_n = float(n_sub.iloc[-1] / n_sub.iloc[0] - 1) * 100
        ds = actual_s - claim_s
        dn = actual_n - claim_n
        print(f"  {name:<30} {sd}→{ed} {claim_s:>+8.2f}% {actual_s:>+8.4f}% "
              f"{claim_n:>+8.2f}% {actual_n:>+8.4f}%")
        crisis_audit.append({
            "crisis": name, "start": sd, "end": ed,
            "readme_strategy_pct": claim_s, "actual_strategy_pct": round(actual_s, 4),
            "deviation_strategy": round(ds, 4),
            "readme_nifty_pct": claim_n, "actual_nifty_pct": round(actual_n, 4),
            "deviation_nifty": round(dn, 4)})

    # ========================================================================
    # PART 2 — Pre-computed results verification
    # ========================================================================
    print(f"\n{'='*120}")
    print("  PART 2 — Pre-computed results files")
    print(f"{'='*120}")

    # 2a Walk-forward
    wf_csv = os.path.join(RESULTS_DIR, "test_walkforward_per_window.csv")
    if os.path.exists(wf_csv):
        wf_df = pd.read_csv(wf_csv)
        print(f"\nWALK-FORWARD ({len(wf_df)} windows):")
        print(f"  Mean OOS CAGR opt: {wf_df['oos_cagr_opt_pct'].mean():.4f}%")
        print(f"  Mean OOS CAGR prod: {wf_df['oos_cagr_prod_pct'].mean():.4f}%")
        # Read the summary text for concatenated metrics
        wf_txt = os.path.join(RESULTS_DIR, "test_walkforward.txt")
        if os.path.exists(wf_txt):
            with open(wf_txt) as f:
                wf_text = f.read()
            # Extract key metrics
            for line in wf_text.split("\n"):
                if "Concatenated OOS" in line or "Geometric mean OOS" in line:
                    print(f"  {line.strip()}")
    else:
        print("\nWalk-forward CSV not found!")

    # 2b Vol scaling
    vs_summary = os.path.join(RESULTS_DIR, "test_vol_scaling_exhaustive_summary.csv")
    if os.path.exists(vs_summary):
        vs_df = pd.read_csv(vs_summary)
        print(f"\nVOL SCALING ({len(vs_df)} variants):")
        print(f"  Best full Δ: {vs_df['full_cagr_delta_pp'].max():+.4f}pp "
              f"({vs_df.loc[vs_df['full_cagr_delta_pp'].idxmax(), 'code']})")
        print(f"  Worst full Δ: {vs_df['full_cagr_delta_pp'].min():+.4f}pp "
              f"({vs_df.loc[vs_df['full_cagr_delta_pp'].idxmin(), 'code']})")
        # MaxDD across variants
        if 'maxdd_delta_pp' in vs_df.columns:
            print(f"  MaxDD Δ range: {vs_df['maxdd_delta_pp'].min():.4f}pp to "
                  f"{vs_df['maxdd_delta_pp'].max():.4f}pp")
    else:
        print("\nVol scaling summary not found!")

    # 2c Cross-country
    cc_path = os.path.join(REPO_ROOT, "validate_us_cross_country.py")
    if os.path.exists(cc_path):
        print(f"\nCross-country script exists at {cc_path}")
    else:
        print("\nCross-country script NOT FOUND at expected path!")
    cc_results = os.path.join(RESULTS_DIR, "validate_us_cross_country.txt")
    if os.path.exists(cc_results):
        print(f"Cross-country results file: exists")
    else:
        print(f"Cross-country results file: NOT FOUND (cannot verify 9/9, 3.84%, false-pos rates)")

    # ========================================================================
    # PART 3 — Plot existence
    # ========================================================================
    print(f"\n{'='*120}")
    print("  PART 3 — Plot existence check")
    print(f"{'='*120}")
    plots_to_check = [
        ("images/equity_curve.png", "Main equity curve"),
        ("images/yearly_returns.png", "Year-by-year bars"),
        ("images/drawdown.png", "Drawdown chart"),
        ("plots/test_walkforward_equity_overlay.png", "Walk-forward equity overlay"),
        ("plots/test_walkforward_parameter_drift.png", "Walk-forward parameter drift"),
    ]
    print()
    for rel_path, desc in plots_to_check:
        full = os.path.join(REPO_ROOT, rel_path)
        status = "EXISTS" if os.path.exists(full) else "MISSING"
        print(f"  [{status}] {rel_path:<55} ({desc})")

    # ========================================================================
    # PART 5 — Cross-reference test scripts mentioned in README
    # ========================================================================
    print(f"\n{'='*120}")
    print("  PART 5 — Test script paths referenced in README")
    print(f"{'='*120}")
    with open(README) as f:
        readme_text = f.read()
    # Find all `experiments/*.py` and *.py in root references
    script_pattern = re.compile(r"`((?:experiments/)?[A-Za-z_][A-Za-z_0-9]*\.py)`")
    refs = sorted(set(script_pattern.findall(readme_text)))
    print()
    script_audit = []
    for ref in refs:
        path = os.path.join(REPO_ROOT, ref)
        exists = os.path.exists(path)
        status = "OK" if exists else "BROKEN"
        print(f"  [{status}] {ref}")
        script_audit.append({"path": ref, "exists": exists})

    # ========================================================================
    # Save raw audit data
    # ========================================================================
    audit_path = os.path.join(RESULTS_DIR, "readme_audit_v21_full_sample.txt")
    with open(audit_path, "w") as f:
        f.write(f"Strategy v2.1 — Full audit run\n")
        f.write(f"Sample: {SD} to {ED_25}\n\n")
        f.write(f"Post-tax metrics:\n")
        for k, v in m25.items():
            f.write(f"  {k}: {v}\n")
        f.write(f"\nPre-tax metrics:\n")
        for k, v in m25_pre.items():
            f.write(f"  {k}: {v}\n")
        f.write(f"\nNIFTY B&H post-tax (10% LT):\n")
        for k, v in nifty_post.items():
            f.write(f"  {k}: {v}\n")
        f.write(f"\nExtended sample: {SD} to {end_date_extended}\n")
        for k, v in m_ext.items():
            f.write(f"  {k}: {v}\n")
        f.write(f"\nYear-by-year strategy post-tax:\n")
        for y in sorted(yr_strat.keys()):
            f.write(f"  {y}: {yr_strat[y]:.4f}%\n")
        f.write(f"\nYear-by-year NIFTY B&H post-tax (10% LT):\n")
        for y in sorted(yr_nifty_post.keys()):
            f.write(f"  {y}: {yr_nifty_post[y]:.4f}%\n")
    print(f"\nSaved raw audit data to: {audit_path}")

    # Save structured audit artifacts as CSV
    pd.DataFrame(audit_rows).to_csv(
        os.path.join(RESULTS_DIR, "readme_audit_headline_claims.csv"), index=False)
    pd.DataFrame(yearly_audit).to_csv(
        os.path.join(RESULTS_DIR, "readme_audit_yearly.csv"), index=False)
    pd.DataFrame(crisis_audit).to_csv(
        os.path.join(RESULTS_DIR, "readme_audit_crisis_windows.csv"), index=False)
    pd.DataFrame(script_audit).to_csv(
        os.path.join(RESULTS_DIR, "readme_audit_script_paths.csv"), index=False)
    print(f"Saved audit CSVs to {RESULTS_DIR}")


if __name__ == "__main__":
    main()

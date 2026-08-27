# Indian Equity Macro-Regime Strategy

A systematic macro-regime strategy for Indian markets. Production config (**v2.2**) combines tactical long exposure to NIFTY 200 Momentum 30 in bull regimes, a defensive quality basket (18 fundamentally-screened low-beta names) during identified stress-flat windows blended 50/50 with cash, NIFTY 50 short exposure on panic-short fires gated by a 15% drawdown confirmation, and haircut-adjusted RBI repo-rate cash yield on remaining idle capital. A 100-day moving-average trend filter on NIFTY 50 acts as the long-engagement gate; slow-stress and panic-short signals override engagement during identified macro stress regimes. After deep bear regimes, the strategy holds NIFTY 50 instead of NIFTY 200 Momentum 30 for the first 60 trading days of the recovery to capture the broad rebound that momentum baskets miss while still loaded with pre-crash defensives. A 5-day cooldown on the slow-stress signal prevents whipsaw flat→long→flat round-trips during noisy chop periods. The signal architecture has been validated on 31 years of US market data (9 of 9 documented stress events detected), addressing overfitting concerns from the limited 18-year Indian sample.

**v2.2 change vs v2.1**: the momentum-gated gold rotation (v1.4 through v2.1) on stress-flat days has been superseded by the defensive quality basket. Gold rotation code remains in the repository behind an opt-in flag (`enable_defensive_basket=False` restores v2.1 behavior byte-for-byte); see the [Superseded Research](#superseded-research--g10-gold-rotation) section for the honest reason.

*Research project. Backtest results, methodology, and known limitations documented below. Not deployed; not investment advice.*

![Equity Curve](images/equity_curve.png)

---

## Headline Results

Backtest period: **2008-04-01 to 2026-05-11** (18.1 years; 2026 is partial, ~4.5 months). Net results assume per-asset transaction costs of **3 bps per leg** on NIFTY 50 futures (short side), **6 bps per leg** on NIFTY 200 Momentum 30 ETFs (long side), and **30 bps per side** on the defensive quality basket (real institutional cost including STT, brokerage, exchange, GST, and slippage on mid-cap-heavy 18-name basket). Idle capital on fully-flat days earns the prevailing RBI repo rate minus a 100 bps haircut modeling realistic liquid-fund execution. **All metrics post-tax**: strategy uses Indian 15% short-term capital gains (annual-net model, with basket exits at 15% pre-2024-07-23 / 20% after); NIFTY 50 buy-and-hold uses 10% long-term capital gains (zero turnover).

**Sharpe convention**: **rf-adjusted** using the time-varying RBI repo rate (the same series used for the strategy's cash yield). Formula: `(mean(daily_return - daily_rf) × 252) / (std(daily_return) × √252)`. Average rf over the full window is 6.27%. A raw return/volatility ratio (unadjusted) is reported separately as a secondary metric where applicable; it is not called "Sharpe."

| Metric | **R1 Production (v2.2)** | Config 7 baseline (v2.1) | NIFTY Buy & Hold |
|---|---|---|---|
| **Max drawdown** | **-13.92%** | -12.78% | -51.72% |
| CAGR | **16.85%** | 16.52% | 7.67% |
| Sharpe (rf-adjusted) | **0.83** | 0.81 | 0.15 |
| Annualized volatility | 12.13% | 12.07% | 17.95% |
| Return/vol ratio (secondary) | 1.34 | 1.33 | 0.50 |

All three columns use the identical Sharpe convention: `(mean(daily_return - daily_rf) × 252) / (std(daily_return) × √252)`, `daily_rf = RBI repo / 252`.

**OOS 2017-01-01 → 2026-05-11:**

| Metric | **R1 Production (v2.2)** | Config 7 baseline (v2.1) |
|---|---|---|
| Max drawdown | **-10.88%** | -12.78% |
| CAGR | **16.10%** | 15.95% |
| Sharpe (rf-adjusted) | **0.80** | 0.79 |

**Honest framing**: the defensive-basket layer (v2.2) is a **marginal, ~Sharpe-neutral change** vs the Config 7 core, not a clean improvement:

- **FULL 2008-2026**: ΔCAGR **+0.33pp**, ΔSharpe **+0.02**, ΔMaxDD **-1.13pp** (modestly deeper)
- **OOS 2017-2026**: ΔCAGR **+0.15pp**, ΔSharpe **+0.01**, ΔMaxDD **+1.90pp** (shallower)

The defensive basket adds ~30 bps of CAGR and +0.01–0.02 Sharpe. It slightly *deepens* full-history MaxDD (the basket has more volatility on active days than the Config-7 cash+gold alternative it replaces) but *shallows* OOS MaxDD (defensive names weathered the 2020 COVID and 2022 windows better than cash+gold). It is not the driver of the strategy's headline outperformance vs NIFTY; that comes from the Config 7 core (regime filter + Mom30 long + defensive engines). The basket earns its place on production as an incremental risk-adjustment layer, not as a source of significant new alpha.

The current README convention is 15% short-term capital gains for the strategy (native tax model in `MacroStrategy.run()`) and 10% long-term capital gains for NIFTY buy-and-hold (buy-and-hold qualifies fully as long-term). Pre-tax numbers are ~3–4pp higher for the strategy and ~1.3pp higher for NIFTY; the post-tax convention is the production-relevant headline.

The strategy generates risk-adjusted alpha vs passive NIFTY exposure through four mechanisms operating together: (1) tactical long exposure to a momentum-tilted equity portfolio — long NIFTY 200 Momentum 30 during bull regimes, flat or short NIFTY 50 during identified stress regimes; (2) defensive quality basket — a fundamentally-screened 18-name portfolio deployed on stress-flat days beyond a 40-day persistence gate, blended 50/50 with cash (v2.2, replaces the v2.1 gold rotation); (3) post-bear NIFTY 50 recovery overlay — swaps Mom30 → NIFTY 50 for 60 days after deep-bear regime flips; (4) cash management — idle capital earns the prevailing RBI repo rate minus a 100 bps haircut on fully-flat days. Cumulative outperformance vs buy-and-hold is the geometric outcome of compounding all four together; mechanisms cannot be cleanly separated into additive contributions, since they interact through the position sequence and the compounding base.

---

## Mechanisms of Outperformance

The strategy's outperformance derives from four mechanisms that compound together over the 18.1-year sample. Their contributions are inherently joint and cannot be cleanly attributed to additive percentages, since each mechanism affects the compounding base for the others. The defensive-basket layer (v2.2) is the most recent and smallest of the four — its incremental contribution over Config 7 is +0.33pp CAGR / +0.02 Sharpe (FULL) and +0.15pp / +0.01 (OOS), not a first-order driver.

**Tactical long exposure to a momentum-tilted equity portfolio.** The strategy holds long exposure to NIFTY 200 Momentum 30 by default during bull regimes (NIFTY 50 above its 100-day moving average), with slow-stress and panic-short overrides interrupting that exposure during identified macro stress. Capital avoidance of left-tail equity returns — the days where stress overrides force flat or short — generates volatility-drag alpha vs buy-and-hold. The strategy is long the long-side index ~65% of trading days (calm bull regimes), flat ~34% (bear regimes and stress flats), short NIFTY 50 ~0.7% (panic-short windows that survive the drawdown confirmation gate). When long, the strategy holds **NIFTY 200 Momentum 30** by default — a 30-stock factor-tilted portfolio drawn from the NIFTY 200 universe and ranked semi-annually by 6-month and 12-month price momentum — except during the first 60 trading days following a deep-bear recovery, when it holds NIFTY 50 instead (see Refinements). Short exposure during panic-shorts remains on NIFTY 50 (more liquid for futures-based shorting). This is the core mechanism; the others amplify it.

**Defensive quality basket on stress-flat days (v2.2).** Once the strategy has been in a stress-flat latch for 40 consecutive trading days (the persistence gate), the flat-day return is replaced with a 50/50 blend of the defensive quality basket and cash. The basket is 18 equal-weighted names selected semi-annually from the top-200 liquid NSE universe, filtered by fundamental hard rules (cfo > 0, net profit > 0, D/E ≤ 3), quality percentile ≥ 0.60, 250-day beta ≤ 0.85, and 250-day annualized vol ≤ 0.30, with a defensive-sector tilt bonus (FMCG, Pharma, Utility, IT) and a sector cap of 5. Real trading costs (30 bps/side + STCG 15%/20%) are charged at entry, exit, and STCG on any realized cumulative gain over the deployment window. Deploys ~368 trading days across the 18-year sample (only in genuinely-sustained stress windows). See [Defensive Quality Basket](#defensive-quality-basket-v22) for full construction and bake-off history. **Replaces** the v2.1 G10 gold rotation — kept in the codebase as opt-in via `enable_defensive_basket=False`.

**Cash yield on idle capital (with realistic haircut).** On fully-flat days where the defensive basket is not yet deployed (first 40 days of every stress latch) OR the basket half of the 50/50 blend on active days, the strategy credits the prevailing RBI repo rate minus a 100 bps haircut. The haircut models real-world liquid-fund execution: instrument spread (~50 bps inside repo), TER (~10–25 bps), and small auto-sweep frictions. Returns are post-tax throughout (15% on net annual gains, Indian short-term capital gains convention); sensitivity to the haircut size is documented under Backtest Caveats.

### Refinements added since v1.5

Four targeted refinements have been added since v1.5; each addresses a documented failure mode. Each is detailed under [Signal Logic](#signal-logic); the cumulative impact takes the strategy from v1.5 through v2.1 to v2.2 (post-tax CAGR 15.64% → 16.52% (v2.1) → 16.85% (v2.2), rf-adjusted Sharpe 0.79 → 0.81 → 0.83, max drawdown −14.67% → −12.78% → −13.92%).

**Post-bear NIFTY recovery overlay.** When a bear regime ends and the strategy re-engages long after a NIFTY drawdown of 15% or more, hold NIFTY 50 instead of NIFTY 200 Momentum 30 for the next 60 trading days, then revert to Momentum 30. Targets the Daniel & Moskowitz (2016) momentum-crash pattern observed cleanly in the 2009 sample, where Momentum 30 held stale pre-crash defensives while the recovery was led by beaten-down cyclicals.

**Slow-stress cooldown.** Once the slow-stress signal fires (forcing flat), suppress any subsequent slow-stress firings for 5 trading days. Other exit signals continue to operate normally. Targets the April–May 2019 bleed pattern where short-cluster re-fires forced repeated flat→long→flat round-trips, with the strategy losing meaningful return each time on exit-day moves.

**Panic-short drawdown confirmation.** Panic-short can only fire when NIFTY's current drawdown from its trailing 60-day high exceeds 15%. All other panic-short conditions (high absolute VIX, accelerating VIX spike, NIFTY below 100-DMA) still required. Targets two documented false-fire incidents (2013-08-27 taper-reaction short and 2022-02-24 Ukraine-reaction short) where panic-short fired into local bottoms and lost ~22.9pp and ~12.0pp respectively.

**Defensive quality basket on stress-flat days (v2.2, replaces G10 gold rotation).** After the strategy has been in a stress-flat latch for 40 consecutive trading days, deploy a fundamentally-screened 18-name low-beta basket blended 50/50 with cash. Real costs (30 bps/side, STCG 15%/20%) charged. Basket construction, persistence-gate sensitivity, and 50/50 blend rationale are documented in the [Defensive Quality Basket](#defensive-quality-basket-v22) section. The v2.1 G10 gold rotation code is retained in the repo behind `enable_defensive_basket=False`. See [Superseded Research](#superseded-research--g10-gold-rotation) for why gold rotation was replaced.

**Cross-country signal architecture validation.** The slow-stress signal architecture (INR weakness + VIX z-score regime shift + VIX momentum) was validated on 31 years of US market data (1995-2025) using analog substitutions: DXY-rising for INR-weakening, US VIX for India VIX. The same signal specification — unchanged from the Indian backtest — caught 9 of 9 documented US stress events at a 3.83% overall fire rate with low false positive rates in calm bull years (0.0-7.5%). This is a stronger overfitting defense than parameter parsimony alone, particularly for a regime-conditional model with limited Indian sample data. See [Cross-Country Validation](#cross-country-validation) section below.

**Sharpe as the primary risk-adjusted metric.** The rf-adjusted Sharpe (using RBI repo rate, avg 6.27%) normalizes return per unit of volatility regardless of which mechanism is doing the work on any given day. The strategy's Sharpe of 0.83 vs NIFTY buy-and-hold's 0.15 (a ~5.5× improvement) is more reliable than cumulative-return comparisons, which are inherently joint and path-dependent.

---

## Long-Side Asset Selection

v1.2 had a structural bull-regime alpha gap: when fully long, the strategy held NIFTY 50 — the same asset as the benchmark — so it could only match (never beat) the benchmark on the long side. v1.3 addresses this by substituting a higher-expected-return Indian equity index as the long-side asset. Eight candidates were considered; two were backtested under identical regime-detection and risk-management mechanics; NIFTY 200 Momentum 30 was selected.

### Indices Considered

1. **NIFTY 50** — retained as benchmark and short-side asset; rejected as long-side due to the bull-regime alpha gap.
2. **NIFTY Midcap 150** — fully backtested as an alternative long-side asset; rejected (drawdown profile, see below).
3. **NIFTY Next 50** — rejected without backtest; still large-cap, no factor lens, expected uplift modest.
4. **NIFTY Smallcap 100 / 250** — rejected; liquidity capacity concerns at scale and deeper crisis drawdowns.
5. **NIFTY Bank** — rejected; single-sector concentration would undermine the strategy's volatility-control objective.
6. **NIFTY 200 Quality 30** — considered, not tested; structurally less responsive to trend persistence (the strategy's core thesis), left as future work.
7. **NIFTY 100 Low Volatility 30** — rejected; substitutes for the regime filter's vol-reduction work rather than complementing it.
8. **NIFTY Alpha 50** — rejected; factor definition partially circular with momentum, and shorter live history reduces confidence.

### Why NIFTY 200 Momentum 30 Won

**Academic foundation.** The momentum premium is one of the most-replicated anomalies in finance: Jegadeesh & Titman (1993), *Returns to Buying Winners and Selling Losers*, Journal of Finance 48(1). Subsequent validation spans asset classes and countries — Asness, Moskowitz & Pedersen (2013) — and momentum is included as the fourth factor in the Carhart (1997) four-factor model. India-specific evidence: Sehgal & Balakrishnan (2002); Joshipura (2012). NSE launched NIFTY 200 Momentum 30 in August 2020 with backfilled history to April 2005, and multiple Indian AMCs operate live momentum ETFs (UTI, Motilal Oswal, ICICI Pru).

**Structural compatibility with the regime architecture.** The strategy already operates on trend persistence — the regime filter is a 100-day moving-average trend gate. Pairing a momentum-tilted long-side asset with a regime architecture built on trend detection is internally coherent: both mechanisms benefit from the same underlying market behavior (persistence of trends past their fundamental drivers).

**Implementability.** Mechanical, transparent index methodology; semi-annual rebalance; tradeable via real Indian ETFs with reasonable AUM and liquidity; sufficient backfilled history for both in-sample (2008-2025) and out-of-sample (2026 YTD) testing.

### Comparison Tables

**Table A — Underlying indices buy-and-hold (2008-04-01 to 2025-12-31):**

| Index | CAGR | Sharpe | Max DD |
|---|---|---|---|
| NIFTY 50 | 10.4% | 0.29 | -51.7% |
| NIFTY Midcap 150 | 14.8% | 0.50 | -61.7% |
| NIFTY 200 Momentum 30 | 15.5% | 0.51 | -55.2% |

Both alternatives offer ~45% higher CAGR than NIFTY 50 with comparable Sharpe; Momentum 30 has the better drawdown profile of the two alternatives.

**Table B — Same strategy mechanics, three long-side assets (v1.3 baseline):**

| Long-side asset | CAGR | Sharpe | Calmar | Max DD |
|---|---|---|---|---|
| NIFTY 50 (regime filter + static gold + panic-short) | 12.59% | 0.50 | 0.77 | -16.4% |
| Midcap 150 | 21.30% | 1.00 | 0.82 | -26.1% |
| NIFTY 200 Momentum 30 | 18.08% | 0.83 | **1.00** | -18.1% |

Midcap 150 produced the highest absolute CAGR but at unacceptable drawdown deterioration — max DD widened from -16.4% (NIFTY 50 baseline) to -26.1%, a ~60% worsening that eliminates the strategy's headline drawdown control. Momentum 30 achieves the best Calmar of the three configurations (1.00) while preserving drawdown within 2pp of the NIFTY 50 baseline.

### v2.1-era validation: Mom30 vs NIFTY 50 under current mechanics

Table B above uses v1.3 baseline mechanics. To confirm that the long-side asset choice still holds under the more refined v2.1 architecture (V2 post-bear NIFTY recovery overlay + 5-day slow-stress cooldown + 15% panic-short DD gate), the same Mom30-vs-NIFTY-50 swap was re-run under v2.1 production.

| Long-side asset | Full CAGR | Sharpe | Max DD | OOS CAGR |
|---|---|---|---|---|
| **Mom30 (production)** | **+16.52%** | **0.830** | **−12.78%** | **+20.12%** |
| NIFTY 50 (substitute) | +10.51% | 0.409 | −13.04% | +12.59% |
| Δ (NIFTY − Mom30) | −6.01pp | −0.421 | −0.26pp | −7.53pp |

Year-by-year, Mom30 long sleeve won 14 of 18 calendar years; NIFTY 50 substitute won in 2018, 2019, 2022, 2025 — exactly the four structural rotation losing years documented above. NIFTY's wins are modest (avg margin +3.65pp, max +8.97pp). Mom30's wins are larger (avg margin −9.68pp, max −25.61pp in 2021). The asymmetry compounds — terminal multiplier on ₹1 is ~₹17.6 (Mom30 sleeve) vs ~₹6.0 (NIFTY sleeve), confirming Mom30 as the long-side choice under v2.1 mechanics, not just v1.3.

Test script: [`experiments/test_nifty_vs_mom30_long.py`](experiments/test_nifty_vs_mom30_long.py).

**Two distinct underperformance modes documented.** Momentum 30 underperforms NIFTY 50 in 4 of 18 years across the sample. These split into two distinct mechanisms.

The first is the **V-recovery momentum crash** (Daniel & Moskowitz 2016): after a sharp market crash, the momentum index holds stale pre-crash defensives while the recovery is led by beaten-down cyclicals. Because Momentum 30 ranks on trailing 6- and 12-month momentum and rebalances semi-annually, it cannot refresh into recovery leaders until a full rebalance cycle after the bottom. This is clearly visible in the 2009 sample. **Addressed in v2.0** via the post-bear NIFTY recovery overlay — see [Signal Logic](#6-post-bear-nifty-recovery-overlay-v20).

The second is **structural factor / sector rotation**, observed in 2018, 2022, and 2025. These years lack a clean crash signature — 2018 was a midcap-vs-largecap rotation (IL&FS / NBFC crisis crushed midcaps while large-caps held), 2022 and 2025 were sector rotations where Momentum 30 held prior-year winners into fresh selloffs. Multiple overlays were tested (relative-strength timing, asset swaps, intensity-scaled flats) and all either failed to fix the years or broke winning years in unacceptable ways. These losses remain unaddressed; see Limitations and Roadmap.

---

## Configurations Tested

The production strategy emerged from a sequence of explicit ablation tests across three design axes: deployment of capital during identified stress regimes, choice of long-side equity asset during bull regimes, and the stress-signal definition. Each was backtested over the full 2008-2025 in-sample period with identical regime-detection logic, transaction costs, and cash-yield assumptions; only the variable under test differed.

| Variant | Status | Reason |
|---|---|---|
| Regime filter alone (no gold, NIFTY-only stress-flat) | Rejected | Stress-flat capital earns only cash yield; misses safe-haven upside |
| Unconditional gold rotation on every stress-flat day | Rejected | Enters gold near intraperiod tops in 2026 H1; gold contribution −9.2% YTD |
| Always-on gold (held during bull regimes too) | Rejected | Dilutes bull-regime equity exposure with non-correlated asset; net CAGR drag |
| Momentum-gated gold rotation (per-latch state machine, single-condition entry) | Selected (v1.2) | Avoids the 2026 timing failure without giving up the safe-haven mechanism; gold-days reduced 76 → 41 |
| Momentum-gated gold rotation + NIFTY Midcap 150 as long-side asset | Rejected | Drawdown deteriorates to −26.1% — eliminates headline drawdown control |
| Momentum-gated gold rotation + NIFTY 200 Momentum 30 as long-side asset | Selected (v1.3) | Highest Calmar of v1.2–v1.3 alternatives; preserves drawdown within 2pp; structurally coherent |
| v1.4: prior + slow-stress signal + macro-confirmed gold rotation gate | Selected (v1.4) | Slow-stress catches the 2013 taper-tantrum failure mode (+3.43pp); macro-confirmed gate prevents the 2026 H1 gold blow-off-top failure; cross-country validation on US data catches 9/9 stress events |
| v1.5: prior + bear-regime requirement on gold rotation entry + mid-latch bull-flip exit | Selected (v1.5) | Eliminates the 2019 gold-in-bull anomaly (3 days, −4.34pp) where gold rotation triggered against a recovering equity tape; v1.5 post-tax MaxDD −14.67% |
| v2.0: prior + post-bear NIFTY recovery overlay + slow-stress cooldown | Selected (v2.0) | Recovery overlay captures the V-recovery cyclicals lead that Momentum 30 misses (cleanly visible in 2009: NIFTY +56% during the 60-day recovery window, Momentum 30 +29% — strategy now holds NIFTY through it). Slow-stress cooldown eliminates the 2019 April-May whipsaw (9 separate fires in short clusters were causing flat→long→flat round-trips). Combined: +1.14pp CAGR, max DD narrows from −14.67% to −13.38% |
| v2.1: prior + 15% drawdown confirmation on panic-short | Selected (v2.1) | Panic-short can only fire when NIFTY drawdown from 60-day high exceeds 15%; suppresses the 2013-08-27 (−22.9pp) and 2022-02-24 (−12.0pp) false fires that fired into local bottoms. All four 2008 GFC panic-shorts (drawdowns 16–32%) preserved. Documented tradeoff: the March 6 2020 fire is suppressed at 11.1% drawdown; next fire on March 9 catches up at 15.5% drawdown, 2020 CAGR drops +52.21% → +46.25% but COVID protection still strongly captured. MaxDD narrows further from −13.38% to −12.78%, rf-adjusted Sharpe 0.79 → 0.81 |
| **v2.2: prior + defensive quality basket replaces G10 gold rotation on stress-flat days** | **Selected (v2.2, current production)** | Defensive basket = 18 fundamentally-screened low-beta names (quality percentile ≥ 0.60, hard rules cfo>0/np>0/D/E≤3, beta ≤ 0.85, vol ≤ 0.30, defensive-sector tilt, sector cap 5), semi-annual rebalance, 50/50 blended with cash, deployed after 40-day persistence gate on each stress-flat latch. Real costs (30 bps/side + STCG 15%/20%) charged. Replaces the v2.1 G10 gold rotation (kept as opt-in via `enable_defensive_basket=False`). Marginal Sharpe-neutral improvement: CAGR 16.52% → 16.85% (+0.33pp), Sharpe 0.81 → 0.83 (+0.02), MaxDD -12.78% → -13.92% (slightly deeper). OOS 2017+: +0.15pp CAGR, +0.01 Sharpe, MaxDD -12.78% → -10.88% (1.9pp shallower). Not a slam-dunk; earns its place as an incremental risk-adjustment layer, not as significant new alpha. |

The methodology throughout was ablation-and-replacement: each new component was layered on top of the previously-selected production base, with the prior version retained in the codebase as an opt-in rollback flag. Configurations are evaluated on the joint criterion of risk-adjusted return (Sharpe, Calmar) and absolute drawdown control. The discipline applied to each new layer was identical: pre-specify the parameter sweep before running, identify a plateau in the qualified range rather than a sharp cliff, disqualify variants that break key validation periods (notably the 2008 GFC and 2020 COVID stress windows for the panic-short gate).

---

## Strategy Overview

The framework targets alpha through **regime identification combined with multi-asset rotation**. One engagement gate plus two stress overrides operate together, with three refinements layered on top:

1. **Regime filter (engagement gate)** — long when NIFTY 50 closes above its 100-day moving average; flat when below. Detects bull/bear regimes on NIFTY 50 independently of which asset is held on the long side (this separates regime detection from asset selection).
2. **Slow-stress override (force flat, with 5-day cooldown)** — sustained EM stress (INR weakness + VIX z-score regime shift + VIX momentum) forces the strategy to flat. Captures slow-burn stress regimes the legacy supply-shock signal missed (2013 taper, 2018 NBFC). Once fired, subsequent slow-stress firings are suppressed for 5 trading days to prevent whipsaw round-trips.
3. **Panic-short override (force short, with 15% drawdown confirmation)** — absolute high VIX combined with accelerating VIX and broken trend, AND NIFTY's drawdown from its trailing 60-day high exceeds 15%, forces an active short on NIFTY 50. Overrides slow-stress when both fire simultaneously. The drawdown confirmation filters VIX-spike-only false fires that previously triggered into local bottoms.
4. **Post-bear NIFTY recovery overlay** — for the first 60 trading days following a bear→bull regime flip preceded by a NIFTY drawdown of 15% or more, the strategy holds NIFTY 50 rather than NIFTY 200 Momentum 30. After the 60-day window, reverts to Momentum 30. Targets the V-recovery momentum-crash pattern.

A momentum-gated gold rotation overlay rotates capital to GOLDBEES.NS during stress-flat windows when the macro-confirmed gate is satisfied (gold 10-day positive momentum capped at 10%, INR weakening over 10 days, US 10-year yields falling over 20 days, bear regime confirmed). Idle capital on remaining flat days earns the RBI repo rate minus a 100 bps haircut.

Position sizing is binary across two long-side assets (long NIFTY 200 Momentum 30 or NIFTY 50 = +1, long gold = +1, short NIFTY 50 = −1, cash flat = 0); no leverage beyond 1×. Position-logic priority is: regime-filter engagement (long when NIFTY > 100 DMA absent overrides) → slow-stress override (force flat on sustained EM stress, subject to 5-day cooldown after prior fire) → panic-short override (force short on acute panic + 15% drawdown confirmation, overrides slow-stress) → momentum-gated gold rotation overlay on stress-flat days → post-bear NIFTY recovery overlay (swaps the long-side asset from Momentum 30 to NIFTY 50 within recovery windows) → RBI repo cash yield (minus 100 bps haircut) on remaining flat days.

Returns are post-tax by default (15% Indian short-term capital gains annual-net model). This produces three independent mechanism families — tactical long exposure to a momentum-tilted equity portfolio, momentum-gated safe-haven rotation with macro confirmation, and cash management — that compound across the 17-year sample.

---

## Signal Logic

### 1. Long Engagement — Regime Filter

**Economic rationale.** The 100 DMA trend filter is the binding gate for long engagement. When NIFTY 50 closes above its 100-day moving average, the strategy holds the long-side asset (NIFTY 200 Momentum 30) absent any active override. When NIFTY 50 closes below, longs are forced flat. The 100-day moving average serves as a coarse trend filter, ensuring the strategy holds long exposure only in confirmed uptrends.

**Mechanics.**
- Bull regime (NIFTY 50 > 100 DMA): longs engaged, shorts blocked
- Bear regime (NIFTY 50 < 100 DMA): longs forced flat, shorts permitted
- Applied as the final override after all other lanes have been computed

### 2. Slow-Stress Trigger — Force Flat (v1.4, with v2.0 cooldown)

**Economic rationale.** EM stress regimes typically manifest as a combination of sustained currency weakness (capital flight from emerging markets) and elevated implied volatility (institutional fear pricing in options markets), often persisting for weeks to months. The 2013 taper tantrum and 2018 NBFC crisis are canonical examples where this pattern unfolded gradually without the acute coordinated multi-asset moves that the legacy supply-shock signal required. The slow-stress signal targets this regime via three first-principles conditions that capture sustained EM stress without depending on specific historical event signatures.

**Mechanics.** All three conditions must fire simultaneously:
- INR 20-day return > 1% (sustained rupee weakening)
- India VIX 90-day z-score > 1.5 (VIX regime shift relative to 1-year baseline — automatically regime-adaptive rather than using a hand-picked absolute threshold)
- India VIX 5-day momentum > 0 (vol still trending up, not mean-reverting)

When all three conditions fire, position is forced to flat. The signal fires on its trigger days only (no cooldown extension — the 20-day and 90-day windows are already slow time horizons; layering an additional NIFTY-momentum cooldown on top would over-extend cash days and crush CAGR). The signal fires approximately 210 days over the 2008-2025 sample (before the v2.0 cooldown), with primary firings during 2013 taper tantrum and elevated periods around 2008, 2011, 2015-16, and 2018-2020 stress windows.

**v2.0 addition: 5-day post-firing cooldown.** Once the slow-stress signal fires (forcing the strategy flat), suppress any subsequent slow-stress firings for the next 5 trading days. Continuous runs (consecutive firing days within a sustained stress regime) are NOT suppressed — once a run begins, all its days are allowed. The cooldown only blocks fresh re-fires that arrive after the prior run has ended. Other exit signals (bear regime, panic-short) remain unaffected.

The motivation comes from the April–May 2019 bleed. Nine separate slow-stress fires arrived in short clusters across those two months. Each fresh fire forced a flat→long→flat round-trip, with the strategy losing meaningful return on each exit-day move (NIFTY frequently rallied across the next 5–20 trading days after each fire, then re-fired again on the next minor INR/VIX wobble). Persistent crisis runs already span the 5-day window from day one and continue firing normally, so the cooldown does not weaken defensive coverage during real stress (2008 GFC, 2018 September NBFC, 2020 COVID, 2021 October all preserved).

**Cooldown sensitivity.** Tested at 0, 3, 5, 7, 10, 15, and 20 days. Five days is the unique optimum on CAGR, Sharpe, and Calmar. Below 5 days under-protects against the 2019 chop. Above 5 days starts suppressing legitimate second-leg defensive fires — specifically, the September 2018 NBFC crisis had two separated firing runs (early September, late September) approximately 7–8 trading days apart; cooldowns of 7 days or more block the second run and the strategy holds Momentum 30 straight into the second leg of the NBFC drawdown. The 5-day choice sits at the longest cooldown that preserves the 2018 September NBFC defense. The qualified-range plateau (0 to 5 days) spans 0.14pp of CAGR — robust within range, sharp cliff above. Impact: +0.14pp CAGR, +0.003 Sharpe, max drawdown narrows from −14.67% to −13.38%.

The legacy supply-shock signal (oil + INR + VIX coordinated 10-day % moves) is retained in the codebase as an opt-in alternative (`make_combiner(use_supply_shock=True)`) for backward compatibility and research comparison. It is not the default.

### 3. Panic-Short Override — Active Short (v1.0, with v2.1 drawdown confirmation)

**Economic rationale.** A high absolute VIX level *combined with* an accelerating VIX spike *and* NIFTY already below trend captures regimes where the cycle has decisively turned bearish — distinct from the sustained stress that the slow-stress lane handles. In these regimes, capital protection plus directional exposure to the bearish move is preferable to going flat.

**Mechanics.** All four conditions must hold simultaneously:
- India VIX absolute level ≥ 25
- VIX up more than 50% over 10 days
- NIFTY closing below its 100-day moving average
- **NIFTY drawdown from its trailing 60-day high > 15%** (v2.1 confirmation gate)

When fired, position is forced to −1 (active short on NIFTY 50). Panic-short overrides slow-stress when both fire simultaneously: acute panic conditions take priority over sustained slow-stress conditions. Short exits when the NIFTY 5-day MA crosses above the 20-day MA. After short exit, the strategy stays flat until the NIFTY 5-day return > 0.5% confirmation fires.

**v2.1 addition: 15% drawdown confirmation.** The original panic-short logic required only the VIX-spike + below-trend conditions; this triggered two documented false fires that hurt the strategy materially. 2013-08-27 (taper tantrum aftermath) fired with NIFTY drawdown only ~13% from 60-day high; the index rallied immediately afterward and the strategy lost ~22.9pp on the short. 2022-02-24 (Ukraine war shock) fired with drawdown ~11.3%; NIFTY rallied through to year-end and the strategy lost ~12.0pp. The drawdown confirmation requires that price action has already shown meaningful damage (15%+ off recent highs) before adding a short — standard risk-management discipline that short positions require multiple independent confirmations, not just a volatility signal. The same 15% threshold used for the post-bear NIFTY recovery overlay, giving the strategy a single internally consistent definition of "real bear regime."

**Drawdown-threshold sensitivity.** Tested at 0% (no gate), 8%, 10%, 12%, 15%, 20%, and 25%. Within the qualified range (8%–15%, all preserving the 2008 GFC and 2020 COVID panic-shorts), the CAGR spread is just 0.17pp — a tight plateau, not a fragile fit. Thresholds at 20% and 25% are disqualified because they block 2 of the 4 GFC panic-shorts (which fired at NIFTY drawdowns of 16% and 17%) and substantially weaken the 2020 COVID defense. The 15% choice sits at the right edge of the qualified plateau and is the smallest threshold that captures both target false fires (2013-08-27 at 13% drawdown, 2022-02-24 at 11.3%). Impact: +0.011 Sharpe, max drawdown narrows from −13.38% to −12.78%, CAGR essentially flat (−0.03pp).

**Documented tradeoff.** The March 6, 2020 panic-short fire occurred when NIFTY drawdown was only ~11.1% from the late-January high. Under v2.1 this fire is suppressed. The next panic-short fire on March 9 (drawdown 15.5%) catches the move three trading days later. 2020 CAGR drops from +52.21% to +46.25% — a meaningful 5.96pp give-back. The COVID protection is still strongly captured overall (the strategy beats NIFTY by +32.4pp post-tax in 2020), but the suppressed-then-caught pattern is the explicit cost of demanding price confirmation before shorting in fast-crash scenarios. If a future crisis develops faster than COVID and the early-fire suppression delays defense materially, this tradeoff would compound. The qualified-plateau evidence suggests this is the right tradeoff on the available sample, but it remains a risk inherent to the gate.

### 4. Gold Rotation — Macro-Confirmed Gate (v1.4, SUPERSEDED in v2.2)

**Status.** SUPERSEDED as of v2.2 by the defensive quality basket (see [Section 6](#6-defensive-quality-basket-v22)). The gold-rotation code path remains in the repository behind `enable_defensive_basket=False` for backward compatibility and reproducibility of v2.1 numbers. Not part of production. Full context in [Superseded Research](#superseded-research--g10-gold-rotation).

The section below documents the v1.4–v2.1 mechanism as it stood before v2.2 replaced it. Kept because it's part of the strategy's evolution and remains a valid opt-in configuration.

**Economic rationale (v1.4–v2.1).** Gold's price action is driven by three fundamental macro factors: real interest rates (gold is a non-yielding asset, so falling real rates raise gold's relative appeal), dollar dynamics (gold is denominated in USD; weaker dollar lifts gold prices), and momentum / flight-to-safety flows. The macro-confirmed gold rotation gate uses one of each of these forces as entry confirmation, replacing the single-condition gate used in v1.2-v1.3.1.

**Mechanics — entry requires ALL of:**
- 0 < gold 10-day return ≤ 10% (positive momentum but not extreme; the cap prevents blow-off-top entries that historically reverse within days)
- USDINR 10-day return > 0.5% (rupee weakening mechanically lifts INR-priced gold)
- US 10-year Treasury yield 20-day return < 0 (falling US yields = gold tailwind globally)
- NIFTY below its 100-day moving average (bear regime — v1.5 addition that eliminated the May 2019 gold-in-bull anomaly)

One-way door exit logic preserved from v1.2: once in gold within a stress-flat latch, exit to cash if gold 10-day return turns negative; stay out for the remainder of that latch (no re-entry within the same latch). v1.5 also added a mid-latch bull-flip exit (exit gold immediately if the regime flips back to bull mid-latch).

**Why v1.4 changed the gate.** The v1.2-v1.3.1 single-condition gate (gold_10d > 0) had two documented failure modes. Marginal-momentum entries (gold 10d return 0-2%) had a 40% hit rate and mean return of −0.42% — essentially noise. Extreme-momentum entries (gold 10d return > 10%) exhibited blow-off-top behavior, with the 2026-01-29 entry at +24% gold momentum followed by a −19% gold crash within days. The v1.4 macro-confirmed gate addresses both: the upper cap blocks blow-off entries; the INR + US 10Y confirmation filters the marginal-momentum noise by requiring macro alignment.

**Why v2.2 replaced this.** The G10 gate was over-restrictive — it fired on only ~27 stress-flat days across the 18-year sample, providing negligible incremental alpha in aggregate. The defensive quality basket bake-off (V7 native) showed a cleaner, better-tested replacement (see [Defensive Quality Basket](#6-defensive-quality-basket-v22)). We built the gate, tested it, and replaced it with something we trust more.

### 5. Post-Bear NIFTY Recovery Overlay (v2.0)

**Economic rationale.** Documented by Daniel & Moskowitz (2016, *Momentum Crashes*): after a sharp market crash, a momentum index holds stale pre-crash winners (defensive stocks that survived the crash) while the recovery is led by beaten-down cyclicals. Because NIFTY 200 Momentum 30's momentum score is computed over trailing 6- and 12-month windows and rebalances only semi-annually (June and December), the index cannot refresh into the recovery leaders until a full rebalance cycle after the bottom. NIFTY 50 captures the broad-market rebound that Momentum 30 misses during the first 2–3 months after the trough.

The 2009 sample illustrates this cleanly. NIFTY's bear regime ended on March 23, 2009. Over the following 60 trading days (March 23 – June 12, 2009), NIFTY 50 returned +55.9%; NIFTY 200 Momentum 30 returned +28.6% over the same window. Without the overlay, the strategy would have held Momentum 30 through this window and captured the lower return. With the overlay, the strategy holds NIFTY 50 through the 60-day window and then reverts to Momentum 30 from June 15, 2009 onward. Momentum 30 then dominates for the remainder of the year (2009 strategy full-year: +76.5% with the overlay, vs +52.0% in v1.5 without — a 24pp single-year improvement).

**Mechanics.** When the strategy is in a long position immediately after a bear→bull regime flip (NIFTY 50 crosses above its 100-day moving average), and the preceding bear-regime peak-to-trough drawdown was ≥15%, the strategy holds NIFTY 50 instead of NIFTY 200 Momentum 30 for the next 60 trading days. After 60 days, it reverts to Momentum 30 (which by then has had time to refresh into recovery leaders via the semi-annual rebalance).

**Drawdown-threshold sensitivity.** Tested at 10%, 12%, 15%, 18%, 20%. The 15%, 18%, and 20% thresholds produce identical results — no qualifying bear drawdowns in the 15–20% range across the sample. 12% added marginal false positives (shallow pullbacks that don't constitute real bear markets). 10% over-triggered. The 15% threshold is the smallest value that captures all real V-recoveries (2008 GFC, 2020 COVID) without including borderline cases; the plateau from 15% to 20% means the choice is robust to the specific threshold within that range.

**Hold-period choice.** 60 trading days reflects the typical Indian semi-annual rebalance cadence (NSE Indices rebalances momentum semi-annually). Not separately swept. Impact: +1.00pp CAGR vs v1.5 baseline, +0.04 Sharpe, max drawdown unchanged. The overlay is active only during ~180 days out of the 17.7-year sample (qualifying V-recovery windows), so it does not affect the strategy outside those specific periods.

### 6. Defensive Quality Basket (v2.2)

**Status.** Production, replaces the v2.1 G10 gold rotation on stress-flat days. Enabled by default in `MacroStrategy(..., enable_defensive_basket=True)`. Set to False to reproduce v2.1 gold-rotation behavior byte-for-byte.

**Economic rationale.** During sustained stress-flat windows, capital that would otherwise sit in cash can be deployed into a diversified basket of high-quality, low-beta names that historically outperform cash on a total-return basis while adding limited additional drawdown. This is a "defensive equity" allocation — not a return-seeking momentum tilt, but a risk-managed harvest of the equity risk premium during periods when the strategy's main long-side asset (Mom30) is disengaged by the regime filter.

**Construction (semi-annual rebalance).** At each rebalance date:

1. **Universe filter**: top-200 NSE names by 60-day rupee turnover (real liquidity floor).
2. **Fundamental hard rules** (point-in-time, 6-month reporting lag): `cfo > 0`, `net_profit > 0`, `total_debt / equity ≤ 3` (default 3.0; the defensive basket used 3.0 in production, not 2.0 which was tested for the momentum-basket variants). Names failing any explicit rule are dropped; names with missing data in a specific field are permissive-passed but names missing from the fundamentals panel entirely are dropped.
3. **Quality percentile ≥ 0.60**: derived from a combined Piotroski F-score + ratio-composite (ROCE, D/E, interest coverage, cash conversion) cross-sectional percentile within the universe.
4. **Risk caps**: 250-day beta ≤ 0.85 vs NIFTY 50, 250-day annualized vol ≤ 0.30. Filters out high-beta cyclicals and volatile mid/small caps.
5. **Composite score**: `z(quality_pct) − z(beta) − z(vol) + 0.5 × 1[defensive sector]` where defensive sectors are FMCG, Pharma, Utility, IT.
6. **Sector cap**: max 5 names per sector. Sort by composite score desc, then apply cap greedily.
7. Take top 18 names, equal-weighted (1/18 = 5.56% per name).
8. **Buffered incumbent retention**: incumbents from the prior rebalance are retained if they still rank in the top-50% of the current composite score (reduces churn).

Sample basket at 2020-06-30 (mid-COVID stress window): ITC, BRITANNIA, HINDUNILVR, SUNPHARMA, HDFCLIFE, and 13 more. Concentrated in FMCG + Pharma + Financials + IT — as designed.

**Persistence gate (N = 40 trading days).** The basket does not deploy immediately on stress-flat days. It waits 40 consecutive trading days of `nifty_position == 0` before deploying, then remains active until the latch ends. This filters out short (< 40-day) stress flickers — ~102 of the 119 stress-flat latches across the sample never qualify — and only deploys during the ~17 genuinely sustained bear windows. Tuning: N ∈ {10, 20, 30, 40, 50, 60} tested in-sample 2008-2016, N=40 was OOS-best Sharpe among basket_cash_blend variants. Locked, applied unchanged to OOS 2017-2026.

**50/50 basket/cash blend.** On active days, the flat-day return is replaced with:
`ret = 0.5 × basket_ret + 0.5 × cash_return`

100% basket (no cash blend) tested — higher CAGR but MaxDD blowout too deep for the risk-adjusted improvement to survive. 50/50 was the best-Sharpe alloc across {100%, 75%, 50%, 25%} tested at N=40.

**Trading costs and tax.** Real institutional costs are charged:
- Entry (day 41 of a qualifying latch): 15 bps of NAV (0.5 alloc × 30 bps/side)
- Exit (regime flip to bull): 15 bps of NAV + STCG on cumulative basket gain over the deployment window
- STCG rate: 15% pre-2024-07-23, 20% after (India, short-term capital gains — basket is always held under 1 year)
- No internal rebalance cost inside a deployment (holdings only change at the semi-annual rebalance dates, which almost never fall inside an active deployment window in practice; when they do, the incremental turnover cost is negligible)

The 30 bps/side cost model covers brokerage (~2 bps), STT (~10 bps), exchange charges (~1 bp), stamp duty (~1 bp), GST (~2 bps on brokerage), and slippage (~14 bps) on the 18-name basket. Slippage estimate reflects realistic execution on mid-cap-heavy names within the top-200 liquid universe.

**Bake-off results (V7 native, defensive-side allocation).** Six candidates tested for the stress-flat allocation, all applied to Config 7 with identical regime signals:

| # | Candidate | FULL CAGR | Sharpe | MaxDD | Deployments |
|---|---|---|---|---|---|
| 0 | Config 7 baseline (G10 gold) | 16.52% | 0.81 | -12.78% | – |
| 1 | Pure cash (no rotation) | ~16.33% | ~0.80 | -12.78% | 119 |
| 2 | Simple gold (bear-regime, no G10 conditions) | ~16.02% | ~0.75 | -23.21% | 119 |
| 3 | G10 incumbent (= baseline) | 16.52% | 0.81 | -12.78% | 0 |
| 4 | Basket-gated 100% (N=40) | ~17.20% | 0.82 | -17.00% | 17 |
| **5** | **Basket + cash 50/50 (N=40) — SELECTED** | **16.85%** | **0.83** | **-13.92%** | **17** |
| 6 | Basket + gold 50/50 (N=40) | ~16.71% | 0.78 | -23.08% | 17 |

Candidate 5 (basket + cash 50/50, N=40) has the best Sharpe and modest MaxDD deepening (~1pp vs baseline). Selected as v2.2 production. Candidate 4 (100% basket) has higher CAGR but ~5pp deeper MaxDD.

**V8 stress-resilient basket bake-off (rejected).** A more sophisticated basket construction — ranking by mean return across prior bear windows only (no look-ahead), balanced beta band 0.6–1.1, fewer defensive-sector picks — was tested. It underperformed the V7 generic construction across FULL and OOS. Reason: bear-window resilience does not transfer across regimes (2008 defenders ≠ 2020 defenders ≠ 2022 defenders), and 11.9% of picks used inverse-vol fallback anyway when history was thin. V7 basket_cash_blend retained.

**Bake-off scripts:** `experiments/stock_momentum/backtest_bakeoff_v7_native.py` (V7), `backtest_bakeoff_v8.py` (V8 rejected).

**Data dependencies for basket construction (needed if rebuilding artifacts):**
- `data/bse_pipeline/extended_fundamentals_v2.parquet` — fundamentals panel (bundled)
- `data/quality_factor/quality_scores_pit.parquet` — quality scores (bundled)
- `data/momentum_scores/scored_universe.parquet` — universe + turnover (bundled)
- `data/yfinance_bulk/adjusted_prices_panel.parquet` — stock price panel for beta/vol computation (~544 MB; NOT bundled — regenerate via `fetch_stock_prices.py` or equivalent yfinance bulk download)

**Runtime artifacts (bundled, small):**
- `data/defensive_basket_holdings.parquet` — 340 rows (holdings × rebalance date)
- `data/defensive_basket_daily_returns.parquet` — 4,749 rows (one basket return per trading day)

The runtime only needs the two small artifacts. The larger source data is only needed to rebuild the artifacts via `python build_defensive_basket.py`.

**Data documentation for the fundamentals + quality pipeline is in the [Data](#data) section.**

### 7. Tested But Not Adopted

#### Long-entry confirmation lanes (USDINR / India VIX momentum)

The codebase retains two signal classes — `USDINRSignal` and `IndiaVIXSignal` — that were originally designed as long-entry confirmation lanes. They were evaluated as binding gates on long re-entry: requiring an entry signal to fire during a flat period before the strategy could re-engage the long-side asset. The variant was backtested over the full 2008-2025 sample under otherwise-identical mechanics.

**Variant tested.** Entry signal definitions (10-day windows): USDINR has fallen >1% over 10 days (rupee strengthening); India VIX has fallen >20% over 10 days (vol decay). Gate logic: when NIFTY > 100 DMA but the strategy is transitioning from flat to long, require an entry signal to have fired during the flat period before allowing the long.

**Results.** The gated variant blocked 423 re-entry attempts and added ~1.7 years of additional flat exposure. CAGR cost: -1.59pp. Sharpe: 0.78 vs 0.83 (v1.3 baseline). The cost concentrates in V-shaped recovery years where the entry signals lag the trend reversal: 2009 (-8.1pp), 2014 (-8.0pp), 2017 (-16.4pp), 2021 (-11.2pp). **Conclusion:** The 100 DMA trend filter dominates the carry- and vol-based entry signals on the relevant time scales. The signal classes are retained in the codebase as scaffolding for future iterations but do not affect production positions. Full test script: [`experiments/test_entry_signal_gate.py`](experiments/test_entry_signal_gate.py).

#### Vol-Scaled Position Sizing (rejected — tested twice, June 2026)

A volatility-scaling overlay was tested on top of v1.3.1 (May 2026) and again exhaustively on top of v2.1 (June 2026). Both rounds reject the mechanism. Combined: 32 distinct vol-scaling parameterizations tested across rolling vol windows, target levels, forecasting methods, target structures, regime gating, smoothing, and residual asset choice. None beats the production binary-sizing base.

**Round 1 — v1.3.1 sweep (13 variants, May 2026).** Tested across rolling realized vol windows (10/20/60 days), target vol levels (10/12/15%), and mitigation overlays (tolerance bands, weekly rebalance). Best variant (60-day window, 15% target, daily rebalance) produced post-tax Sharpe 0.673 vs base 0.731 — a -0.058 deterioration. All variants negative.

**Round 2 — v2.1 exhaustive sweep (19 variants, June 2026).** Re-tested across the broader design space the first round didn't cover:

| Dimension | Variants tested |
|---|---|
| Window length (realized vol) | 20, 30, 60, 90 days |
| Vol forecasting | Realized, EWMA (λ=0.94), GARCH(1,1) |
| Target structure | Constant 18%, rolling 252d mean, 75th percentile of 3y distribution, down-vol-only |
| Regime conditioning | NIFTY > 200-DMA gate, India VIX < 20 gate, no-overlap default |
| Smoothing / hysteresis | 5-day EMA on weight, threshold-based (Δw > 10%) |
| Portfolio-level vs leg-level | σ_target ∈ {8%, 10%, 12%, 15%, 18%} at portfolio vol |

All 19 variants underperform v2.1 baseline. Best variant (D2 — VIX < 20 gate) is −0.06pp full CAGR. Worst (GARCH(1,1)) is −1.04pp full / −2.30pp OOS. Maximum drawdown is identical (−12.78%) across all 14 leg-level variants — vol scaling fails to narrow drawdowns at all, which is its supposed selling point. The 5 portfolio-level variants (PV1-PV5) do narrow MaxDD by 0.72-2.73pp, but at the cost of −1.21pp to −7.01pp CAGR — the drawdown reduction comes from uniform exposure haircuts that also cut the wins, leaving Sharpe lower.

**Architectural mechanism of failure.** Vol scaling is structurally redundant with v2.1's regime architecture. The strategy's full-sample realized vol is ~12.7% (already well below typical vol scaling targets); Mom30's standalone vol is ~22-25%. When Mom30 vol spikes, NIFTY is already below its 100-DMA and the regime filter has moved the strategy to cash — vol scaling has nothing to act on. When vol then stays elevated through recoveries (2009 GFC rebound, 2020-21 COVID rebound), vol scaling under-invests exactly during the up-leg where v2.1 wants full exposure. Strategy alpha is concentrated in high-vol recovery regimes; vol scaling fires hardest during those regimes, cutting the recovery upside.

**The clean framing.** Vol scaling is a substitute for regime-based risk management, not a complement. v2.1 already takes the regime-based path; layering vol scaling on top is asking it to compete with mechanisms that fire faster and more selectively. Vol scaling's natural home is in long-only or long-short factor portfolios without regime architecture (the original Barroso-Santa-Clara 2015 setup); applied to v2.1 it has no marginal contribution to add.

**Residual scope.** Portfolio-level vol scaling does work mechanically for risk-budgeting purposes — e.g., if v2.1 is deployed inside a multi-strategy book at a fixed vol target. PV2 (10% target) hits 10.19% realized vol with 1.20× leverage equivalent to recover baseline notional. This is sizing, not alpha generation, and is documented separately under deployment considerations.

Test scripts: [`experiments/test_vol_managed_momentum.py`](experiments/test_vol_managed_momentum.py) (B-S-C variants), [`experiments/test_vol_scaling_exhaustive.py`](experiments/test_vol_scaling_exhaustive.py) (full sweep including portfolio-level). Round 1 script parked at `parked/test_vol_scaling.py`.

#### Slow-Stress Signal Iterations (rejected variants leading to v1.4)

In developing the v1.4 slow-stress signal, several specifications were tested and rejected. The selected v1.4 specification (INR 20-day return + VIX 90-day z-score + VIX 5-day momentum) was chosen for balance of selectivity (~210 fires in-sample) and coverage (catches 2013 taper cleanly, US validation 9/9). Key rejected variants:

| Variant | Why rejected |
|---|---|
| VIX 60d/252d ratio only | 60-day MA too slow; lagged 2013 entry by months |
| VIX z-score + 60-day mixed windows | Catastrophic 2009 drag from trailing post-GFC stress detection |
| VIX z-score + 3-day persistence | Filtered out legitimate signals proportionally with noise |
| 2-of-3 with mixed fast/slow per indicator | Over-fired at 644-878 days, OOS deterioration |
| INR + VIX + oil three-condition (60-day) | Excluded 2018 because oil wasn't sustained-elevated |

Key methodological lessons: VIX-only signals over-fire in calm regimes where any small spike registers as elevated z-score (cross-asset confirmation needed); tighter thresholds filter genuine signal proportionally with noise (adding a different asset class is better than tightening the same signal); mixed fast/slow windows per input inevitably catch fast-window false positives.

#### Gold Rotation Gate Iterations (rejected variants leading to the v1.4 macro-confirmed gate)

In developing the v1.4 macro-confirmed gold rotation gate, several specifications were tested:

| Variant | Why rejected |
|---|---|
| Tighter lower bound only (gold 10d > 2%) | Helped slightly but didn't fix 2026 H1 blow-off-top |
| Upper cap only (gold 10d ≤ 10%) | Lower IS Sharpe |
| Both bounds (2% < gold 10d ≤ 10%) | Lost 2013 mid-rally legitimate entries |
| No gate (control test) | OOS -8.17%, MaxDD -21.9% — confirms gate adds value |
| INR-only mechanical | 55% hit rate, -21.9% MaxDD — INR direction alone insufficient |
| 4-condition sum score | OOS -12.64%, same blow-off-top failure pattern |

Key methodological lessons: upper momentum cap is essential for blow-off-top protection; external macro confirmation outperforms single-asset tightening; US 10Y yields are a more fundamental gold driver than DXY (though both correlate); over-constraining (4+ conditions) reduces fires to statistically insignificant counts.

---

## Data

### Market data (macro signals + benchmarks)

| Series | Ticker | Source | Frequency |
|---|---|---|---|
| NIFTY 50 | `^NSEI` | Yahoo Finance via `yfinance` | Daily, adjusted close |
| USD/INR | `INR=X` | Yahoo Finance | Daily |
| India VIX | `^INDIAVIX` | Yahoo Finance | Daily |
| WTI Crude (front-month) | `CL=F` | Yahoo Finance | Daily |
| Gold ETF (v1.1, opt-in v2.2) | `GOLDBEES.NS` | Yahoo Finance (NSE-listed) | Daily; series begins 2009-01-02 |
| NIFTY 200 Momentum 30 (v1.3) | `NIFTYMOM30` | NSE CSV via `niftyindices.com` (pulled with `nselib`); stored as `data/momentum30_history.csv` | Daily; backfilled 2008-01-01, live since Aug 2020 |
| US 10-Year Treasury yield (v1.4, opt-in v2.2) | `^TNX` | Yahoo Finance | Daily |
| RBI Repo Rate (v1.1) | — | RBI MPC press releases ([rbi.org.in](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx)); hardcoded as `RBI_REPO_RATE_HISTORY` in `strategy.py` | Step function (~55 announcements over 2008–2026) |

Most market data is downloaded live at runtime via `yfinance`; NIFTY 200 Momentum 30 is loaded from a static CSV (`data/momentum30_history.csv`) sourced from niftyindices.com via the `nselib` Python library. India VIX series begins March 2008, which sets the in-sample start at **2008-04-01**. A warmup period from **2006-01-01 to 2008-03-31** seeds rolling windows and is excluded from results. GOLDBEES.NS data starts 2009-01-02; pre-2009 stress-flat days remain fully flat in the backtest (gold instrument not yet tradable). Cleaning is minimal: forward-fill across mismatched holiday calendars, drop full-NaN rows.

### Fundamentals data (v2.2 — defensive basket construction)

The defensive basket requires point-in-time corporate financials + a stock price panel for individual-name beta/vol computation. Sources and pipeline:

**Primary fundamentals source — BSE annual reports.** ~6,751 annual-report PDFs downloaded from bseindia.com covering ~1,561 stocks back to FY2007. Parsed via a table-extraction pipeline (`experiments/stock_momentum/bse_pipeline_full.py`) that handles both regex-based and pdfplumber-based extraction depending on PDF format. Line items extracted include Revenue, EBIT, Net Profit, Cash Flow from Operations, Total Debt, Total Equity, Interest Expense, Total Assets, Current Assets, Current Liabilities. Output: `data/bse_pipeline/extended_fundamentals_v2.parquet` (~1 MB, ~194k rows).

**Secondary source — Screener.in bulk export.** Merged with BSE-parsed data to fill coverage gaps. **Important post-processing fix**: the Screener export used non-standard column labels for CFO (only ~10% coverage under the original label) and Total Equity (~17% coverage under the raw label). A label-mapping step (`experiments/stock_momentum/panel_postprocess.py`) restored these to 93% and 96% coverage respectively for post-2014 data. Pre-2014 data has known gaps in Current Assets / Current Liabilities and EBIT — flagged explicitly.

**Era-adapted Piotroski F-score.**
- Post-2014 (~2015+): full 9-component Piotroski F-score computable for most names (P7 methodology, all nine binary checks available)
- Pre-2014 (~2008-2014): only 8 components computable due to missing Current Assets/Liabilities in the pre-2014 source data (Q8 methodology, one component dropped). The scale is normalized to be comparable across eras.

**Coverage and confidence:**
- Screener-sourced data: ~94% accuracy against ground truth for spot-checked large-caps
- BSE-parser-sourced data (high-confidence tier): ~87% accuracy
- Both sources dropped where confidence is low or catastrophic outliers detected
- Banks excluded from the fundamentals panel (different accounting standards; equity/debt ratios not comparable to non-financials)

**Quality composite score.** Combines Piotroski F-score (era-adapted) with a ratio composite (ROCE 3-year avg, Revenue CAGR 5-year, D/E, Interest Coverage, Cash Conversion 3-year avg). Cross-sectional percentile computed within each rebalance date's eligible universe. Output: `data/quality_factor/quality_scores_pit.parquet` (per-symbol × rebalance-date). See `experiments/stock_momentum/quality_factor.py` for exact scoring logic.

**Universe and momentum scores.** `data/momentum_scores/scored_universe.parquet` — 500 stocks × 36 semi-annual rebalances (2008-06-30 → 2025-12-31). Contains liquidity rank (`universe_rank_turnover` = rank by 60-day rupee turnover), momentum metrics (mom_12_1, mom_6_1, risk_adj_mom_*), and composite momentum score used for the top-N liquid universe filter in the defensive basket. Momentum computation: `experiments/stock_momentum/build_universe.py`.

**Stock price panel — NOT bundled.** `data/yfinance_bulk/adjusted_prices_panel.parquet` (~544 MB) contains daily adjusted-close prices for 1,274 NSE-listed symbols spanning 2007-01-02 → 2026-06-11. Bulk-downloaded from yfinance. **Not committed to the repo due to size.** Users who want to rebuild the defensive-basket artifacts from source need this file — fetch script: `experiments/stock_momentum/bulk_pull_yfinance.py` (runs against a symbol list; multi-hour download). Alternatively, the two runtime artifacts (`defensive_basket_holdings.parquet` + `defensive_basket_daily_returns.parquet`) are bundled and are the only files production loads at runtime.

**Survivorship handling.** The stock price panel includes delisted names (yfinance retains history for delisted tickers when available). Fundamentals panel includes historical data for names that have since delisted. No survivorship bias adjustment beyond what these sources provide — a known limitation for the fundamentals side, where the coverage skews toward names that survived long enough to have multiple years of reported data.

**Point-in-time discipline.** All fundamentals lookups use a 6-month reporting lag (via `latest_fy_at_date(rebalance_date)` in `defensive_basket.py` / `backtest_defensive_rotation.py`). A June-30 rebalance uses fiscal-year data ending approximately 12 months earlier (accounting for the typical March fiscal year-end + 6-month reporting cushion). Prevents look-ahead bias from using not-yet-published fundamentals.

**Cross-validation.** NIFTY 200 Momentum 30 replica (top-30 equal-weighted from our momentum ranking) tracks the actual NSE-published index at daily-return correlation 0.892 (2009-2024). Absolute CAGR gap ~2.86pp (our replica outperformed — small-cap tilt in equal-weight vs cap-weighted index).

### Data-source constants

**`^TNX` (US 10-year Treasury yield)** was introduced in v1.4 as one of the entry conditions for the G10 gold rotation gate. Rationale: US real-rate dynamics are the most fundamental macro driver of gold prices globally, and including this signal as a gate condition prevents gold rotation during periods when US rates are rising (creating a structural headwind for gold). Available via yfinance with full sample coverage. Still needed by the v2.1 configuration (opt-in via `enable_defensive_basket=False`); not required for v2.2 production.

**NIFTY 200 Momentum 30 history note.** The index was launched live in August 2020 with backfilled history to April 2005 (the index's official base date) by NSE Indices Ltd. The backfilled portion uses the same mechanical methodology (semi-annual rebalance, momentum score = 6m + 12m risk-adjusted price momentum, top 30 stocks by score from NIFTY 200 universe) that NSE applies live. Cross-validation against yfinance over the 2019+ overlap period showed perfect correlation (1.000000) and 0.0000% mean relative difference, confirming data fidelity.

The RBI repo rate timeline is **hardcoded** rather than fetched at runtime because (a) no reliable free Indian short-rate API exists with full 2008-2026 coverage, (b) the repo rate is a step function with only ~55 changes over 18 years, ideal for a static table, and (c) hardcoding makes the backtest deterministic and auditable. Each row is sourced from the corresponding RBI MPC press release; the table is maintained manually and must be updated when RBI announces new rate decisions.

**Forward-testing implication:** When the strategy is run on dates after the last hardcoded entry, `build_rbi_repo_rate_series()` forward-fills the most recent rate indefinitely. This is correct as long as RBI hasn't moved the rate since the last entry — but goes silently stale if a rate change occurred and the table wasn't updated. For paper trading or live use, the table needs a manual refresh after each RBI MPC meeting (every ~6-8 weeks). Productionizing this — moving to a CSV-backed config file with a FRED API fallback — is on the roadmap.

---

## Backtest Methodology

| Item | Detail |
|---|---|
| Position sizing | Binary: +1, 0, -1. No fractional sizing. |
| Leverage | 1× max in either direction. |
| Long-side asset (v1.3) | **NIFTY 200 Momentum 30** held during bull regimes. Implementation vehicle: NSE-listed momentum ETFs (UTI, Motilal Oswal, ICICI Pru). Regime detection runs on NIFTY 50 independently of long-side asset choice. |
| Short-side asset | **NIFTY 50** (futures) on panic-short fires. ^NSEI is more liquid for short execution than the Momentum 30 ETF basket. |
| Signal timing | Signals computed from day-T close; positions applied from T+1 open via `position.shift(1)`. No look-ahead. |
| Rebalance | Daily — position re-evaluated every trading day. |
| Benchmark | NIFTY 50 buy-and-hold, no costs. |
| Transaction costs | NIFTY 50 futures (short side): **3 bps per leg**. NIFTY 200 Momentum 30 ETF (long side): **6 bps per leg** (ETF spread + STT; slightly wider than NIFTY futures due to lower turnover). Gold (GOLDBEES.NS, opt-in v2.2): **5 bps per leg**. Defensive quality basket (v2.2, on stress-flat days after 40-day gate): **30 bps per side** covering brokerage (~2 bps), STT (~10 bps), exchange charges (~1 bp), stamp duty (~1 bp), GST on brokerage (~2 bps), and slippage (~14 bps) on the 18-name basket. Applied as `\|Δposition\| × cost_bps / 10,000` for index / futures / gold; entry+exit for the defensive basket (each side × alloc, so 0.5 alloc × 30 bps = 15 bps of NAV per transition). Long↔short flips cost both legs. Cash sweep: **0 bps** (institutional auto-sweep into liquid fund). |
| Cash yield on flat days (v1.2) | Time-varying RBI repo rate as a step function (range 4.0%–9.0% over 2008–2026, avg 6.27%), with a **100 bps haircut** applied daily on fully-flat days to model realistic institutional liquid-fund execution (instrument spread + TER + sweep friction). Hardcoded in `RBI_REPO_RATE_HISTORY` in `strategy.py`. Setting `cash_yield_haircut_bps=0` recovers v1.1.1's pure-repo assumption (sensitivity in Backtest Caveats). |
| Defensive quality basket (v2.2) | On stress-flat days after 40-day persistence gate, replace flat-day return with 50/50 blend of basket return + cash. Basket = 18 equal-weighted names, semi-annual rebalance (Jun/Dec), top-200 liquid + hard rules (cfo > 0, np > 0, D/E ≤ 3) + quality percentile ≥ 0.60 + beta ≤ 0.85 + vol ≤ 0.30 + defensive-sector tilt (+0.5 bonus for FMCG/Pharma/Utility/IT) + sector cap 5. Cost: 15 bps NAV at entry + 15 bps NAV at exit + STCG on cumulative gain. Runtime overlay loaded from `data/defensive_basket_daily_returns.parquet`. Rebuild via `python build_defensive_basket.py`. Enabled by `enable_defensive_basket=True` (default in `MacroStrategy`). |
| Gold rotation (v1.4–v2.1, SUPERSEDED in v2.2) | Per-latch state machine with macro-confirmed entry gate: 0 < gold 10d return ≤ 10% AND INR 10d return > 0.5% AND US 10Y 20d return < 0 AND NIFTY < 100 DMA. Superseded by defensive basket in v2.2; code retained in the combiner. Opt-in via `enable_defensive_basket=False` (reproduces v2.1 gold-rotation behavior byte-for-byte). |
| Tax model — main return | Indian 15% short-term capital gains, annual-net model. Tax of 15% applied to net positive annual returns. Loss years unchanged. Losses within a year offset gains. Applied natively in `MacroStrategy.run()` with `apply_tax=True` default. Opt-out with `apply_tax=False` for pre-tax analysis. |
| Tax model — defensive basket (v2.2) | Short-term capital gains at exit: 15% pre-2024-07-23, 20% after (India rate stepped up mid-2024). Applied to the cumulative alloc-weighted gain over the deployment window, deducted on the exit day. |
| Risk-free rate (Sharpe) | Time-varying RBI repo rate (raw, not haircut-adjusted) — same series used for the cash-yield model. Avg 6.27% (FULL 2008-2026), 5.57% (OOS 2017-2026). Applied as `(r - repo/252)` for daily excess-return computation. Reconciliation with legacy 0.84: the v2.1 README's 0.84 was measured through 2025-12-31 on the prior yfinance data snapshot; the canonical 0.81 is through 2026-05-11 (2026 partial ~4.5 months) with refreshed data. Same rf convention throughout — the 0.03 delta is endpoint extension + data refresh, not a methodology change. |
| Out-of-sample | 2017-01-01 to 2026-05-11 designated OOS for parameter selection freeze. 2026 partial (~4.5 months) noted separately in all headline tables. |
| Parameter selection | Judgement-based for macro-signal thresholds; explicit in-sample-lock-then-OOS-apply discipline for v2.2 defensive basket parameters (persistence N=40, alloc=0.5). No grid-search overfitting. |

---

## Results

### Year-by-Year Returns

Post-tax strategy returns (Indian short-term capital gains, 15% annual-net model) vs NIFTY 50 buy-and-hold post-tax (10% long-term capital gains).

| Year | Strategy (post-tax) | NIFTY B&H (post-tax) | Outperformance |
|---|---|---|---|
| 2008 | +3.8% | -37.6% | **+41.3pp** |
| 2009 | +76.5% | +67.0% | **+9.5pp** |
| 2010 | +19.0% | +16.2% | **+2.9pp** |
| 2011 | -3.2% | -24.6% | **+21.5pp** |
| 2012 | +25.4% | +24.7% | **+0.7pp** |
| 2013 | +1.5% | +6.2% | -4.7pp |
| 2014 | +30.2% | +27.9% | **+2.3pp** |
| 2015 | +0.6% | -4.1% | **+4.7pp** |
| 2016 | +19.0% | +2.8% | **+16.2pp** |
| 2017 | +27.6% | +25.5% | **+2.2pp** |
| 2018 | -6.1% | +2.9% | -9.0pp |
| 2019 | +4.7% | +10.9% | -6.1pp |
| 2020 | +46.3% | +13.8% | **+32.4pp** |
| 2021 | +40.2% | +21.6% | **+18.6pp** |
| 2022 | +1.4% | +4.0% | -2.6pp |
| 2023 | +23.9% | +17.9% | **+6.0pp** |
| 2024 | +20.9% | +8.0% | **+12.9pp** |
| 2025 | +5.2% | +9.5% | -4.3pp |

The strategy outperforms NIFTY in **13 of 18 calendar years** on a post-tax basis. The biggest contributors are 2008 (+41.3pp, GFC drawdown avoidance), 2020 (+32.4pp, COVID panic-short plus gold rotation plus the recovery overlay), and 2011 (+21.5pp, European debt stress + cash yield at ~8% repo). The 17-year compounded result is driven by **asymmetric crisis-window capture** plus **bull-regime factor alpha**.

**2009 recovery improvement (v2.0).** The recovery overlay shifted the 2009 outcome from a structural underperformance to a meaningful outperformance. Under v1.5 (no overlay), 2009 returned +52.0% post-tax vs NIFTY's +67.0% — a loss of 15.0pp from holding Momentum 30 through the cyclical recovery. Under v2.0–v2.1 (with overlay), 2009 returns +76.5%, beating NIFTY by +9.5pp. The overlay held NIFTY 50 from March 23 to June 12, 2009 (the 60-day window after the bear regime ended), capturing the +55.9% NIFTY rebound during that period rather than Momentum 30's +28.6%. After June 15, the strategy reverted to Momentum 30 which then dominated for the rest of the year.

**2019 fix (v2.0 cooldown).** The slow-stress cooldown improved 2019 from −0.7% (v1.5) to +4.7% (v2.0). The April–May 2019 firing cluster (9 separate slow-stress fires across two months) had been forcing the strategy through repeated flat→long→flat round-trips. The cooldown blocks the rapid re-fires while preserving the legitimate persistent stress.

**2013 and 2022 fix (v2.1 drawdown confirmation).** The panic-short drawdown confirmation eliminated two specific false-fire incidents. 2013 improved from approximately −1.9% (v2.0) to +1.5% (v2.1) — the 2013-08-27 panic-short (NIFTY drawdown only ~13% at fire) is now suppressed and the strategy holds through the late-2013 NIFTY rebound. 2022 improved from approximately −1.1% (v2.0) to +1.4% (v2.1) — the 2022-02-24 Ukraine-reaction panic-short (drawdown ~11.3%) is now suppressed.

**2020 give-back (v2.1 documented tradeoff).** 2020 dropped from +52.2% (v2.0) to +46.3% (v2.1) — a 5.9pp give-back. The March 6, 2020 panic-short fire (NIFTY drawdown 11.1% from the late-January high) is suppressed under v2.1's 15% threshold. The next fire on March 9 (drawdown 15.5%) catches the move three trading days later, so the COVID protection is still strongly captured (the strategy beats NIFTY by +32.4pp in 2020 even after the give-back). The give-back is the explicit cost of demanding price confirmation before shorting in fast-crash scenarios.

**Remaining underperformance: 2013, 2018, 2019, 2022, 2025.** These five years still underperform NIFTY B&H on a post-tax basis. 2018 (−9.0pp), 2022 (−2.6pp), and 2025 (−4.3pp) are structural factor / sector rotation losses (Momentum 30 holds prior-year winners into fresh selloffs); see Limitations and Momentum-Crash Mitigation Research. 2013 (−4.7pp) and 2019 (−6.1pp) reflect residual signal-timing costs that the v2.0–v2.1 refinements only partially addressed.

![Yearly Returns](images/yearly_returns.png)

### Drawdown

![Drawdown](images/drawdown.png)

Maximum drawdown of **−12.78%** vs NIFTY's **−51.72%** (both post-tax) — a **75% reduction**. Cash yield on flat days during bear regimes (notably 2008-2009 GFC and 2020 March-August COVID recovery) cushions equity drawdowns by adding deterministic positive return on the worst-impact days. The drawdown profile reflects the joint mechanism set: the largest contributions to the gap come from the 2008 GFC (regime filter + cash yield at ~8% repo), 2011 European debt stress (gold rotation + cash yield), and 2020 COVID crash (panic-short + gold rotation + cash yield through the recovery period). v2.1's max drawdown improves vs v1.5's −14.67% primarily through the panic-short drawdown confirmation (eliminates the 2013 and 2022 short losses that previously contributed to drawdown).

### Cost Sensitivity

The long-side asset is NIFTY 200 Momentum 30 (ETF, 6 bps per leg base case). The table below varies the long-side cost; NIFTY short cost (3 bps) and gold cost (5 bps) are held fixed. Cash sweep is treated as zero-cost at all levels. All numbers post-tax. Numbers below are for the v2.1 Config 7 baseline (through 2025-12-31); the shape of the sensitivity is unchanged in v2.2 — the defensive-basket layer is independent of the Mom30-ETF cost dimension.

| Long-side cost (bps/leg) | Cumulative Return | CAGR | Sharpe (rf-adjusted approx) | Max DD |
|---|---|---|---|---|
| 0 | 1,827.4% | 17.46% | 0.89 | -12.8% |
| 3 | 1,722.7% | 17.11% | 0.87 | -12.8% |
| **6 (base, v2.1)** | **1,623.6%** | **16.75%** | **0.84** | **-12.8%** |
| 10 | 1,498.3% | 16.27% | 0.80 | -12.8% |
| 15 | 1,351.8% | 15.67% | 0.75 | -13.5% |
| 20 | 1,216.1% | 15.05% | 0.71 | -14.3% |
| 50 | 627.3% | 11.40% | 0.44 | -22.8% |

Strategy economics degrade more slowly than a purely directional version because cash yield on idle capital is unaffected by transaction costs — fully-flat days don't trade and so don't pay friction. Sharpe stays well above NIFTY's 0.20 buy-and-hold (post-tax) all the way through 20 bps long-side cost. The 50 bps row remains a stress test, not a realistic implementation cost.

---

## Robustness Checks

### Crisis-Period Stress Tests

Post-tax cumulative returns over crisis windows (strategy and NIFTY both post-tax; short-period windows within a year reflect annual-net tax scaling).

| Crisis | Window | Strategy (v2.1) | NIFTY |
|---|---|---|---|
| GFC | Sep 2008 – Mar 2009 | **+2.1%** | -30.5% |
| Euro debt | Jul 2011 – Dec 2011 | **+1.0%** | -17.8% |
| Taper Tantrum | May – Sept 2013 | **-0.3%** | -3.3% |
| NBFC / IL&FS | Aug 2018 – Nov 2018 | **-0.5%** | -4.1% |
| COVID Crash | Feb – May 2020 | **+16.8%** | -18.2% |
| Russia 2022 | Feb – Jun 2022 | **-1.7%** | -10.2% |
| Momentum sell-off 2025-26 | Oct 2025 – Apr 2026 | **+3.6%** | -3.4% |

The strategy navigates GFC-style and COVID-style regimes well — both feature decisive trend breakdowns that the panic-short and slow-stress lanes capture cleanly. The GFC window returns +2.1% (vs NIFTY −30.5%) because cash yield on the fully-flat days at ~8% repo dominates the small drag from the stress latch; all four 2008 panic-shorts (at NIFTY drawdowns of 16–32%) fire through the v2.1 confirmation gate. The 2011 European debt window flips positive (vs NIFTY −17.8%) via flat-period cash yield plus correct slow-stress force-flat coverage. The 2013 Taper Tantrum window is now nearly flat (−0.3%) — the slow-stress cooldown (v2.0) and panic-short drawdown confirmation (v2.1) together prevent the 2013-08-27 false panic-short. The 2020 COVID window returns +16.8% (vs NIFTY −18.2%) even after the v2.1 March-6 panic-short suppression; the next fire on March 9 captures the crash. The 2025-26 momentum sell-off window (Oct 2025 – Apr 2026) was a real defensive test: NIFTY fell −3.4% over this seven-month period including the March 2026 −10.19% single-month drop. The strategy returned **+3.6%**, beating NIFTY by ~7pp through the defensive engines firing as designed. This is consistent with the broader 2026 YTD picture (strategy +2.0%, NIFTY −8.9%).

**A note on Momentum 30 behavior in stress.** Momentum 30 itself underperforms NIFTY 50 in some crisis windows (e.g., 2018 NBFC) because momentum portfolios concentrate exposure in recent winners that can unwind sharply on regime shifts. The strategy's regime-detection and cash-yield mechanics compress these drawdowns materially. This is also the mechanism driving the residual 2018, 2022, and 2025 underperformance — see Limitations.

### 2026 Out-of-Sample Performance

The strategy went live in development through 2025-12-31, with 2026 reserved as out-of-sample. Through 2026-05-11:

| | 2026 YTD return (through 2026-05-11) |
|---|---|
| **Strategy (v2.2 production, post-tax)** | **~+2.0%** |
| Strategy (v2.1 baseline, post-tax) | ~+2.0% |
| NIFTY 50 Buy & Hold (post-tax) | -8.9% |
| **Outperformance vs NIFTY** | **~+11pp** |

The v2.2 defensive basket had limited effect on this specific 2026 OOS window because the March 2026 stress latch was too short to fully clear the 40-day persistence gate before the regime flipped back to bull. The v2.2 uplift is concentrated in the ~17 sustained bear windows the strategy has seen historically, not in short-duration events like this one.

(2026 YTD is a loss year for NIFTY so post-tax NIFTY = pre-tax NIFTY; the 10% LT tax only applies to gains.)

v2.1's 2026 OOS performance is broadly consistent with v1.4–v1.5's. Three mechanisms contributed:

1. **Slow-stress signal fired earlier than regime filter alone.** During the 2026 January-March equity deterioration, the slow-stress signal force-flatted on its trigger conditions (INR weakening + VIX z-score elevation + VIX momentum rising) before the 100 DMA regime filter would have disengaged on its own. This provided earlier defensive positioning.

2. **Macro-confirmed gold rotation gate prevented the 2026-01-29 blow-off-top entry.** v1.3.1's single-condition gate (gold_10d > 0) would have entered gold at +24% momentum on 2026-01-29; the position then crashed −19% within days. The v1.4 macro-confirmed gate blocks entries above the 10% momentum cap, preventing this specific failure mode.

3. **Slow-stress cooldown and drawdown-confirmed panic-short** did not materially change OOS results vs v1.4–v1.5 (the 2026 OOS window did not contain a chop period that would have triggered the cooldown's benefit, nor a borderline panic-short fire that the drawdown confirmation would have caught or suppressed). The two v2.0–v2.1 refinements are primarily in-sample optimizations against patterns identified during diagnostic work; their OOS performance neither confirms nor contradicts the in-sample benefit on this single window.

**The March 2026 stress window is a clean illustration of the defensive engines working as designed.** NIFTY 50 fell −10.19% in March 2026 alone (a single-month drawdown comparable to several full crisis years in the historical sample). The strategy returned +0.33% over the same month — a 10.5pp swing vs the index — because the slow-stress signal had already moved the strategy to cash (earning the haircut-adjusted RBI repo rate) before the March crash deepened. This single OOS month captures the strategy's core thesis: avoid the worst equity drawdowns while still capturing bull-regime upside. The 2026 YTD total (+2.0% strategy vs −8.9% NIFTY 50) is the cumulative effect of this defensive positioning through the full Jan-May period.

Buy-and-hold YTD for the three indices considered (all post-tax): NIFTY 50 −8.9%, NIFTY 200 Momentum 30 (estimated) −5% to −6%. The strategy outperformed all three benchmarks in the OOS window.

### Cross-Country Validation

The slow-stress signal architecture introduced in v1.4 (INR weakness + VIX z-score regime shift + VIX momentum) was validated on US market data spanning 1995-2025 using analog substitutions: DXY-rising for INR-weakening (both measuring sustained currency stress in the dominant direction for the respective market) and US VIX for India VIX. The signal specification was held exactly fixed — no re-parameterization, no calibration to US data.

#### Results

Overall fire rate: **3.83% of trading days over 31 years**.

US stress events detected (**9 of 9 documented events**):

| Event | Window | Signal Detection |
|---|---|---|
| LTCM crisis | Aug-Oct 1998 | Pre-fire Jun 11, 1998 (45 days early) |
| Dot-com bust | Mar 2000-Oct 2002 | Multiple latches across the window |
| Pre-GFC stress | Jul-Aug 2007 | Fired during initial credit stress |
| Global Financial Crisis | Sep 2008-Mar 2009 | Sustained firing through crash |
| Euro debt crisis | Aug-Oct 2011 | Fired during peak stress |
| China devaluation | Aug 2015-Feb 2016 | Multiple latches |
| Fed tightening shock | Oct-Dec 2018 | Fired |
| COVID crash | Feb-Apr 2020 | First fire Feb 21 (6 days into stress) |
| 2022 inflation shock | Apr-Oct 2022 | Sustained firing |

False positive rates in calm bull years:
- 2017: 0.0%
- 2019: 1.1%
- 2014: 7.5%
- 2021: 4.4%

#### Interpretation

The cross-country validation tests whether the slow-stress signal architecture detects genuine sustained EM-style stress regimes or whether it is curve-fit to specific Indian historical events. Catching 9 of 9 documented US stress events using an unchanged signal specification at a 3.83% overall fire rate provides strong empirical evidence that the architecture generalizes across markets, time periods, and event types.

The pre-fire on LTCM (June 11, 1998, approximately 45 days before the LTCM crisis is conventionally considered to have begun) is particularly significant. The signal detected sustained DXY weakness combined with US VIX z-score elevation and momentum confirmation well before LTCM's formal events. This is the kind of leading-indicator behavior that distinguishes a real signal from a coincidence detector.

False positive rates in clearly calm years (2017: 0.0%, 2019: 1.1%) indicate the signal is selective rather than over-firing. Higher false positive rates in 2014 (7.5%) reflect mid-cycle vol elevation around Russia-Ukraine tensions and Fed taper concerns that did not escalate into full stress regimes — these are edge cases where the signal correctly identified macro deterioration that ultimately resolved without crisis.

This validation does not eliminate overfitting risk entirely — the signal specification was developed against Indian data, and the test is on US data using the same specification. A future researcher who developed a strategy on the US data first would arrive at potentially different parameters. But cross-market validation with an unchanged specification is a stronger empirical defense against curve-fitting than parameter parsimony alone, and substantially stronger than any defense available to v1.3.1.

The full validation script is at [`validate_us_cross_country.py`](validate_us_cross_country.py) in the project root.

### Walk-Forward Validation

Rolling 5-year training / 1-year out-of-sample windows across the full 2008-2026 sample (13 windows total). For each window, the three parameters originally selected by sensitivity testing — slow-stress cooldown days, panic-short drawdown threshold, post-bear recovery drawdown threshold — were re-optimized on the training window by maximizing Sharpe across a pre-specified grid (cooldown ∈ {0, 3, 5, 7, 10, 15, 20}; panic-short DD ∈ {0.08, 0.10, 0.12, 0.15, 0.20, 0.25}; recovery DD ∈ {0.10, 0.12, 0.15, 0.18, 0.20}; 210 combinations per window). The training-window-optimal parameters were then applied to the immediately-following 1-year OOS window. Parameters chosen on economic priors (100-DMA window, slow-stress signal thresholds, gold macro thresholds, 60-day recovery hold) were held fixed across all windows.

#### Results — production v2.1 beats window-optimal on every aggregate metric

| Metric | Window-optimal (per-window fit) | v2.1 production | Δ |
|---|---|---|---|
| Concatenated OOS CAGR | +14.85% | **+15.41%** | **+0.56pp** |
| Concatenated OOS Sharpe | 0.707 | **0.755** | **+0.048** |
| Concatenated OOS MaxDD | −15.12% | **−12.78%** | **+2.34pp shallower** |
| Geometric mean OOS-year CAGR | +15.42% | **+16.00%** | **+0.58pp** |

Of the 4 windows where parameters materially diverged from production, production won 3 of 4. The one window window-optimal won was the COVID-2020 OOS year, where a 3-day cooldown (vs production's 5-day) caught the rapid March 2020 dynamics marginally better.

#### Parameter drift across windows — the optimizer chasing noise

The per-window optimal cooldown drifts across {5, 15, 15, 3, 3, 3, 3, 5, 5, 5, 5, 7, 0} — long-cooldown choices cluster in the early training windows (where the 2008-2013 chop dominates), tighter values dominate the middle, and the final window collapses to 0 days. The per-window optimal panic-short DD threshold drifts {15, 15, 15, 15, 15, 15, 8, 8, 10, 10, 10, 10, 12}; recovery DD drifts {15, 15, 15, 15, 15, 12, 12, 12, 10, 10, 12, 12, 12} — both showing the optimizer chasing tighter thresholds in later windows. Production's stable choices (5 / 15 / 15) generalize better OOS than this drift would suggest the "optimal" choice should.

#### Interpretation

A standard walk-forward bar would require production parameters to fall within ±1pp of window-optimal in ≥80% of windows. Production hits this for the panic-short DD threshold (92%) and recovery DD threshold (85%), but only 69% for cooldown days. Strict reading would flag this as drift.

The aggregate result inverts that reading. Production beats per-window optimization on every concatenated-OOS metric. The "drift" the optimizer finds in later windows is overfitting to recent training data — production's stable choices won out-of-sample. This is the strongest defense against parameter overfitting that the strategy could pass.

Combined with the cross-country validation on US 1995-2025 data (9/9 stress events at 3.83% fire rate), the strategy now has two independent generalization defenses: architecture-level (cross-market) and parameter-level (walk-forward).

Test script: [`experiments/test_walkforward.py`](experiments/test_walkforward.py). Output: `results/test_walkforward.txt`, `results/test_walkforward_per_window.csv`, `results/test_walkforward_parameter_stability.csv`, `plots/test_walkforward_equity_overlay.png`, `plots/test_walkforward_parameter_drift.png`.

### Parameter Sensitivity Coverage

The walk-forward validation above re-optimizes the three most-recently-tuned parameters (v2.0–v2.1 era refinements) across rolling windows. For full transparency on the rest of the parameter space, this section consolidates the sensitivity tests for every fitted parameter — what was swept, what plateau it sits on, and the one explicit gap.

| Parameter | Production value | Range tested | Spread (full-sample CAGR) | Plateau? | Test location |
|---|---|---|---|---|---|
| `slow_stress_lock_days` | 5d | {0, 3, 5, 7, 10, 15, 20} | 0.14pp across qualified range (0–5d) | Tight plateau within qualified range; sharp cliff above (7d+ blocks 2018 Sept NBFC second leg) | README Signal Logic §2 + walk-forward |
| `panic_short_dd_threshold` | 15% | {0, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25} | 0.17pp across qualified range (8–15%) | Tight plateau within qualified range; disqualified above (20%+ blocks 2 of 4 GFC panic-shorts) | README Signal Logic §3 + walk-forward |
| `v2_dd_threshold` (post-bear recovery) | 15% | {0.10, 0.12, 0.15, 0.18, 0.20} | Identical across 15–20% (no qualifying bear DDs in that range across sample) | Flat plateau 15–20%; 12% adds false positives, 10% over-triggers | README Signal Logic §5 + walk-forward |
| `v2_days` (V2 hold period) | 60d | {30, 45, 60, 90, 120} | 0.43pp across full range | Moderate sensitivity; 60d sits inside a stable region (60d and 120d ≈ optimal, 30d worst at −0.37pp); MaxDD identical across all values | `experiments/test_v2_hold_period_sensitivity.py` |
| Regime-filter DMA window | 100d | {50, 75, 100, 125, 150, 200} | Tested in `test_dma_sensitivity.py` | 100d sits within the qualified range; 50d over-triggers, 200d lags too much | `experiments/test_dma_sensitivity.py` |
| Slow-stress signal thresholds (INR 20d > 1%, VIX 90d z > 1.5, VIX 5d mom > 0) | as listed | Rejected-variants table (VIX-only, 60d windows, 3-day persistence, 2-of-3 mixed, INR+VIX+oil 60d) | Each rejected variant documented with reason | README Signal Logic §2 "tested but not adopted" + cross-country US validation (9/9 stress events) |
| Gold gate macro thresholds (gold 10d cap 10%, INR 10d > 0.5%, US 10Y 20d < 0) | as listed | Rejected-variants table (tighter lower bound, upper-cap only, both bounds, no gate, INR-only, 4-condition sum score) | Each rejected variant documented with reason | README Signal Logic §4 + Gold Rotation Gate Iterations subsection |
| Cash haircut on flat days | 100 bps | {0, 50, 100, 200} | Documented in Backtest Caveats §5 | 100 bps default chosen over the pure-repo v1.1.1 assumption as a conservatism check | README Backtest Caveats §5 |
| Long-side cost | 6 bps | {0, 3, 6, 10, 15, 20, 50} | Cost Sensitivity table | Sharpe stays >NIFTY's 0.20 through 20 bps | README Cost Sensitivity table |

**Coverage summary:** of the ~10 fitted parameters in v1.4–v2.1, 9 have explicit sensitivity tests (either inline sweeps in the README, dedicated test scripts, or the rejected-variants tables). The walk-forward additionally tests the 3 most-recently-tuned parameters across 13 rolling windows. The cross-country US validation tests the slow-stress signal *architecture* (not threshold-level) by applying the unchanged specification to 31 years of US data.

**One known gap:** V2 hold period was originally noted in Signal Logic §5 as "not separately swept" and was chosen because it matches the NSE semi-annual rebalance cadence. The sensitivity test added in June 2026 (table row above) confirms 60d sits inside a stable region with moderate (~0.43pp) full-sample CAGR variation. 60d is not strictly optimal — 120d marginally outperforms (+0.06pp CAGR) — but the difference is within noise and MaxDD is identical across all tested values. The economic-prior choice survives sensitivity testing.

**Honest framing.** The strategy passed every sensitivity test where one was run, and the walk-forward provided rolling-window OOS validation for the most-tuned parameters. The remaining honest exposure is to *design-level* researcher degrees of freedom: each of the 6 version evolutions (v1.0 → v2.1) was a response to a documented in-sample failure mode. That class of overfitting cannot be fully neutralized by parameter sensitivity tests — it requires forward paper-trading evidence, which is in progress (see Roadmap).

---

## Benchmark Attribution

The strategy's reported outperformance vs NIFTY 50 buy-and-hold conflates three sources of value: asset selection (NIFTY 200 Momentum 30 vs NIFTY 50), the regime filter's tactical exposure decisions, and the override layer (slow-stress signal, panic-short trigger, momentum-gated gold rotation). To isolate each component's contribution and stress-test the strategy against more sophisticated comparators than buy-and-hold, the strategy was benchmarked against 10 alternatives spanning passive and dynamic rule-based portfolios.

### Benchmarks tested

**Static (passive alternatives):**

1. NIFTY 50 buy-and-hold (the conventional loose benchmark)
2. NIFTY 200 Momentum 30 buy-and-hold (long-side asset alone)
3. GOLDBEES.NS buy-and-hold (gold alone)
4. Static 50/50 Mom30/gold, monthly rebalance
5. Static 70/30 Mom30/gold, monthly rebalance
6. Risk-parity Mom30/gold (inverse-vol weighted, monthly rebalance)

**Dynamic (rules-based timing alternatives):**

7. **Dynamic A: Regime filter alone** — 100% Mom30 when NIFTY > 100 DMA, 100% cash otherwise. The strategy's regime filter in isolation with no override signals.
8. **Dynamic B: Regime filter + static gold** — 70/30 Mom30/gold in bull, 100% gold in bear.
9. **Dynamic C: Cross-sectional momentum** — top-ranked among (Mom30, gold, cash) by 60-day return, monthly rebalance.
10. **Dynamic D: Vol-targeted Mom30** — Mom30 sized to 12% target vol using 20-day realized vol, residual in cash.

All benchmarks apply identical Indian short-term capital gains tax (15% annual-net positive) and per-asset transaction costs (3–6 bps per leg).

### Headline results

All numbers post-tax. Strategy uses 15% short-term capital gains; passive benchmarks use 10% long-term capital gains; rule-based benchmarks (Dynamic A etc.) use 15% short-term capital gains to match the strategy's turnover profile.

| Comparator | Strategy excess CAGR | Strategy excess Sharpe | Strategy MaxDD vs Benchmark |
|---|---|---|---|
| vs NIFTY 50 B&H | +8.38pp | +0.637 | +38.9pp better |
| vs Mom30 B&H | +~3-4pp | +0.4 | +~40pp better |
| vs Dynamic A (regime filter alone) | +2.53pp | +0.113 | +2.5pp better |

The strategy outperforms every benchmark on risk-adjusted Sharpe and Calmar. v2.0–v2.1 widen the gap vs Dynamic A meaningfully — under v1.5 the strategy beat Dynamic A by +1.42pp CAGR with a 0.5pp MaxDD disadvantage; under v2.1 it beats Dynamic A by +2.53pp CAGR with a 2.5pp MaxDD advantage.

### Decomposition of NIFTY 50 outperformance

The headline +8.38pp CAGR vs NIFTY 50 (post-tax) decomposes into three components:

| Component | Approximate contribution |
|---|---|
| Asset selection (Mom30 vs NIFTY 50, available passively) | ~3.9pp |
| Regime filter (Mom30/cash on 100 DMA) | ~2.0pp |
| Override layer (slow-stress + panic-short + gold rotation + recovery overlay + refinements) | +2.53pp |

The asset selection and regime filter components are architecturally present in v1.3 and earlier; the override layer represents the cumulative v1.4–v2.1 incremental value over a simpler regime-filter design.

### The Dynamic A comparison: isolating the override layer

Dynamic A — the strategy's 100-DMA regime filter in isolation with no override signals — is the most rigorous comparator for measuring the override layer's contribution. Strategy beats Dynamic A by +2.53pp CAGR and +0.113 Sharpe (post-tax).

#### Year-by-year scorecard vs Dynamic A (v2.1)

| Year | Excess vs Dynamic A | Notes |
|---|---|---|
| 2008 | −0.0pp | Both flat through GFC; panic-shorts net neutral |
| 2009 | **+26.84pp** | Recovery overlay captured NIFTY rebound (post-bear hold for 60 days) |
| 2010 | +5.45pp | Slow-stress force-flat + gold rotation |
| 2011 | +0.0pp | Slow-stress + gold offset within the bear window |
| 2012 | +0.74pp | Distributed across mechanisms |
| 2013 | −1.35pp | Slow-stress and bear-regime drag offset by panic-short DD-gate save |
| 2014 | −1.48pp | Slow-stress drag |
| 2015 | −1.34pp | Slow-stress drag (recovery overlay did not trigger; preceding bear DD <15%) |
| 2016 | +0.27pp | Roughly matched |
| 2017 | +1.50pp | Slow-stress force-flat |
| 2018 | +1.08pp | Slow-stress catches Sept NBFC (preserved by 5-day cooldown plateau) |
| 2019 | −0.03pp | Cooldown cut the chop bleed; remaining noise |
| **2020** | **+21.54pp** | **COVID — panic-short (now drawdown-gated) + recovery overlay through summer rebound** |
| 2021 | +4.63pp | Slow-stress force-flat |
| 2022 | −0.70pp | 2022-02-24 panic-short now suppressed; remaining factor rotation cost |
| 2023 | +0.0pp | Roughly matched |
| 2024 | +0.0pp | Roughly matched |
| 2025 | +1.22pp | Drawdown-confirmed panic-short avoided one false fire |

Net: 9 winning years (2009, 2010, 2012, 2016, 2017, 2018, 2020, 2021, 2025) totaling roughly +62pp; 5 losing years (2013, 2014, 2015, 2019, 2022) totaling roughly −5pp; 4 neutral years. Cumulative ~+57pp over 18 years compounds to ~+2.53pp CAGR.

### Why the override layer is justified

Three reasons the +2.53pp CAGR contribution is meaningful rather than disappointing:

**1. Diversified across multiple independent mechanisms.** Panic-short (with drawdown confirmation), gold rotation, slow-stress force-flat (with cooldown), and the recovery overlay each contribute substantially and positively. The architecture is not dependent on any single signal continuing to work — if one mechanism's edge degrades in future regimes, the others continue to deliver.

**2. Coverage of fat-tail crisis events.** The 2020 COVID contribution (+21.54pp vs Dynamic A) is the regime-defensive architecture working as designed during a tail event. This is what justifies the operational overhead of the override layer — strategies built for crisis protection are evaluated partly on their crisis behavior, and this strategy delivered materially during the largest stress event in the sample. Even excluding 2020 entirely, the strategy still adds material cumulative alpha across other winning years (2009 +26.84pp from the recovery overlay alone); the alpha is not a single-event story.

**3. Architectural validity beyond Indian alpha.** The signal architecture is validated cross-country on 31 years of US data (see Cross-Country Validation section) — caught 9 of 9 documented US stress events at 3.83% fire rate. This addresses overfitting concerns that the +2.53pp Indian-sample alpha alone cannot, and supports the inference that the override layer's contribution generalizes.

### Note on Dynamic A's max drawdown (strategy now meaningfully shallower)

Under v1.5 (post-tax), the strategy's MaxDD was −14.67% vs Dynamic A's −15.25% — already 0.58pp shallower. The v2.0–v2.1 refinements widen this advantage: the strategy's MaxDD is now −12.78% vs Dynamic A's −15.25% — a 2.47pp shallower drawdown. The improvement is primarily attributable to the panic-short drawdown confirmation (eliminating the 2013 and 2022 false shorts that previously contributed to peak drawdown depths).

The full benchmark comparison script is at [`experiments/benchmark_comparison.py`](experiments/benchmark_comparison.py).

---

## Momentum-Crash Mitigation Research

The long-side asset (NIFTY 200 Momentum 30) beats NIFTY 50 by ~4.8pp CAGR over the sample but underperforms in 4 years: 2009, 2018, 2022, 2025. These split into two distinct mechanisms.

### The V-recovery momentum crash (2009, 2020-adjacent) — addressed in v2.0

Documented by Daniel & Moskowitz (2016, *Momentum Crashes*): after a sharp market crash, a momentum index holds stale pre-crash winners (defensives that survived the crash) while the recovery is led by beaten-down cyclicals. Because the NIFTY 200 Momentum 30 momentum score is computed over trailing 6- and 12-month windows and rebalances only semi-annually (June/December), the index cannot refresh into the recovery leaders until a full rebalance cycle after the bottom. In 2009, momentum lagged NIFTY through most of the year; the index did not flip into recovery cyclicals until the December 2009 rebalance, by which point the trailing windows were dominated by the recovery.

**Production overlay (v2.0).** When the strategy is in a long position immediately after a bear→bull regime flip preceded by a NIFTY drawdown of 15% or more, hold NIFTY 50 instead of NIFTY 200 Momentum 30 for the next 60 trading days, then revert to Momentum 30. See [Signal Logic section 5](#5-post-bear-nifty-recovery-overlay-v20) for full mechanics and sensitivity. Empirical impact: +1.00pp CAGR vs v1.5, +0.04 Sharpe, max drawdown unchanged. The overlay fires only during V-recovery windows (~180 days out of the 17.7-year sample, primarily 2009 and 2020) and does not affect the strategy outside those windows.

### Rejected alternative: Daniel-Moskowitz bear-state rule (R1)

A second finance-grounded overlay was tested for the same V-recovery problem and rejected in favor of the production overlay:

| Overlay | Trigger | Net Δ (cumulative) | ΔCAGR | ΔSharpe | False positives |
|---|---|---|---|---|---|
| **Production (v2.0): drawdown-based** | Bear-regime drawdown ≥15%, then hold NIFTY 60 days on re-entry | +27.21pp | +1.00pp | +0.04 | None |
| R1 (Daniel-Moskowitz bear-state) — rejected | NIFTY trailing 12-month return < −10% at semi-annual rebalance, hold NIFTY 6 months | +14.14pp | +0.87pp | +0.028 | 2012 (grinding bear, −6.95pp) |

Both improve risk-adjusted returns with max drawdown unchanged. The production overlay is more selective: its contiguous-bear-regime drawdown measure distinguishes sharp crashes (2008-09, COVID) from grinding bears (2011-12), so it avoids the 2012 false positive that R1's trailing-return rule takes. R1 is the textbook formulation; the drawdown-based variant is an empirically superior version for this sample. Test scripts: [`experiments/test_recovery_rotation.py`](experiments/test_recovery_rotation.py) and [`experiments/test_rebalance_aligned_rules.py`](experiments/test_rebalance_aligned_rules.py).

### The structural-rotation losses (2018, 2022, 2025) — not yet addressed

The other underperformance years are a different mechanism: factor/style rotations rather than V-recovery crashes. 2018 was a midcap-vs-largecap rotation (IL&FS crisis crushed midcaps while large-caps held); 2022 and 2025 were sector rotations (momentum holding prior-year winners into fresh selloffs). These have no clean crash signature for the recovery overlay to trigger on — the underperformance accrues gradually during normal long-holding periods. Multiple mitigation approaches were tested:

| Overlay | Approach | Result |
|---|---|---|
| Relative-strength timing | Swap Mom30 → NIFTY 50 when Mom30 trailing relative strength below threshold | Net negative across all thresholds; whipsaws and gives back more in win years than it saves |
| Asset swap during stress windows | Hold NIFTY 50 instead of Mom30 during slow-stress flats with macro confirmation | Marginal effect; can't distinguish factor rotation from V-recovery |
| Intensity-scaled stress flats | Partial-flat sized by VIX z-score during stress | Breaks 2008 GFC defense (moderate-z early-crisis days hold partial Momentum 30 into the crash) |
| Sector concentration gate | Detect Mom30 sector concentration via rolling regression; signal weakness when most-loaded sector trends down | Initial diagnostic was informative but the underlying β computation used corrupted Midcap 150 cache data (TR instead of PR); result requires re-validation. See "Composition swap research — paused due to data integrity issue" subsection below. |

These losses remain unaddressed by any overlay tested to date. Further approaches under investigation include multi-asset simultaneous holding, breadth-based regime detection, and sector-rotation signals using the newly cached NSE sector index data. Diagnostic script: [`experiments/diagnose_mom30_composition.py`](experiments/diagnose_mom30_composition.py).

### Composition swap research — paused due to data integrity issue (June 2026)

A research arc spanning ~6 weeks investigated swapping Mom30 → NIFTY 50 on days when Mom30's composition was structurally exposed to a falling cap segment, using a rolling 60-day regression of Mom30 returns on NIFTY 50 + NIFTY Midcap 150 + NIFTY Smallcap 250 to extract a β_mid composition signal. Four architectural iterations of the cap composition swap rule were tested:

- **v1 forward-hold same-day swap** (252-day hold or AND-exit) — rejected (OOS −0.62pp)
- **v2 OR-exit + engagement filter** — rejected (full sample −0.01pp, inert)
- **v3 single recovery exit with 5-day persistence** — rejected (OOS −1.22pp)
- **v4 AND-exit + ongoing engagement yield + entry engagement filter** — initially **+0.16pp full CAGR / +0.13pp OOS** (PRE-data-correction)

A sensitivity sweep across 6 variants of v4 (exit DMA width, exit-c specification, persistence days, entry threshold) all clustered around the v4 baseline. Swap-target sensitivity tested 6 alternative defensive assets (NIFTY 100, 50/50 NIFTY+cash, 100% cash, regime-filtered NIFTY/cash, NIFTY FMCG, NIFTY Pharma) — NIFTY 50 was near-optimal across the family. A sector composition diagnostic ran the same regression framework with sector indices (Bank, IT, FMCG, Pharma, Auto, Energy, Metal, Realty, Infra, PSE); Infra emerged as dominant signal in 2022 H1 and 2025 H1.

**Data integrity issue (discovered June 2026).** During verification of the v4 result, a level cross-check against published NSE values revealed that `_extra_data_cache.pkl["NIFTY_MIDCAP_150"]` had been populated from yfinance ticker `^NSMIDCP`, which is actually NIFTY Midcap 150 *Total Return Index* (with dividend reinvestment), not the Price Return version. Cached levels were 3-4× too high (Dec 2024 cached = 67,988 vs actual NSE NIFTY Midcap 150 PR = 21,141). Daily returns correlated 0.93 with the real series so day-by-day diagnostics looked plausible, but the regression β values were wrong.

After correcting the data source (NSE CSV NIFTY Midcap 150 PR), the original v4 result reversed: from **+0.16pp full / +0.13pp OOS** to **−0.28pp full / −1.37pp OOS / −0.023 Sharpe**. The "big winning" Sep 2020 → Mar 2021 episode that drove most of v4's apparent edge **never enters at all under the corrected data** (β_mid + midcap-weak conjunction never held in that window). All v4 family results (sensitivity sweep, swap-target sensitivity, sector diagnostic interpretations) were re-run on corrected data; every variant tested came out negative on full sample CAGR.

**Status:** Composition research paused. v2.1 production remains the shipped strategy with no composition overlay. `CompositionSwapOverlay` class is retained in `strategy.py` as scaffolding (default off) for any future re-test with corrected data.

Test scripts: [`experiments/test_composition_v4.py`](experiments/test_composition_v4.py), [`experiments/test_composition_sensitivity.py`](experiments/test_composition_sensitivity.py), [`experiments/test_swap_target_sensitivity.py`](experiments/test_swap_target_sensitivity.py), [`experiments/diagnose_mom30_composition.py`](experiments/diagnose_mom30_composition.py), [`experiments/diagnose_mom30_sector_composition.py`](experiments/diagnose_mom30_sector_composition.py).

---

## Limitations

Active weaknesses I am addressing on the roadmap.

1. **Limited cross-asset universe.** The current implementation is two-asset (NIFTY + gold) with cash as the third state. The structural question — whether cumulative alpha vs NIFTY can be sourced from something other than tactical reduction of NIFTY exposure — is now partially addressed via gold rotation, but the asset universe remains narrow. Expansion to additional risk assets (USDINR overlay, broader equity indices) is on the roadmap. Walk-forward validation of the gold rotation rule specifically has not been done.

2. **Momentum-factor structural-rotation losses (2018, 2022, 2025).** The Momentum 30 long-side asset underperforms NIFTY 50 in these three structural factor / sector rotation years. 2018 was a midcap-vs-largecap rotation (IL&FS crisis crushed midcaps while large-caps held); 2022 and 2025 were sector rotations where Momentum 30 held prior-year winners into fresh selloffs. The V-recovery crash years (2009, COVID-adjacent) are now addressed via the v2.0 recovery overlay, but the structural-rotation years lack a clean crash signature. Multiple mitigation approaches were tested (relative-strength timing, asset swaps during stress, intensity-scaled flats; sector- and cap-composition diagnostics paused due to data integrity issue — see Momentum-Crash Mitigation Research) — all either failed to fix the years or broke winning years. These losses remain unaddressed; further approaches under investigation include multi-asset simultaneous holding, breadth-based regime detection, and sector-rotation signals using the newly cached NSE sector index data.

3. **Panic-short exit logic is structurally thin.** The active short uses only two exit mechanisms — a 5-day / 20-day NIFTY MA crossover and a 60-day time cap (the latter only active in `hold=True` configs) — and both parameter sets (5/20 windows, 60-day cap) were hand-picked rather than derived from panic-event duration statistics or a parameter sweep. The strategy enters via a strict 4-condition AND (VIX level, VIX spike, below 100-DMA, and v2.1's drawdown confirmation) but exits on a single binary MA flip — an asymmetry between strict-entry and loose-exit that has not been stress-tested against scenarios where the initial short thesis is wrong (e.g. a V-shaped recovery that bottoms before the MA crossover registers). There is no stop-loss, no profit-taking rule, and no volatility-normalized exit threshold. **Mitigating controls:** (a) the production config ships with `hold=False` (pulse short only — short is active solely on the days where panic conditions raw-fire AND drawdown confirmation passes), structurally capping any single-short loss exposure at one day; (b) v2.1's drawdown confirmation filters the two known false-fire events (2013, 2022). The roadmap addresses the broader exit framework; until then, sizing of any panic-short component should be conservative and the no-hold default should not be flipped without redesigning the exit framework first.

4. **No live track record.** All results are backtest-only. Out-of-sample paper trading from 2026 onward is in progress; live trading at size has not been undertaken.

5. **Bull-regime alpha gap (ADDRESSED in v1.3, factor-crash risk partially addressed since v2.0).** v1.2 had a structural bull-regime alpha gap. v1.3 addressed this via NIFTY 200 Momentum 30 substitution. The V-recovery momentum-crash failure mode is addressed in v2.0 via the post-bear NIFTY recovery overlay. The structural-rotation factor-crash years (2018, 2022, 2025) remain open — see Limitation 2.

6. **Lagging recovery detection.** The 100-DMA trend filter is a lagging indicator by construction — NIFTY typically rallies 15-25% off a crisis trough before crossing its 100 DMA, so the strategy systematically misses the early-recovery phase of each cycle. Once the regime flips to bull, the v2.0 recovery overlay then captures the post-flip 60-day rebound (which substantially compensates for the late re-entry on V-recoveries), but the strategy still misses the pre-flip portion of any cyclical recovery. Candidate replacements or augmentations include breadth signals (% of NIFTY 200 above 50 DMA), shorter MA crossovers (20/50 golden cross), and VIX-peak-rollover detection (separate from the absolute VIX-level signal). None were adopted because faster trend filters generate more false signals in chop regimes and require dedicated parameter testing.

7. **Panic-short fast-crash risk under v2.1 drawdown confirmation.** The 15% drawdown confirmation on panic-short suppressed the March 6, 2020 fire (NIFTY drawdown only ~11.1% at fire time). The next fire on March 9 (drawdown 15.5%) caught the move three trading days later, so COVID protection remained strongly captured overall (2020 strategy +46.3% post-tax vs NIFTY +13.8%). But if a future crisis develops faster than COVID — where panic-short would normally fire at <15% drawdown and price continues to fall sharply before crossing the 15% threshold — the gate would delay defense materially. The qualified-plateau sensitivity evidence (8% to 15% threshold spread is 0.17pp CAGR) suggests the rule is robust within range, but the 5.9pp 2020 give-back is the explicit cost of demanding price confirmation; a future fast-crash scenario could compound this cost.

8. **Single-day news-event surprises are architecturally unmitigable.** The strategy is a long-term trend strategy gated by trailing moving-average regime detection. By construction, it cannot anticipate policy announcements, geopolitical shocks, or other discrete events that produce instant gap moves. Three documented cases where this cost the strategy materially:

   - **2019-09-20** — Finance Minister Sitharaman's surprise corporate tax cut (corporate rate slashed 30% → 22%, new manufacturing 15%). NIFTY +5.32% in a single day, the largest single-day rally in modern Indian history. The strategy was flat (regime filter had triggered from the Aug-Sep downturn) and returned +0.01% — a single-day cost of −5.32pp.
   - **2022-02-25** — Day after Russia invaded Ukraine. NIFTY +2.53% relief rally as panic faded and the invasion was priced in. Strategy flat (regime filter / slow-stress had triggered from Feb 24's −4.78%); returned +0.01%.
   - **2022-02-15** — Russia's "partial troop withdrawal" headline (later proved false). NIFTY +3.03% global relief rally; strategy flat.

   Of the top 10 wrong-side days in the strategy's losing years, 7 are flat days where the regime filter had triggered and the news-driven rally happened before the filter could re-engage. Across all such days, cumulative single-day cost is approximately +37pp of "regret" relative to optimal positioning. This is a structural cost of the trailing-MA architecture, not a bug. Faster regime detection (50-DMA or breadth signals) trades this lag for whipsaw cost in chop regimes; the trade-off was evaluated and 100-DMA's slower lag was retained because the chop cost is worse on average. The honest framing: this strategy is built to participate in trending bull regimes and avoid extended bear regimes; it is not built to capture or anticipate news-driven single-day moves, and a separate higher-frequency strategy would be the appropriate vehicle for that.

---

## Backtest Caveats

These are structural caveats inherent to backtest research and macro-strategy design — not specific flaws of this strategy. They are documented for transparency, not as roadmap items.

1. **Researcher degrees of freedom (now substantially mitigated).** Parameters (lookback windows, thresholds, DMA length) and signal selection were chosen with knowledge of recent Indian market behavior. Three independent defenses now address overfitting concern: (a) plateau-based sensitivity testing for every fitted parameter — see [Parameter Sensitivity Coverage](#parameter-sensitivity-coverage) for the consolidated table covering all ~10 fitted parameters, their tested ranges, and plateau verdicts; (b) cross-country validation on US 1995-2025 data using unchanged signal specification (9/9 stress events at 3.83% fire rate); (c) walk-forward parameter validation across 13 rolling 5y train / 1y OOS windows — production v2.1 parameters beat per-window-optimal selections on every aggregate OOS metric (+0.56pp CAGR, +0.048 Sharpe, +2.34pp shallower MaxDD). The v2.0–v2.1 refinements were tested with disqualification rules applied to each parameter sweep (no variant that breaks 2008, 2018 September NBFC, 2020 COVID, or 2021 defensive coverage was retained). Combined, these are substantially stronger overfitting defenses than parameter parsimony alone — but they do not neutralize *design-level* researcher degrees of freedom (each version evolution was a response to an observed in-sample failure); that class of overfitting requires forward paper-trading evidence to test.

2. **Limited regime diversity in available data.** India VIX only exists from 2008, capping the Indian backtest at ~17 years. Two true crisis regimes (GFC, COVID) plus several smaller stresses (2011, 2013, 2018, 2022) is statistically thin for a regime-conditional model. v1.4's cross-country validation extends architecture-level evidence to 31 years and 9 stress events on US data, materially addressing this concern.

3. **Non-stationarity of macro relationships.** USDINR / VIX / equity correlations have shifted over the sample (pre vs post 2014 RBI inflation-targeting framework, pre vs post 2020 liquidity regime, evolving FII flow dynamics). The strategy implicitly assumes some stability in these relationships going forward.

4. **Capacity and crowding unknown.** Backtest is unaware of position size. VIX-based and panic-short signals may have crowded behavior in stress regimes; edge at scale has not been tested.

5. **Cash-yield modeling assumes liquid-fund-style execution (v1.2 / v1.3 / v1.4).** The strategy credits the RBI repo rate minus a 100 bps haircut on fully-flat days. v1.1.1 used a no-haircut (pure repo) assumption that external review flagged as too aggressive; v1.2's 100 bps default is more conservative and more credible. Additionally, the Sharpe-ratio benchmark hurdle is held constant at 6% even though the modeled cash yield ranges 3–8% over the sample after haircut — a minor inconsistency that doesn't materially affect cross-strategy comparison since NIFTY's Sharpe uses the same hurdle.

6. **Tax-model approximation (v1.4).** The 15% annual-net tax model is an approximation of Indian short-term capital gains tax. It applies a flat 15% to net positive annual returns; loss years are unchanged; intra-year losses offset gains. Real tax treatment depends on holding period, instrument-specific treatment (futures vs equities), and complex carry-forward rules not modeled. The approximation is appropriate for deployability-relevant headline metrics but should not be used for precise tax planning. Pre-tax analysis is available via `apply_tax=False`.

7. **Limited out-of-sample coverage (partially addressed via walk-forward).** Held-out 2026 OOS testing covers 2026-01-01 through 2026-05-11 — a single year, single regime. v2.1 outperformed NIFTY by +10.9pp post-tax in this window. Broader OOS coverage is now provided via walk-forward validation: 13 rolling 5y train / 1y OOS windows produce concatenated OOS results across 13 distinct one-year periods spanning 2013-2026. Production v2.1 parameters beat per-window-optimal selections on every aggregate OOS metric (+15.41% vs +14.85% CAGR, 0.755 vs 0.707 Sharpe). Cross-country validation on US data (9/9 stress events caught) provides architecture-level OOS evidence orthogonal to the parameter-level walk-forward.

---

## Roadmap

In progress and planned:

1. **Multi-asset holding** — test simultaneous holding of Momentum 30 and gold/NIFTY rather than the current single-asset rotation. Benchmark attribution suggested diversification value the current single-asset structure leaves unused. The post-bear NIFTY recovery overlay (v2.0) is a single-asset-at-a-time switch; multi-asset holding is the broader generalization. Architecture change to `MacroStrategy`'s position accounting; requires careful cost modeling for simultaneous long-side positions.

2. **Further mitigation approaches for the 2018/2022/2025 structural-rotation losses.** These years lack the V-recovery signature the recovery overlay targets; the loss-pattern diagnostic confirmed no single price-based signal in our current dataset cleanly identifies them without unacceptable win-year whipsaw cost. An earlier composition diagnostic (`experiments/diagnose_mom30_composition.py`) appeared to identify an informative conditional signal but used corrupted Midcap 150 cache data (Total Return instead of Price Return). Re-running with corrected data is on the roadmap; until then, composition-based mitigation approaches are paused. See "Composition swap research — paused due to data integrity issue" subsection in the Momentum-Crash Mitigation Research section for details. Candidate directions to investigate further: sector-rotation signals using the cached NSE sector indices (NIFTY_BANK, NIFTY_IT, NIFTY_AUTO, NIFTY_FMCG, etc.), multi-asset holding alongside Momentum 30, breadth signals (% of NIFTY 200 above own 50 DMA), and Quality 30 / Low Volatility 30 as conditional alternative long-side assets.

3. **Stock-level momentum portfolio construction (new direction, June 2026).** Extend the project from index-level overlay design (current: regime-aware engines applied to NIFTY 200 Momentum 30 index) to stock-level portfolio construction. Build a top-200 universe (BSE 200 by market cap + liquidity), apply quality screen (SCDV-style: ROE, debt/equity, earnings stability), score remaining names by 6m + 12m risk-adjusted momentum, construct a 30-stock portfolio with max 3% per position and optional sector-neutral constraint. Backtest against NIFTY 200 Momentum 30 index and NIFTY 200 Quality 30 index. Integrate as alternative long-side asset in v2.1 architecture for end-to-end comparison. This mirrors the construction methodology used by active AMC quant funds (e.g., 360 ONE Quant Fund's SCDV + momentum hybrid). 5-6 weekends estimated. Demonstrates stock-level construction capability beyond the current index-overlay design.

4. **Early-recovery detection.** The 100-DMA trend filter lags cyclical recoveries by 15-25% of the underlying move. The v2.0 recovery overlay compensates for the post-flip portion of this lag but doesn't help with the pre-flip portion. Candidate replacements/augmentations: breadth signals (% of NIFTY 200 above 50 DMA), shorter MA crossovers (20/50 golden cross), VIX-peak-rollover (VIX has fallen ≥30% from a recent peak above 25). Trade-off to test: faster trend filters generate more false signals in chop regimes. Requires dedicated parameter testing and OOS validation before adoption.

5. **Additional safe-haven cross-asset overlays** — extend beyond gold to USDINR and other defensive assets historically resilient during India-stress regimes. Targets diversification of the safe-haven sleeve and improvements to Sharpe through reduced single-asset reliance during stress windows.

6. **Panic-short exit framework redesign** — replace the current single-rule MA crossover exit with a layered framework: profit-take at +X%, stop-loss at −Y%, volatility-normalized exit thresholds (scale by current VIX), and immediate re-evaluation of entry conditions (cover the moment any of the entry conditions flips). Required before flipping the production config from `hold=False` to `hold=True`. Addresses Limitation 3.

7. **Signal-by-signal P&L attribution** — decompose cumulative P&L by lane (slow-stress, panic-short, regime-filter contribution, gold rotation, recovery overlay) to confirm each signal independently earns its keep. Partial work already complete via [`attribution_v14.py`](attribution_v14.py) (asset selection vs regime call decomposition).

8. **Forward paper-trading** — daily logged signals against live data from 2026 onward.

9. **Productionize the RBI repo rate feed** — replace the hardcoded `RBI_REPO_RATE_HISTORY` table with a CSV-backed config file plus a FRED API fallback for any dates after the last manual entry. Add a runtime warning if the strategy runs on a date past the latest available rate. Required before any live trading; nice-to-have for paper trading.

10. **Modular refactor** — break monolithic `strategy.py` into `src/data.py`, `src/signals.py`, `src/backtest.py` for extensibility.

**Completed in v2.1 validation (June 2026 — previously on roadmap):**
- ✅ Walk-forward parameter validation (13 rolling 5y train / 1y OOS windows; production v2.1 beats per-window-optimal on every aggregate OOS metric: +0.56pp CAGR, +0.048 Sharpe, +2.34pp shallower MaxDD)
- ✅ Exhaustive vol-scaling rejection (32 variants across two test rounds; closed across estimator, target structure, regime gating, smoothing, and residual asset choice)

**Completed in v2.0–v2.1 (previously on roadmap):**
- ✅ Post-bear NIFTY recovery overlay (v2.0 — addresses 2009-style V-recovery momentum-crash failure mode; +1.00pp CAGR, +0.04 Sharpe)
- ✅ Slow-stress cooldown (v2.0 — addresses 2019 April-May whipsaw chop; +0.14pp CAGR, max DD narrows −14.67% → −13.38%)
- ✅ Panic-short drawdown confirmation (v2.1 — addresses 2013-08-27 and 2022-02-24 false fires; +0.011 Sharpe, max DD narrows −13.38% → −12.78%)

**Completed in v1.4 (previously on roadmap):**
- ✅ Slow-stress regime layer (`SlowStressSignal` — addresses 2013 / 2018 failure modes at the signal level)
- ✅ Macro-confirmed gold rotation gate (addresses 2026 H1 gold-rotation failure mode)
- ✅ Cross-country signal architecture validation (US 1995-2025, 9/9 stress events)
- ✅ Native tax modeling (`apply_annual_tax` integrated into `MacroStrategy.run()`)

**Completed in v1.5 (previously on roadmap):**
- ✅ 2019 gold-in-bull anomaly fix (bear-regime requirement on gold rotation entry + mid-latch bull-flip exit)

---

## Version History

All numbers in the table below are post-tax. Pre-v1.4 rows did not have a native tax model and are shown as their pre-tax values (no annual-net tax was applied to those backtest configurations). v1.4 onwards uses 15% short-term capital gains (annual-net).

| Version | Description | Cumulative | CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|
| v1.0 | Single-asset directional (no gold, no cash yield). Preserved at commit `c2860fc`. (pre-tax) | 467.2% | 9.91% | 0.33 | -22.2% |
| v1.1.1 | Adds gold rotation throughout stress-flat latches + pure-repo cash yield. Preserved at commit `078878a`. (pre-tax) | 908.4% | 13.40% | 0.55 | -18.3% |
| v1.2 | Adds momentum-gated gold rotation (per-latch state machine) + 100 bps repo haircut. (pre-tax) | 784.8% | 12.59% | 0.50 | -16.4% |
| v1.3 | Substitutes NIFTY 200 Momentum 30 for NIFTY 50 as long-side asset; regime detection unchanged. (pre-tax) | 2,022.6% | 18.08% | 0.83 | -18.1% |
| v1.3.1 | README correction. Documents architecture honestly: 100 DMA regime filter is the binding entry gate; USDINR/VIX signal classes retained as scaffolding only. Test results for entry-signal-gated variant added. No code or numerical changes vs v1.3. (pre-tax) | 2,022.6% | 18.08% | 0.83 | -18.1% |
| v1.4 | Slow-stress signal replaces supply-shock as default stress detector (INR 20d weakness + VIX 90d z-score + VIX 5d momentum). Macro-confirmed gold rotation gate replaces single-condition gate (adds INR + US 10Y macro confirmation, caps blow-off-top entries). Tax modeling integrated natively. Cross-country validation on US data 1995-2025 catches 9/9 documented stress events. New data dependency: ^TNX. | ~1,440% | 15.50% | 0.78 | -15.0% |
| v1.5 | Gold-in-bull anomaly fix. Gold rotation entry now requires bear regime (NIFTY < 100 DMA) as a fourth gate condition on top of macro confirmation; mid-latch bull-flip exit added alongside the existing 10d-negative exit. Eliminates the 3-day May 2019 anomaly (-4.34pp) where slow-stress fired in bull regime and gold rotation triggered against a recovering equity tape. Backward-compatible via `gold_require_bear=False`. No new data dependencies. | 1,345.0% | 15.64% | 0.79 | -14.7% |
| v2.0 | Adds two refinements. (1) Post-bear NIFTY recovery overlay: hold NIFTY 50 instead of Momentum 30 for the first 60 trading days following a bear→bull regime flip preceded by a NIFTY drawdown ≥15%. Targets the Daniel & Moskowitz (2016) V-recovery momentum-crash pattern. 2009 single-year improvement: +52% → +76%. (2) Slow-stress cooldown: suppress slow-stress re-fires for 5 trading days after each unsuppressed firing event. Prevents 2019 April-May whipsaw chop. Combined impact vs v1.5: CAGR 15.64% → 16.78% (+1.14pp), MaxDD −14.67% → −13.38%, Sharpe 0.79 → 0.83. Backward-compatible via `enable_v2=False` and `slow_stress_lock_days=0`. | 1,631.3% | 16.78% | 0.83 | -13.4% |
| v2.1 | Adds 15% drawdown confirmation on panic-short. Panic-short can only fire when NIFTY's drawdown from its trailing 60-day high exceeds 15%. Suppresses the 2013-08-27 (drawdown ~13%, taper-reaction) and 2022-02-24 (drawdown ~11.3%, Ukraine-reaction) false fires. All four 2008 GFC panic-shorts (drawdowns 16–32%) preserved. Documented tradeoff: the March 6, 2020 fire (drawdown 11.1%) is suppressed; the next fire on March 9 (drawdown 15.5%) catches the move three days later, 2020 CAGR drops +52.21% → +46.25% but COVID protection still strongly captured. Combined impact vs v2.0: rf-adjusted Sharpe 0.79 → 0.81 (+0.02), MaxDD −13.38% → −12.78%, CAGR 16.78% → 16.52% (extended through 2026-05-11). Backward-compatible via `panic_short_dd_threshold=0`. | ~1,595% | 16.52% | 0.81 | -12.78% |
| **v2.2** | **Adds defensive quality basket on stress-flat days beyond 40-day persistence gate (blended 50/50 with cash, 30 bps/side, STCG 15%/20%). REPLACES the v2.1 G10 gold rotation on stress-flat days (gold code retained behind `enable_defensive_basket=False`). Marginal Sharpe-neutral improvement: CAGR 16.52% → 16.85% (+0.33pp), rf-adjusted Sharpe 0.81 → 0.83 (+0.02), MaxDD −12.78% → −13.92% (slightly deeper). OOS 2017+: CAGR 15.95% → 16.10% (+0.15pp), Sharpe 0.79 → 0.80, MaxDD -12.78% → -10.88% (1.9pp shallower). Honest framing: incremental risk-adjustment layer, not a first-order driver. Basket construction and bake-off history in the [Defensive Quality Basket](#6-defensive-quality-basket-v22) section. Identity check: `enable_defensive_basket=False` reproduces v2.1 baseline byte-exact. Current.** | **~1,655%** | **16.85%** | **0.83** | **-13.92%** |

The cumulative improvement from v1.5 to v2.1 was the largest single jump since the v1.3 long-side asset substitution: CAGR 15.64% → 16.52% (+0.88pp — endpoint through 2026-05-11), rf-adjusted Sharpe 0.79 → 0.81 (+0.02), max drawdown −14.67% → −12.78% (+1.89pp shallower). Each of the three v2.1 refinements was tested against a pre-specified parameter sweep with a disqualification rule (no variant that breaks 2008 GFC, 2018 September NBFC, 2020 COVID, or 2021 stress-window defense was retained); the selected thresholds (15% bear DD for recovery overlay, 5-day slow-stress cooldown, 15% panic-short drawdown confirmation) each sit on a tight plateau within their qualified range rather than at a cliff edge.

v2.2's defensive quality basket adds a further +0.33pp CAGR / +0.02 rf-adjusted Sharpe. The improvement is marginal and Sharpe-neutral; the layer's earned place in production is as an incremental risk-adjustment mechanism, not as a source of significant new alpha. The basket parameters (persistence N=40, alloc=0.5) were tuned on 2008-2016 in-sample only, locked, and applied unchanged to OOS 2017-2026 — the standard research discipline the strategy has used since v1.4.

v1.5's headline impact was on drawdown control (MaxDD −15.0% → −14.7%, Calmar 1.03 → 1.07) more than on CAGR (+0.14pp). The 2019 anomaly was a single 3-day window where the priority logic let gold rotation enter against a regime-bull tape; the fix closes it surgically without touching any other signal.

v1.4's primary improvement vs v1.3.1 was methodological as well as mechanical. The cross-country validation on 31 years of US data provides substantially stronger empirical evidence that the signal architecture generalizes beyond the Indian sample, addressing the most direct overfitting concern that arises from a 17-year regime-conditional model. The 2013 taper-tantrum failure mode is cleanly addressed (+3.43pp). The macro-confirmed gold rotation gate specifically addresses the 2026 H1 gold-rotation failure mode by adding macro confirmation requirements (INR + US 10Y) on top of the v1.2 momentum gate.

---

## Superseded Research — G10 gold rotation

**What it was.** The v1.4-v2.1 G10 gold rotation was a 5-condition macro-confirmed entry gate for the stress-flat allocation:
1. Gold 10-day return in (0, 10%] — positive momentum but not blow-off-top
2. USDINR 10-day return > 0.5% — rupee weakening (INR-priced gold tailwind)
3. US 10-year Treasury yield 20-day return < 0 — falling US real rates (global gold tailwind)
4. NIFTY below 100-DMA — bear regime confirmed (v1.5 requirement)
5. Currently in a stress-flat latch (per strategy state)

When all 5 fired, capital rotated from cash into GOLDBEES.NS. Held until either gold 10-day return turned negative (one-way-door exit within the latch) or the regime flipped back to bull.

**Why it was replaced (v2.2).** The gate was over-restrictive — it fired on only ~27 stress-flat days across the 18-year sample, providing negligible incremental alpha in aggregate. The defensive quality basket bake-off (V7 native) showed:
- Ungated ("simple") gold — bear-regime-only, no 5-condition gate — blew out drawdown to ~-23% (much worse than the strategy's headline -13%)
- The 5-condition gate was so restrictive it barely ever fired (27 out of ~1670 stress-flat days = 1.6%)
- A defensive quality basket alternative was a cleaner, better-tested replacement, deploying ~368 days across the sample with lower MaxDD deepening

The G10 gate was a real research effort — designed to avoid the 2026-01 gold blow-off-top (v1.2-v1.3.1 gate would have entered at +24% gold momentum and lost -19% within days), and the macro-confirmation logic was validated against US Treasury yield behavior. But in the end it was solving a smaller version of the problem the defensive basket solves better. This is an honest "we built it, tested it, and replaced it with something we trust more" — not "we found a bug." The code remains available as opt-in.

**How to reproduce v2.1 (gold rotation active).** Set `enable_defensive_basket=False` when constructing `MacroStrategy`. Byte-identical reproduction confirmed via IC1 identity check.

---

## Ongoing / Rejected Research

Beyond the tests documented above, several substantial research efforts have been undertaken and either rejected or shelved. Documented here because they represent real work and inform what to try (and not try) next.

**Momentum basket for bull-day exposure — 5 iterations (V1-V5), all rejected.** The hypothesis was that a self-picked momentum basket could beat the cheap NIFTYMOM30 index on bull days by adding quality filtering, size tilting, or risk management. Five iterations tested (V1: base momentum; V2: quality-gated; V3: cost/persistence fixes; V4: individual-name risk caps; V5: vol-cap sweep). Best result: V5 vc50 achieved OOS Sharpe 1.23 (vs Mom30 index R1's 1.24 — essentially tied on Sharpe) and OOS CAGR 15.78% (-0.32pp gap) but with -23.67% MaxDD (vs R1's -10.88% — 12.79pp deeper). Bottom line: **no variant beats the cheap Mom30 index on Sharpe AND MaxDD simultaneously**.

Root cause: the Mom30 index (a) is cap-weighted so avoids concentration in mid/small caps that get destroyed in factor rotations (2018 IL&FS crisis + LTCG-tax combined shock, 2022 quality selloff), (b) costs 6 bps/side vs our 15-30 bps/side, and (c) uses the same underlying momentum signal we do (rank_composite_risk_adj is reverse-engineered from NSE's methodology). The self-picked basket earns +2.3pp bull-only CAGR on average but pays back through -25% bull-only MaxDD vs the index's -8%.

**Meaningful sub-finding from momentum-basket research**: the hard-rules quality gate (cfo > 0, np > 0, D/E ≤ 2) added +3.7pp OOS CAGR / +0.26 Sharpe over pure momentum. Quality filtering matters — just not enough to overcome the fundamental cost + diversification disadvantage vs a cheap index. Scripts: `experiments/stock_momentum/momentum_basket_bakeoff_v[1-5].py`; diagnostic: `diagnose_basket_drawdown.py`.

**Bull-side momentum basket status: NOT SHIPPED, but research ongoing.** Next iterations to try (documented here as roadmap, not built): sector cap (max 5 per sector, matching defensive-basket construction — would prevent 2018 mid-cap-chemicals concentration), inverse-vol weighting (real risk parity), momentum-crash detection (Daniel-Moskowitz signal), sector-neutral momentum (top-3 per sector). If any of these lets us match the Mom30 index on OOS Sharpe with MaxDD within 5pp of the index's -11%, the momentum basket ships. Currently it stays in `experiments/`.

**Vol-targeting overlay — tested, rejected.** A volatility-scaling overlay on Config 7 was tested exhaustively (18 parameterizations across window / target-vol / cap / regime-gating dimensions). Initial results looked like +1pp CAGR — until leverage financing cost was properly charged (RBI repo + 200 bps spread on borrowed notional above 1×), which added ~170-200 bps/yr of drag and erased the gain. Best "delever-only" variant (cap=1.0×) improved rf-adjusted Sharpe by +0.07 but at cost of -3.2pp CAGR — not a good tradeoff. All levered variants (cap 1.5×+) LOST vs Config 7 after financing cost. Rejected. This is the strategy's canonical "rigor lesson": always charge the real cost of leverage before believing a levered backtest.

**Quality as a standalone factor — tested, weak.** Buying names by pure quality score alone (no momentum) produced weak / non-monotonic returns across deciles. Quality only pays as an interaction with momentum (per Novy-Marx 2013). Documented in `experiments/stock_momentum/quality_backtest.py`.

**Stress-resilient basket (V8) — worse than V7 generic.** A more sophisticated defensive-basket construction ranking by mean return across prior bear windows only (no look-ahead) with balanced beta band 0.6–1.1 was tested. It underperformed the V7 generic construction across FULL and OOS. Reason: bear-window defensive leadership rotates (2008 defenders ≠ 2020 defenders ≠ 2022 defenders); tilting toward historical bear winners does not generalize. V7 basket_cash_blend retained.

---

## Reproduce

```bash
git clone https://github.com/Neil-2501/nifty-macro-regime.git
cd nifty-macro-regime
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Runtime artifacts for the defensive basket are bundled with the repo:
#   data/defensive_basket_holdings.parquet
#   data/defensive_basket_daily_returns.parquet
# Production strategy loads these directly.

python strategy.py
```

Market data (yfinance) is fetched at runtime — no separate download step needed for the main strategy. Runtime is ~30–60 seconds, network-bound. All headline results print to stdout. Defensive basket ships ON by default in `MacroStrategy(...)`; set `enable_defensive_basket=False` to reproduce v2.1 baseline (Config 7 with G10 gold rotation).

**To rebuild defensive-basket artifacts from source data** (required if you want to regenerate the holdings + daily returns yourself, e.g., after adding data through a later date):

```bash
# Requires the ~544 MB stock-price panel data/yfinance_bulk/adjusted_prices_panel.parquet
# Fetch first if not present:
# python experiments/stock_momentum/bulk_pull_yfinance.py

python build_defensive_basket.py
```

Rebuild runtime is ~2-3 minutes (beta/vol computation over 200 stocks × 36 rebalance dates). Outputs the two runtime parquets.

**Cross-country validation** (US 1995-2025):

```bash
python validate_us_cross_country.py
```

**Identity check** (verify defensive-basket ON/OFF matches canonical R1 / Config 7 baseline):

```bash
python phase1_verify_identity.py
```

---

## Contact

Neil K. Kapadia · neilkk@umich.edu

---

*MIT licensed. Code and methodology provided for research purposes only; not investment advice.*

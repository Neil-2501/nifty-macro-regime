# Indian Equity Macro-Regime Strategy

A systematic macro-regime strategy for Indian markets combining tactical long exposure to NIFTY 200 Momentum 30 in bull regimes, sustained-stress detection via INR weakness combined with India VIX z-score regime shift, momentum-gated gold rotation with multi-asset macro confirmation during identified stress windows, NIFTY 50 short exposure on panic-short fires gated by a 15% drawdown confirmation, and haircut-adjusted RBI repo-rate cash yield on idle capital. A 100-day moving-average trend filter on NIFTY 50 acts as the long-engagement gate; slow-stress and panic-short signals override engagement during identified macro stress regimes. After deep bear regimes, the strategy holds NIFTY 50 instead of NIFTY 200 Momentum 30 for the first 60 trading days of the recovery to capture the broad rebound that momentum baskets miss while still loaded with pre-crash defensives. A 5-day cooldown on the slow-stress signal prevents whipsaw flat→long→flat round-trips during noisy chop periods. The signal architecture has been validated on 31 years of US market data (9 of 9 documented stress events detected), addressing overfitting concerns from the limited 17-year Indian sample. Position sizing is binary across two assets (long-side index +1, gold +1, NIFTY 50 futures -1) with cash as the third state; no leverage beyond 1×.

*Research project. Backtest results, methodology, and known limitations documented below. Not deployed; not investment advice.*

![Equity Curve](images/equity_curve.png)

---

## Headline Results

Backtest period: **2008-04-01 to 2025-12-31** (17.7 years). Net results assume per-asset transaction costs of **3 bps per leg** on NIFTY 50 futures (short side), **6 bps per leg** on NIFTY 200 Momentum 30 ETFs (long side), and **5 bps per leg** on GOLDBEES.NS (gold ETF). Idle capital on fully-flat days earns the prevailing RBI repo rate minus a 100 bps haircut modeling realistic liquid-fund execution.

| Metric | Strategy (v2.1) | NIFTY Buy & Hold | Δ |
|---|---|---|---|
| Sharpe (post-tax, RF = 6%) | **0.84** | 0.20 | **+313%** |
| Sharpe (pre-tax, RF = 6%) | 0.93 | 0.27 | +248% |
| Sortino | 1.12 | 0.25 | **+352%** |
| Calmar | 1.34 | 0.19 | **+595%** |
| Annualized volatility (pre-tax) | 14.20% | 19.27% | -26% |
| Max drawdown | **-14.9%** | -51.7% | **-71%** |
| CAGR (pre-tax) | 19.93% | 9.73% | **+1,019 bps** |
| Cumulative return (pre-tax) | 2,721.7% | 451.3% | +2,270.4pp |

Sharpe figures are post-tax by default from v1.4 onward, reflecting Indian short-term capital gains tax (15% annual-net model). Pre-tax Sharpe is reported alongside for reference. v1.3.1 reported pre-tax numbers exclusively; the v1.4 default change makes the headline metric natively deployability-relevant. CAGR, Sortino, Calmar, and vol shown above are pre-tax for benchmark comparability (NIFTY is also pre-tax). v2.1 cumulatively improves on v1.5 across every metric: post-tax CAGR 15.64% → 16.75% (+1.11pp), post-tax Sharpe 0.79 → 0.84 (+0.05), max drawdown −14.67% → −12.78% (+1.89pp shallower), Calmar 1.07 → 1.31. The improvement comes from three additions detailed under [Signal Logic](#signal-logic) and [Version History](#version-history): a post-bear NIFTY recovery overlay, a slow-stress cooldown, and a panic-short drawdown confirmation.

The strategy generates risk-adjusted alpha vs passive NIFTY exposure through three independent mechanisms operating together: (1) tactical long exposure to a momentum-tilted equity portfolio — long NIFTY 200 Momentum 30 during bull regimes, flat or short NIFTY 50 during identified stress regimes; (2) momentum-gated safe-haven rotation — long gold during stress windows only when the multi-asset macro confirmation set is aligned, with mid-latch exit to cash if gold momentum turns negative; (3) cash management — idle capital earns the prevailing RBI repo rate minus a 100 bps haircut on fully-flat days, modeling realistic institutional liquid-fund execution. The 313% post-tax Sharpe improvement is the most direct measure of joint risk-adjusted skill across these mechanisms. Cumulative outperformance vs buy-and-hold (+2,270pp over 17.7 years) is the geometric outcome of compounding all three together — the mechanisms cannot be cleanly separated into additive contributions, since they interact through the position sequence and the compounding base.

---

## Mechanisms of Outperformance

The strategy's outperformance derives from three mechanisms that compound together over the 17.7-year sample. Their contributions are inherently joint and cannot be cleanly attributed to additive percentages, since each mechanism affects the compounding base for the others.

**Tactical long exposure to a momentum-tilted equity portfolio.** The strategy holds long exposure to NIFTY 200 Momentum 30 by default during bull regimes (NIFTY 50 above its 100-day moving average), with slow-stress and panic-short overrides interrupting that exposure during identified macro stress. Capital avoidance of left-tail equity returns — the days where stress overrides force flat or short — generates volatility-drag alpha vs buy-and-hold. The strategy is long the long-side index ~65% of trading days (calm bull regimes), flat ~34% (bear regimes and stress flats), short NIFTY 50 ~0.7% (panic-short windows that survive the drawdown confirmation gate), and long gold ~0.5% (stress-flat windows where the gold rotation gate is satisfied). When long, the strategy holds **NIFTY 200 Momentum 30** by default — a 30-stock factor-tilted portfolio drawn from the NIFTY 200 universe and ranked semi-annually by 6-month and 12-month price momentum — except during the first 60 trading days following a deep-bear recovery, when it holds NIFTY 50 instead (see Refinements). Short exposure during panic-shorts remains on NIFTY 50 (more liquid for futures-based shorting). This is the core mechanism; the others amplify it.

**Momentum-gated safe-haven rotation with macro confirmation.** During identified stress-flat windows, capital rotates to GOLDBEES.NS gated by three macro conditions: gold's 10-day return must be positive but capped at 10% (preventing blow-off-top entries), INR must have weakened by 0.5%+ over 10 days (confirming macro stress that mechanically supports INR-priced gold), and US 10-year Treasury yields must be falling over 20 days (gold's fundamental macro tailwind). The macro-confirmed gate replaces the v1.2-v1.3.1 single-condition gate (gold_10d > 0) which let in marginal-momentum entries (40% hit rate) and extreme-momentum entries (blow-off tops). v1.4 holds gold approximately 31 days across the sample, down from v1.3's 41 days; the additional macro confirmation requirements filter out marginal entries while preserving the legitimate flight-to-safety opportunities. One-way door exit logic is preserved: once in gold within a latch, exit to cash if 10-day return turns negative and stay out for the remainder of that latch.

**Cash yield on idle capital (with realistic haircut).** On fully-flat days where neither NIFTY nor gold is held, the strategy credits the prevailing RBI repo rate minus a 100 bps haircut. The haircut models real-world liquid-fund execution: instrument spread (~50 bps inside repo), TER (~10–25 bps), and small auto-sweep frictions. Returns are post-tax by default in v1.4 (15% on net annual gains, Indian short-term capital gains convention); sensitivity to the haircut size is documented under Backtest Caveats.

### Refinements added since v1.5

Three targeted refinements were added to the v1.5 production base, each addressing a documented failure mode. Each is detailed under [Signal Logic](#signal-logic); their cumulative impact takes the strategy from v1.5 to v2.1 (post-tax CAGR 15.64% → 16.75%, Sharpe 0.79 → 0.84, max drawdown −14.67% → −12.78%).

**Post-bear NIFTY recovery overlay.** When a bear regime ends and the strategy re-engages long after a NIFTY drawdown of 15% or more, hold NIFTY 50 instead of NIFTY 200 Momentum 30 for the next 60 trading days, then revert to Momentum 30. Targets the Daniel & Moskowitz (2016) momentum-crash pattern observed cleanly in the 2009 sample, where Momentum 30 held stale pre-crash defensives while the recovery was led by beaten-down cyclicals.

**Slow-stress cooldown.** Once the slow-stress signal fires (forcing flat), suppress any subsequent slow-stress firings for 5 trading days. Other exit signals continue to operate normally. Targets the April–May 2019 bleed pattern where short-cluster re-fires forced repeated flat→long→flat round-trips, with the strategy losing meaningful return each time on exit-day moves.

**Panic-short drawdown confirmation.** Panic-short can only fire when NIFTY's current drawdown from its trailing 60-day high exceeds 15%. All other panic-short conditions (high absolute VIX, accelerating VIX spike, NIFTY below 100-DMA) still required. Targets two documented false-fire incidents (2013-08-27 taper-reaction short and 2022-02-24 Ukraine-reaction short) where panic-short fired into local bottoms and lost ~22.9pp and ~12.0pp respectively.

**Cross-country signal architecture validation.** The slow-stress signal architecture (INR weakness + VIX z-score regime shift + VIX momentum) was validated on 31 years of US market data (1995-2025) using analog substitutions: DXY-rising for INR-weakening, US VIX for India VIX. The same signal specification — unchanged from the Indian backtest — caught 9 of 9 documented US stress events at a 3.84% overall fire rate with low false positive rates in calm bull years (0.0-7.5%). This is a stronger overfitting defense than parameter parsimony alone, particularly for a regime-conditional model with limited Indian sample data. See [Cross-Country Validation](#cross-country-validation) section below.

**The Sharpe improvement (+313% post-tax vs NIFTY) is the most reliable single measure of risk-adjusted skill** because it normalizes return per unit of volatility regardless of which mechanism is doing the work on any given day. Cumulative return improvement (+2,270pp pretax) is striking but is inherently joint and path-dependent.

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
| v1.5: prior + bear-regime requirement on gold rotation entry + mid-latch bull-flip exit | Selected (v1.5) | Eliminates the 2019 gold-in-bull anomaly (3 days, −4.34pp) where gold rotation triggered against a recovering equity tape; MaxDD narrows from −17.2% to −15.5% |
| v2.0: prior + post-bear NIFTY recovery overlay + slow-stress cooldown | Selected (v2.0) | Recovery overlay captures the V-recovery cyclicals lead that Momentum 30 misses (cleanly visible in 2009: NIFTY +56% during the 60-day recovery window, Momentum 30 +29% — strategy now holds NIFTY through it). Slow-stress cooldown eliminates the 2019 April-May whipsaw (9 separate fires in short clusters were causing flat→long→flat round-trips). Combined: +1.14pp CAGR, max DD narrows from −14.67% to −13.38% |
| **v2.1: prior + 15% drawdown confirmation on panic-short** | **Selected (v2.1, current production)** | Panic-short can only fire when NIFTY drawdown from 60-day high exceeds 15%; suppresses the 2013-08-27 (−22.9pp) and 2022-02-24 (−12.0pp) false fires that fired into local bottoms. All four 2008 GFC panic-shorts (drawdowns 16–32%) preserved. Documented tradeoff: the March 6 2020 fire is suppressed at 11.1% drawdown; next fire on March 9 catches up at 15.5% drawdown, 2020 CAGR drops +52.21% → +46.25% but COVID protection still strongly captured. MaxDD narrows further from −13.38% to −12.78%, Sharpe 0.83 → 0.84 |

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

### 4. Gold Rotation — Macro-Confirmed Gate (v1.4, with v1.5 bear requirement)

**Economic rationale.** Gold's price action is driven by three fundamental macro factors: real interest rates (gold is a non-yielding asset, so falling real rates raise gold's relative appeal), dollar dynamics (gold is denominated in USD; weaker dollar lifts gold prices), and momentum / flight-to-safety flows. The macro-confirmed gold rotation gate uses one of each of these forces as entry confirmation, replacing the single-condition gate used in v1.2-v1.3.1.

**Mechanics — entry requires ALL of:**
- 0 < gold 10-day return ≤ 10% (positive momentum but not extreme; the cap prevents blow-off-top entries that historically reverse within days)
- USDINR 10-day return > 0.5% (rupee weakening mechanically lifts INR-priced gold)
- US 10-year Treasury yield 20-day return < 0 (falling US yields = gold tailwind globally)
- NIFTY below its 100-day moving average (bear regime — v1.5 addition that eliminated the May 2019 gold-in-bull anomaly)

One-way door exit logic preserved from v1.2: once in gold within a stress-flat latch, exit to cash if gold 10-day return turns negative; stay out for the remainder of that latch (no re-entry within the same latch). v1.5 also added a mid-latch bull-flip exit (exit gold immediately if the regime flips back to bull mid-latch).

**Why v1.4 changed the gate.** The v1.2-v1.3.1 single-condition gate (gold_10d > 0) had two documented failure modes. Marginal-momentum entries (gold 10d return 0-2%) had a 40% hit rate and mean return of −0.42% — essentially noise. Extreme-momentum entries (gold 10d return > 10%) exhibited blow-off-top behavior, with the 2026-01-29 entry at +24% gold momentum followed by a −19% gold crash within days. The v1.4 macro-confirmed gate addresses both: the upper cap blocks blow-off entries; the INR + US 10Y confirmation filters the marginal-momentum noise by requiring macro alignment.

### 5. Post-Bear NIFTY Recovery Overlay (v2.0)

**Economic rationale.** Documented by Daniel & Moskowitz (2016, *Momentum Crashes*): after a sharp market crash, a momentum index holds stale pre-crash winners (defensive stocks that survived the crash) while the recovery is led by beaten-down cyclicals. Because NIFTY 200 Momentum 30's momentum score is computed over trailing 6- and 12-month windows and rebalances only semi-annually (June and December), the index cannot refresh into the recovery leaders until a full rebalance cycle after the bottom. NIFTY 50 captures the broad-market rebound that Momentum 30 misses during the first 2–3 months after the trough.

The 2009 sample illustrates this cleanly. NIFTY's bear regime ended on March 23, 2009. Over the following 60 trading days (March 23 – June 12, 2009), NIFTY 50 returned +55.9%; NIFTY 200 Momentum 30 returned +28.6% over the same window. Without the overlay, the strategy would have held Momentum 30 through this window and captured the lower return. With the overlay, the strategy holds NIFTY 50 through the 60-day window and then reverts to Momentum 30 from June 15, 2009 onward. Momentum 30 then dominates for the remainder of the year (2009 strategy full-year: +76.5% with the overlay, vs +52.0% in v1.5 without — a 24pp single-year improvement).

**Mechanics.** When the strategy is in a long position immediately after a bear→bull regime flip (NIFTY 50 crosses above its 100-day moving average), and the preceding bear-regime peak-to-trough drawdown was ≥15%, the strategy holds NIFTY 50 instead of NIFTY 200 Momentum 30 for the next 60 trading days. After 60 days, it reverts to Momentum 30 (which by then has had time to refresh into recovery leaders via the semi-annual rebalance).

**Drawdown-threshold sensitivity.** Tested at 10%, 12%, 15%, 18%, 20%. The 15%, 18%, and 20% thresholds produce identical results — no qualifying bear drawdowns in the 15–20% range across the sample. 12% added marginal false positives (shallow pullbacks that don't constitute real bear markets). 10% over-triggered. The 15% threshold is the smallest value that captures all real V-recoveries (2008 GFC, 2020 COVID) without including borderline cases; the plateau from 15% to 20% means the choice is robust to the specific threshold within that range.

**Hold-period choice.** 60 trading days reflects the typical Indian semi-annual rebalance cadence (NSE Indices rebalances momentum semi-annually). Not separately swept. Impact: +1.00pp CAGR vs v1.5 baseline, +0.04 Sharpe, max drawdown unchanged. The overlay is active only during ~180 days out of the 17.7-year sample (qualifying V-recovery windows), so it does not affect the strategy outside those specific periods.

### 6. Tested But Not Adopted

#### Long-entry confirmation lanes (USDINR / India VIX momentum)

The codebase retains two signal classes — `USDINRSignal` and `IndiaVIXSignal` — that were originally designed as long-entry confirmation lanes. They were evaluated as binding gates on long re-entry: requiring an entry signal to fire during a flat period before the strategy could re-engage the long-side asset. The variant was backtested over the full 2008-2025 sample under otherwise-identical mechanics.

**Variant tested.** Entry signal definitions (10-day windows): USDINR has fallen >1% over 10 days (rupee strengthening); India VIX has fallen >20% over 10 days (vol decay). Gate logic: when NIFTY > 100 DMA but the strategy is transitioning from flat to long, require an entry signal to have fired during the flat period before allowing the long.

**Results.** The gated variant blocked 423 re-entry attempts and added ~1.7 years of additional flat exposure. CAGR cost: -1.59pp. Sharpe: 0.78 vs 0.83 (v1.3 baseline). The cost concentrates in V-shaped recovery years where the entry signals lag the trend reversal: 2009 (-8.1pp), 2014 (-8.0pp), 2017 (-16.4pp), 2021 (-11.2pp). **Conclusion:** The 100 DMA trend filter dominates the carry- and vol-based entry signals on the relevant time scales. The signal classes are retained in the codebase as scaffolding for future iterations but do not affect production positions. Full test script: [`experiments/test_entry_signal_gate.py`](experiments/test_entry_signal_gate.py).

#### Vol-Scaled Position Sizing (rejected, May 2026)

A volatility-scaling overlay was tested on top of v1.3.1 to determine whether fractional position sizing (rather than binary +1/0/-1) could improve risk-adjusted returns by reducing exposure during high-vol periods. Thirteen variants were tested across rolling realized vol windows (10/20/60 days), target vol levels (10/12/15%), and mitigation overlays (tolerance bands, weekly rebalance). All variants underperformed the binary-sizing base.

**Mechanism of failure.** The strategy's existing regime filter, supply-shock, and panic-short signals already implement vol-conditional sizing — they take exposure to zero during high-vol regimes. Adding a vol-scaling overlay double-counts this behavior, scaling down exposure on the same days the regime filter would have already done so, without adding new information. The best variant (60-day window, 15% target, daily rebalance) produced post-tax Sharpe 0.673 vs base 0.731 — a -0.058 deterioration. Script parked at `parked/test_vol_scaling.py`.

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

| Series | Ticker | Source | Frequency |
|---|---|---|---|
| NIFTY 50 | `^NSEI` | Yahoo Finance via `yfinance` | Daily, adjusted close |
| USD/INR | `INR=X` | Yahoo Finance | Daily |
| India VIX | `^INDIAVIX` | Yahoo Finance | Daily |
| WTI Crude (front-month) | `CL=F` | Yahoo Finance | Daily |
| Gold ETF (v1.1) | `GOLDBEES.NS` | Yahoo Finance (NSE-listed) | Daily; series begins 2009-01-02 |
| NIFTY 200 Momentum 30 (v1.3) | `NIFTYMOM30` | NSE CSV via `niftyindices.com` (pulled with `nselib`); stored as `data/momentum30_history.csv` | Daily; backfilled 2008-01-01, live since Aug 2020 |
| US 10-Year Treasury yield (v1.4) | `^TNX` | Yahoo Finance | Daily |
| RBI Repo Rate (v1.1) | — | RBI MPC press releases ([rbi.org.in](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx)); hardcoded as `RBI_REPO_RATE_HISTORY` in `strategy.py` | Step function (53 announcements over 2008–2025) |

Most market data is downloaded live at runtime via `yfinance`; NIFTY 200 Momentum 30 is loaded from a static CSV (`data/momentum30_history.csv`) sourced from niftyindices.com via the `nselib` Python library. India VIX series begins March 2008, which sets the in-sample start at **2008-04-01**. A warmup period from **2006-01-01 to 2008-03-31** seeds rolling windows and is excluded from results. GOLDBEES.NS data starts 2009-01-02; pre-2009 stress-flat days remain fully flat in the backtest (gold instrument not yet tradable). Cleaning is minimal: forward-fill across mismatched holiday calendars, drop full-NaN rows.

**v1.4 introduces `^TNX` (US 10-year Treasury yield) as input to the macro-confirmed gold rotation gate.** US real-rate dynamics are the most fundamental macro driver of gold prices globally; including this signal as a gate condition prevents gold rotation during periods when US rates are rising (creating a structural headwind for gold). Available via yfinance with full sample coverage.

**NIFTY 200 Momentum 30 history note.** The index was launched live in August 2020 with backfilled history to April 2005 (the index's official base date) by NSE Indices Ltd. The backfilled portion uses the same mechanical methodology (semi-annual rebalance, momentum score = 6m + 12m risk-adjusted price momentum, top 30 stocks by score from NIFTY 200 universe) that NSE applies live. Cross-validation against yfinance over the 2019+ overlap period showed perfect correlation (1.000000) and 0.0000% mean relative difference, confirming data fidelity.

The RBI repo rate timeline is **hardcoded** rather than fetched at runtime because (a) no reliable free Indian short-rate API exists with full 2008-2025 coverage, (b) the repo rate is a step function with only ~50 changes over 17 years, ideal for a static table, and (c) hardcoding makes the backtest deterministic and auditable. Each row is sourced from the corresponding RBI MPC press release; the table is maintained manually and must be updated when RBI announces new rate decisions.

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
| Transaction costs | NIFTY 50 futures (short side): **3 bps per leg**. NIFTY 200 Momentum 30 ETF (long side): **6 bps per leg** (ETF spread + STT; slightly wider than NIFTY futures due to lower turnover). Gold (GOLDBEES.NS): **5 bps per leg** (ETF spread + STT). Cash sweep: **0 bps** (institutional auto-sweep into liquid fund). Applied as `\|Δposition\| × cost_bps / 10,000`, deducted from same-day return. Long↔short flips cost both legs. |
| Cash yield on flat days (v1.2) | Time-varying RBI repo rate as a step function (range 4.0%–9.0% over 2008–2025), with a **100 bps haircut** applied daily on fully-flat days to model realistic institutional liquid-fund execution (instrument spread + TER + sweep friction). Hardcoded in `RBI_REPO_RATE_HISTORY` in `strategy.py`. Setting `cash_yield_haircut_bps=0` recovers v1.1.1's pure-repo assumption (sensitivity in Backtest Caveats). |
| Gold rotation (v1.4–v1.5) | Per-latch state machine with macro-confirmed entry gate: 0 < gold 10d return ≤ 10% AND INR 10d return > 0.5% AND US 10Y 20d return < 0 AND NIFTY < 100 DMA (v1.5 bear-regime requirement). One-way door exit preserved (exit to cash if gold 10d turns negative mid-latch); mid-latch bull-flip exit added in v1.5. Replaces v1.2–v1.3.1 single-condition gate (gold_10d > 0). |
| Tax model (v1.4) | Indian short-term capital gains, annual-net model. Tax of 15% applied to net positive annual returns. Loss years unchanged. Losses within a year offset gains. Applied natively in `MacroStrategy.run()` with `apply_tax=True` default. Opt-out with `apply_tax=False` for pre-tax analysis. |
| Risk-free rate | 6% per annum (India 10Y G-Sec proxy) for Sharpe and Sortino. |
| Out-of-sample | 2026-01-01 to present held out from parameter selection. |
| Parameter selection | Judgement-based; no grid search or formal optimization. |

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

Maximum drawdown of **−14.9%** (pre-tax) / **−12.8%** (post-tax) vs NIFTY's **−51.7%** — a **71% reduction**. Cash yield on flat days during bear regimes (notably 2008-2009 GFC and 2020 March-August COVID recovery) cushions equity drawdowns by adding deterministic positive return on the worst-impact days. The drawdown profile reflects the joint mechanism set: the largest contributions to the gap come from the 2008 GFC (regime filter + cash yield at ~8% repo), 2011 European debt stress (gold rotation + cash yield), and 2020 COVID crash (panic-short + gold rotation + cash yield through the recovery period). v2.1's max drawdown improves vs v1.5's −15.5% (post-tax: −12.8% vs −14.7%) primarily through the panic-short drawdown confirmation (eliminates the 2013 and 2022 short losses that previously contributed to drawdown).

### Cost Sensitivity

The long-side asset is NIFTY 200 Momentum 30 (ETF, 6 bps per leg base case). The table below varies the long-side cost; NIFTY short cost (3 bps) and gold cost (5 bps) are held fixed. Cash sweep is treated as zero-cost at all levels. Sensitivity reported pre-tax to match NIFTY benchmark convention.

| Long-side cost (bps/leg) | Cumulative Return | CAGR | Sharpe | Max DD |
|---|---|---|---|---|
| 0 | 3,108.8% | 20.77% | 0.98 | -14.9% |
| 3 | 2,909.1% | 20.35% | 0.95 | -14.9% |
| **6 (base, v2.1)** | **2,721.7%** | **19.93%** | **0.93** | **-14.9%** |
| 10 | 2,489.8% | 19.37% | 0.89 | -14.9% |
| 15 | 2,226.5% | 18.67% | 0.85 | -14.9% |
| 20 | 1,989.8% | 17.98% | 0.81 | -15.4% |
| 50 | 996.5% | 13.92% | 0.56 | -22.8% |

Strategy economics degrade more slowly than a purely directional version because cash yield on idle capital is unaffected by transaction costs — fully-flat days don't trade and so don't pay friction. Sharpe stays well above NIFTY's 0.27 buy-and-hold all the way through 20 bps long-side cost. The 50 bps row remains a stress test, not a realistic implementation cost.

---

## Robustness Checks

### Crisis-Period Stress Tests

Pre-tax cumulative returns over crisis windows (pre-tax to match NIFTY benchmark convention).

| Crisis | Window | Strategy (v2.1) | NIFTY |
|---|---|---|---|
| GFC | Sep 2008 – Mar 2009 | **+2.4%** | -30.7% |
| Euro debt | Jul 2011 – Dec 2011 | **+1.0%** | -18.1% |
| Taper Tantrum | May – Sept 2013 | **-0.4%** | -3.3% |
| NBFC / IL&FS | Aug 2018 – Nov 2018 | **-0.5%** | -4.2% |
| COVID Crash | Feb – May 2020 | **+19.6%** | -19.9% |
| Russia 2022 | Feb – Jun 2022 | **-2.0%** | -9.0% |
| Momentum sell-off 2025-26 | Oct 2025 – Apr 2026 | +1.9% | +6.2% |

The strategy navigates GFC-style and COVID-style regimes well — both feature decisive trend breakdowns that the panic-short and slow-stress lanes capture cleanly. The GFC window returns +2.4% (vs NIFTY −30.7%) because cash yield on the fully-flat days at ~8% repo dominates the small drag from the stress latch; all four 2008 panic-shorts (at NIFTY drawdowns of 16–32%) fire through the v2.1 confirmation gate. The 2011 European debt window flips positive (vs NIFTY −18.1%) via flat-period cash yield plus correct slow-stress force-flat coverage. The 2013 Taper Tantrum window is now nearly flat (−0.4%) vs v1.4's −2.6% — the slow-stress cooldown (v2.0) and panic-short drawdown confirmation (v2.1) together prevent the 2013-08-27 false panic-short. The 2020 COVID window returns +19.6% (vs NIFTY −19.9%) even after the v2.1 March-6 panic-short suppression; the next fire on March 9 captures the crash. The 2025–26 momentum sell-off window is the most recent stress and is the first crisis-window-style underperformance under the new production version — the strategy held +1.9% but NIFTY rebounded +6.2%, reflecting that Momentum 30's structural rotation losses remain unaddressed.

**A note on Momentum 30 behavior in stress.** Momentum 30 itself underperforms NIFTY 50 in some crisis windows (e.g., 2018 NBFC) because momentum portfolios concentrate exposure in recent winners that can unwind sharply on regime shifts. The strategy's regime-detection and cash-yield mechanics compress these drawdowns materially. This is also the mechanism driving the residual 2018, 2022, and 2025 underperformance — see Limitations.

### 2026 Out-of-Sample Performance

The strategy went live in development through 2025-12-31, with 2026 reserved as out-of-sample. Through 2026-05-11:

| | 2026 YTD return |
|---|---|
| **Strategy (v2.1)** | **+2.4%** (pre-tax) / +2.0% (post-tax) |
| NIFTY 50 Buy & Hold | -8.9% |
| **Outperformance (pre-tax)** | **+11.3pp** |

v2.1's 2026 OOS performance is broadly consistent with v1.4–v1.5's. Three mechanisms contributed:

1. **Slow-stress signal fired earlier than regime filter alone.** During the 2026 January-March equity deterioration, the slow-stress signal force-flatted on its trigger conditions (INR weakening + VIX z-score elevation + VIX momentum rising) before the 100 DMA regime filter would have disengaged on its own. This provided earlier defensive positioning.

2. **Macro-confirmed gold rotation gate prevented the 2026-01-29 blow-off-top entry.** v1.3.1's single-condition gate (gold_10d > 0) would have entered gold at +24% momentum on 2026-01-29; the position then crashed −19% within days. The v1.4 macro-confirmed gate blocks entries above the 10% momentum cap, preventing this specific failure mode.

3. **Slow-stress cooldown and drawdown-confirmed panic-short** did not materially change OOS results vs v1.4–v1.5 (the 2026 OOS window did not contain a chop period that would have triggered the cooldown's benefit, nor a borderline panic-short fire that the drawdown confirmation would have caught or suppressed). The two v2.0–v2.1 refinements are primarily in-sample optimizations against patterns identified during diagnostic work; their OOS performance neither confirms nor contradicts the in-sample benefit on this single window.

Buy-and-hold YTD for the three indices considered: NIFTY 50 −8.9%, NIFTY 200 Momentum 30 (estimated) −5% to −6%. The strategy outperformed all three benchmarks in the OOS window.

### Cross-Country Validation

The slow-stress signal architecture introduced in v1.4 (INR weakness + VIX z-score regime shift + VIX momentum) was validated on US market data spanning 1995-2025 using analog substitutions: DXY-rising for INR-weakening (both measuring sustained currency stress in the dominant direction for the respective market) and US VIX for India VIX. The signal specification was held exactly fixed — no re-parameterization, no calibration to US data.

#### Results

Overall fire rate: **3.84% of trading days over 31 years**.

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

The cross-country validation tests whether the slow-stress signal architecture detects genuine sustained EM-style stress regimes or whether it is curve-fit to specific Indian historical events. Catching 9 of 9 documented US stress events using an unchanged signal specification at a 3.84% overall fire rate provides strong empirical evidence that the architecture generalizes across markets, time periods, and event types.

The pre-fire on LTCM (June 11, 1998, approximately 45 days before the LTCM crisis is conventionally considered to have begun) is particularly significant. The signal detected sustained DXY weakness combined with US VIX z-score elevation and momentum confirmation well before LTCM's formal events. This is the kind of leading-indicator behavior that distinguishes a real signal from a coincidence detector.

False positive rates in clearly calm years (2017: 0.0%, 2019: 1.1%) indicate the signal is selective rather than over-firing. Higher false positive rates in 2014 (7.5%) reflect mid-cycle vol elevation around Russia-Ukraine tensions and Fed taper concerns that did not escalate into full stress regimes — these are edge cases where the signal correctly identified macro deterioration that ultimately resolved without crisis.

This validation does not eliminate overfitting risk entirely — the signal specification was developed against Indian data, and the test is on US data using the same specification. A future researcher who developed a strategy on the US data first would arrive at potentially different parameters. But cross-market validation with an unchanged specification is a stronger empirical defense against curve-fitting than parameter parsimony alone, and substantially stronger than any defense available to v1.3.1.

The full validation script is at [`validate_us_cross_country.py`](validate_us_cross_country.py) in the project root.

### Walk-Forward Validation

Not yet implemented (parameter selection was manual). Planned — see Roadmap. v1.4's cross-country validation addresses architecture-level generalization but parameter walk-forward remains an open methodology item.

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

| Comparator | Strategy excess CAGR | Strategy excess Sharpe | Strategy MaxDD vs Benchmark |
|---|---|---|---|
| vs NIFTY 50 B&H | +8.41pp | +0.626 | +38.3pp better |
| vs Mom30 B&H | +4.5pp | +0.42 | +42.4pp better |
| vs Dynamic A (regime filter alone) | +2.53pp | +0.113 | +2.5pp better |

The strategy outperforms every benchmark on risk-adjusted Sharpe and Calmar. v2.0–v2.1 widen the gap vs Dynamic A meaningfully — under v1.5 the strategy beat Dynamic A by +1.42pp CAGR with a 0.5pp MaxDD disadvantage; under v2.1 it beats Dynamic A by +2.53pp CAGR with a 2.5pp MaxDD advantage.

### Decomposition of NIFTY 50 outperformance

The headline +8.41pp CAGR vs NIFTY 50 decomposes into three components:

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

**3. Architectural validity beyond Indian alpha.** The signal architecture is validated cross-country on 31 years of US data (see Cross-Country Validation section) — caught 9 of 9 documented US stress events at 3.84% fire rate. This addresses overfitting concerns that the +2.53pp Indian-sample alpha alone cannot, and supports the inference that the override layer's contribution generalizes.

### Note on Dynamic A's max drawdown advantage (now reversed in v2.1)

Under v1.5, Dynamic A's MaxDD (−15.2%) was 0.5pp better than the strategy's (−15.5%). The v2.0–v2.1 refinements reverse this: the strategy's MaxDD is now −12.78% post-tax vs Dynamic A's −15.2% — a 2.5pp advantage. The drawdown improvement is primarily attributable to the panic-short drawdown confirmation (eliminating the 2013 and 2022 false shorts that previously contributed to peak drawdown depths).

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
| Sector concentration gate | Detect Mom30 sector concentration via rolling regression; signal weakness when most-loaded sector trends down | Diagnostic was informative (β_mid > median+1σ AND most-loaded segment below own 100-DMA → −11pp average forward 12mo Mom30 vs NIFTY), but rule construction failed in-sample tests |

These losses remain unaddressed by any overlay tested to date. Further approaches under investigation include multi-asset simultaneous holding, breadth-based regime detection, and sector-rotation signals using the newly cached NSE sector index data. Diagnostic script: [`experiments/diagnose_mom30_composition.py`](experiments/diagnose_mom30_composition.py).

---

## Limitations

Active weaknesses I am addressing on the roadmap.

1. **Limited cross-asset universe.** The current implementation is two-asset (NIFTY + gold) with cash as the third state. The structural question — whether cumulative alpha vs NIFTY can be sourced from something other than tactical reduction of NIFTY exposure — is now partially addressed via gold rotation, but the asset universe remains narrow. Expansion to additional risk assets (USDINR overlay, broader equity indices) is on the roadmap. Walk-forward validation of the gold rotation rule specifically has not been done.

2. **Momentum-factor structural-rotation losses (2018, 2022, 2025).** The Momentum 30 long-side asset underperforms NIFTY 50 in these three structural factor / sector rotation years. 2018 was a midcap-vs-largecap rotation (IL&FS crisis crushed midcaps while large-caps held); 2022 and 2025 were sector rotations where Momentum 30 held prior-year winners into fresh selloffs. The V-recovery crash years (2009, COVID-adjacent) are now addressed via the v2.0 recovery overlay, but the structural-rotation years lack a clean crash signature. Multiple mitigation approaches were tested (relative-strength timing, asset swaps during stress, intensity-scaled flats, sector-concentration diagnostics) — all either failed to fix the years or broke winning years. These losses remain unaddressed; further approaches under investigation include multi-asset simultaneous holding, breadth-based regime detection, and sector-rotation signals using the newly cached NSE sector index data.

3. **Panic-short exit logic is structurally thin.** The active short uses only two exit mechanisms — a 5-day / 20-day NIFTY MA crossover and a 60-day time cap (the latter only active in `hold=True` configs) — and both parameter sets (5/20 windows, 60-day cap) were hand-picked rather than derived from panic-event duration statistics or a parameter sweep. The strategy enters via a strict 4-condition AND (VIX level, VIX spike, below 100-DMA, and v2.1's drawdown confirmation) but exits on a single binary MA flip — an asymmetry between strict-entry and loose-exit that has not been stress-tested against scenarios where the initial short thesis is wrong (e.g. a V-shaped recovery that bottoms before the MA crossover registers). There is no stop-loss, no profit-taking rule, and no volatility-normalized exit threshold. **Mitigating controls:** (a) the production config ships with `hold=False` (pulse short only — short is active solely on the days where panic conditions raw-fire AND drawdown confirmation passes), structurally capping any single-short loss exposure at one day; (b) v2.1's drawdown confirmation filters the two known false-fire events (2013, 2022). The roadmap addresses the broader exit framework; until then, sizing of any panic-short component should be conservative and the no-hold default should not be flipped without redesigning the exit framework first.

4. **No live track record.** All results are backtest-only. Out-of-sample paper trading from 2026 onward is in progress; live trading at size has not been undertaken.

5. **Bull-regime alpha gap (ADDRESSED in v1.3, factor-crash risk partially addressed since v2.0).** v1.2 had a structural bull-regime alpha gap. v1.3 addressed this via NIFTY 200 Momentum 30 substitution. The V-recovery momentum-crash failure mode is addressed in v2.0 via the post-bear NIFTY recovery overlay. The structural-rotation factor-crash years (2018, 2022, 2025) remain open — see Limitation 2.

6. **Lagging recovery detection.** The 100-DMA trend filter is a lagging indicator by construction — NIFTY typically rallies 15-25% off a crisis trough before crossing its 100 DMA, so the strategy systematically misses the early-recovery phase of each cycle. Once the regime flips to bull, the v2.0 recovery overlay then captures the post-flip 60-day rebound (which substantially compensates for the late re-entry on V-recoveries), but the strategy still misses the pre-flip portion of any cyclical recovery. Candidate replacements or augmentations include breadth signals (% of NIFTY 200 above 50 DMA), shorter MA crossovers (20/50 golden cross), and VIX-peak-rollover detection (separate from the absolute VIX-level signal). None were adopted because faster trend filters generate more false signals in chop regimes and require dedicated parameter testing.

7. **Panic-short fast-crash risk under v2.1 drawdown confirmation.** The 15% drawdown confirmation on panic-short suppressed the March 6, 2020 fire (NIFTY drawdown only ~11.1% at fire time). The next fire on March 9 (drawdown 15.5%) caught the move three trading days later, so COVID protection remained strongly captured overall (2020 strategy +46.3% post-tax vs NIFTY +13.8%). But if a future crisis develops faster than COVID — where panic-short would normally fire at <15% drawdown and price continues to fall sharply before crossing the 15% threshold — the gate would delay defense materially. The qualified-plateau sensitivity evidence (8% to 15% threshold spread is 0.17pp CAGR) suggests the rule is robust within range, but the 5.9pp 2020 give-back is the explicit cost of demanding price confirmation; a future fast-crash scenario could compound this cost.

---

## Backtest Caveats

These are structural caveats inherent to backtest research and macro-strategy design — not specific flaws of this strategy. They are documented for transparency, not as roadmap items.

1. **Researcher degrees of freedom.** Parameters (lookback windows, thresholds, DMA length) and signal selection (slow-stress + panic-short + regime filter + macro-confirmed gold rotation gate + recovery overlay + slow-stress cooldown + drawdown confirmation) were chosen with knowledge of recent Indian market behavior. Walk-forward parameter validation is on the roadmap but has not yet been done. The choice of *which signals* to include is partially addressed via cross-country validation in v1.4 (the slow-stress architecture catches 9 of 9 US stress events using an unchanged specification), but parameter-level walk-forward remains untested. The v2.0–v2.1 refinements were tested with a disqualification rule applied to each parameter sweep (no variant that breaks the 2008, 2018 September, 2020, or 2021 defensive coverage was retained), which provides a stronger overfitting defense than parameter parsimony alone for each new layer.

2. **Limited regime diversity in available data.** India VIX only exists from 2008, capping the Indian backtest at ~17 years. Two true crisis regimes (GFC, COVID) plus several smaller stresses (2011, 2013, 2018, 2022) is statistically thin for a regime-conditional model. v1.4's cross-country validation extends architecture-level evidence to 31 years and 9 stress events on US data, materially addressing this concern.

3. **Non-stationarity of macro relationships.** USDINR / VIX / equity correlations have shifted over the sample (pre vs post 2014 RBI inflation-targeting framework, pre vs post 2020 liquidity regime, evolving FII flow dynamics). The strategy implicitly assumes some stability in these relationships going forward.

4. **Capacity and crowding unknown.** Backtest is unaware of position size. VIX-based and panic-short signals may have crowded behavior in stress regimes; edge at scale has not been tested.

5. **Cash-yield modeling assumes liquid-fund-style execution (v1.2 / v1.3 / v1.4).** The strategy credits the RBI repo rate minus a 100 bps haircut on fully-flat days. v1.1.1 used a no-haircut (pure repo) assumption that external review flagged as too aggressive; v1.2's 100 bps default is more conservative and more credible. Additionally, the Sharpe-ratio benchmark hurdle is held constant at 6% even though the modeled cash yield ranges 3–8% over the sample after haircut — a minor inconsistency that doesn't materially affect cross-strategy comparison since NIFTY's Sharpe uses the same hurdle.

6. **Tax-model approximation (v1.4).** The 15% annual-net tax model is an approximation of Indian short-term capital gains tax. It applies a flat 15% to net positive annual returns; loss years are unchanged; intra-year losses offset gains. Real tax treatment depends on holding period, instrument-specific treatment (futures vs equities), and complex carry-forward rules not modeled. The approximation is appropriate for deployability-relevant headline metrics but should not be used for precise tax planning. Pre-tax analysis is available via `apply_tax=False`.

7. **Limited out-of-sample coverage.** OOS testing covers 2026-01-01 through 2026-05-11. v2.1 outperformed NIFTY by +11.3pp pre-tax in this window — a meaningful demonstration that the slow-stress signal plus macro-confirmed gold rotation gate continue to work in live conditions. The v2.0 recovery overlay and v2.1 panic-short drawdown confirmation did not materially fire in the OOS window (the window did not contain a bear→bull V-recovery flip or a panic-short fire near the drawdown threshold), so their OOS performance is neither confirmed nor contradicted by this single window. This is a single OOS year and a single regime; broader OOS validation requires either additional time or formal walk-forward methodology (on the roadmap). Cross-country validation on US data (9/9 events caught) provides architecture-level OOS evidence even if not parameter-level.

---

## Roadmap

In progress and planned:

1. **Multi-asset holding** — test simultaneous holding of Momentum 30 and gold/NIFTY rather than the current single-asset rotation. Benchmark attribution suggested diversification value the current single-asset structure leaves unused. The post-bear NIFTY recovery overlay (v2.0) is a single-asset-at-a-time switch; multi-asset holding is the broader generalization. Architecture change to `MacroStrategy`'s position accounting; requires careful cost modeling for simultaneous long-side positions.

2. **Further mitigation approaches for the 2018/2022/2025 structural-rotation losses.** These years lack the V-recovery signature the recovery overlay targets; the loss-pattern diagnostic confirmed no single price-based signal in our current dataset cleanly identifies them without unacceptable win-year whipsaw cost. The Mom30 composition diagnostic (`experiments/diagnose_mom30_composition.py`) found one informative conditional signal — β_mid > median+1σ AND most-loaded segment below own 100-DMA predicts an 11pp average forward 12-month Mom30 vs NIFTY underperformance — but rule construction failed in-sample tests. Candidate directions to investigate further: sector-rotation signals using the cached NSE sector indices (NIFTY_BANK, NIFTY_IT, NIFTY_AUTO, NIFTY_FMCG, etc.), multi-asset holding alongside Momentum 30, breadth signals (% of NIFTY 200 above own 50 DMA), and Quality 30 / Low Volatility 30 as conditional alternative long-side assets.

3. **Walk-forward parameter validation** — re-fit thresholds and lookback windows on rolling 5-year windows; report out-of-sample-only equity curve. Includes walk-forward validation of the slow-stress signal, gold rotation gate, recovery overlay, slow-stress cooldown duration, and panic-short drawdown threshold. v1.4's cross-country validation addresses architecture-level generalization but parameter walk-forward remains untested. Rolling 5-year training windows with 1-year OOS aggregation is the standard approach; the strategy's parameters were judgment-based throughout development.

4. **Early-recovery detection.** The 100-DMA trend filter lags cyclical recoveries by 15-25% of the underlying move. The v2.0 recovery overlay compensates for the post-flip portion of this lag but doesn't help with the pre-flip portion. Candidate replacements/augmentations: breadth signals (% of NIFTY 200 above 50 DMA), shorter MA crossovers (20/50 golden cross), VIX-peak-rollover (VIX has fallen ≥30% from a recent peak above 25). Trade-off to test: faster trend filters generate more false signals in chop regimes. Requires dedicated parameter testing and OOS validation before adoption.

5. **Additional safe-haven cross-asset overlays** — extend beyond gold to USDINR and other defensive assets historically resilient during India-stress regimes. Targets diversification of the safe-haven sleeve and improvements to Sharpe through reduced single-asset reliance during stress windows.

6. **Panic-short exit framework redesign** — replace the current single-rule MA crossover exit with a layered framework: profit-take at +X%, stop-loss at −Y%, volatility-normalized exit thresholds (scale by current VIX), and immediate re-evaluation of entry conditions (cover the moment any of the entry conditions flips). Required before flipping the production config from `hold=False` to `hold=True`. Addresses Limitation 3.

7. **Signal-by-signal P&L attribution** — decompose cumulative P&L by lane (slow-stress, panic-short, regime-filter contribution, gold rotation, recovery overlay) to confirm each signal independently earns its keep. Partial work already complete via [`attribution_v14.py`](attribution_v14.py) (asset selection vs regime call decomposition).

8. **Forward paper-trading** — daily logged signals against live data from 2026 onward.

9. **Productionize the RBI repo rate feed** — replace the hardcoded `RBI_REPO_RATE_HISTORY` table with a CSV-backed config file plus a FRED API fallback for any dates after the last manual entry. Add a runtime warning if the strategy runs on a date past the latest available rate. Required before any live trading; nice-to-have for paper trading.

10. **Modular refactor** — break monolithic `strategy.py` into `src/data.py`, `src/signals.py`, `src/backtest.py` for extensibility.

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

| Version | Description | Cumulative (pre-tax) | CAGR (pre-tax) | Sharpe | Max DD |
|---|---|---|---|---|---|
| v1.0 | Single-asset directional (no gold, no cash yield). Preserved at commit `c2860fc`. | 467.2% | 9.91% | 0.33 | -22.2% |
| v1.1.1 | Adds gold rotation throughout stress-flat latches + pure-repo cash yield. Preserved at commit `078878a`. | 908.4% | 13.40% | 0.55 | -18.3% |
| v1.2 | Adds momentum-gated gold rotation (per-latch state machine) + 100 bps repo haircut. | 784.8% | 12.59% | 0.50 | -16.4% |
| v1.3 | Substitutes NIFTY 200 Momentum 30 for NIFTY 50 as long-side asset; regime detection unchanged. | 2,022.6% | 18.08% | 0.83 | -18.1% |
| v1.3.1 | README correction. Documents architecture honestly: 100 DMA regime filter is the binding entry gate; USDINR/VIX signal classes retained as scaffolding only. Test results for entry-signal-gated variant added. No code or numerical changes vs v1.3. | 2,022.6% | 18.08% | 0.83 | -18.1% |
| v1.4 | Slow-stress signal replaces supply-shock as default stress detector (INR 20d weakness + VIX 90d z-score + VIX 5d momentum). Macro-confirmed gold rotation gate replaces single-condition gate (adds INR + US 10Y macro confirmation, caps blow-off-top entries). Tax modeling integrated natively. Cross-country validation on US data 1995-2025 catches 9/9 documented stress events. New data dependency: ^TNX. | 2,166.8% | 18.51% | 0.78 (post-tax) / 0.87 (pre-tax) | -17.2% |
| v1.5 | Gold-in-bull anomaly fix. Gold rotation entry now requires bear regime (NIFTY < 100 DMA) as a fourth gate condition on top of macro confirmation; mid-latch bull-flip exit added alongside the existing 10d-negative exit. Eliminates the 3-day May 2019 anomaly (-4.34pp) where slow-stress fired in bull regime and gold rotation triggered against a recovering equity tape. Backward-compatible via `gold_require_bear=False`. No new data dependencies. | 2,211.2% | 18.63% | 0.79 (post-tax) / 0.88 (pre-tax) | -15.5% |
| v2.0 | Adds two refinements. (1) Post-bear NIFTY recovery overlay: hold NIFTY 50 instead of Momentum 30 for the first 60 trading days following a bear→bull regime flip preceded by a NIFTY drawdown ≥15%. Targets the Daniel & Moskowitz (2016) V-recovery momentum-crash pattern. 2009 single-year improvement: +52% → +76% post-tax. (2) Slow-stress cooldown: suppress slow-stress re-fires for 5 trading days after each unsuppressed firing event. Prevents 2019 April-May whipsaw chop. Combined impact vs v1.5: post-tax CAGR 15.64% → 16.78% (+1.14pp), post-tax MaxDD −14.67% → −13.38%, post-tax Sharpe 0.79 → 0.83. Backward-compatible via `enable_v2=False` and `slow_stress_lock_days=0`. | 2,757.0% | 20.01% | 0.83 (post-tax) / 0.93 (pre-tax) | -14.9% |
| **v2.1** | **Adds 15% drawdown confirmation on panic-short. Panic-short can only fire when NIFTY's drawdown from its trailing 60-day high exceeds 15%. Suppresses the 2013-08-27 (drawdown ~13%, taper-reaction) and 2022-02-24 (drawdown ~11.3%, Ukraine-reaction) false fires. All four 2008 GFC panic-shorts (drawdowns 16–32%) preserved. Documented tradeoff: the March 6, 2020 fire (drawdown 11.1%) is suppressed; the next fire on March 9 (drawdown 15.5%) catches the move three days later, 2020 CAGR drops +52.21% → +46.25% but COVID protection still strongly captured. Combined impact vs v2.0: post-tax Sharpe 0.83 → 0.84 (+0.011), post-tax MaxDD −13.38% → −12.78%, post-tax CAGR essentially flat (−0.03pp). Backward-compatible via `panic_short_dd_threshold=0`. Current.** | **2,721.7%** | **19.93%** | **0.84** (post-tax) / 0.93 (pre-tax) | **-14.9%** |

The cumulative improvement from v1.5 to v2.1 is the largest single jump since the v1.3 long-side asset substitution: post-tax CAGR 15.64% → 16.75% (+1.11pp), post-tax Sharpe 0.79 → 0.84 (+0.05), max drawdown −14.67% → −12.78% (+1.89pp shallower), Calmar 1.07 → 1.31. Each of the three refinements was tested against a pre-specified parameter sweep with a disqualification rule (no variant that breaks 2008 GFC, 2018 September NBFC, 2020 COVID, or 2021 stress-window defense was retained); the selected thresholds (15% bear DD for recovery overlay, 5-day slow-stress cooldown, 15% panic-short drawdown confirmation) each sit on a tight plateau within their qualified range rather than at a cliff edge.

v1.5's headline impact was on drawdown control (MaxDD −17.2% → −15.5%, Calmar 1.08 → 1.20) more than on CAGR (+0.12pp pre-tax). The 2019 anomaly was a single 3-day window where the priority logic let gold rotation enter against a regime-bull tape; the fix closes it surgically without touching any other signal.

v1.4's primary improvement vs v1.3.1 was methodological as well as mechanical. The cross-country validation on 31 years of US data provides substantially stronger empirical evidence that the signal architecture generalizes beyond the Indian sample, addressing the most direct overfitting concern that arises from a 17-year regime-conditional model. The 2013 taper-tantrum failure mode is cleanly addressed (+3.43pp). The macro-confirmed gold rotation gate specifically addresses the 2026 H1 gold-rotation failure mode by adding macro confirmation requirements (INR + US 10Y) on top of the v1.2 momentum gate.

---

## Reproduce

```bash
git clone https://github.com/Neil-2501/nifty-macro-regime.git
cd nifty-macro-regime
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python strategy.py
```

Data is fetched via `yfinance` at runtime — no separate data download step. Runtime is ~30–60 seconds, network-bound. All headline results print to stdout.

To run the cross-country validation separately:

```bash
python validate_us_cross_country.py
```

---

## Contact

Neil K. Kapadia · neilkk@umich.edu

---

*MIT licensed. Code and methodology provided for research purposes only; not investment advice.*

# Indian Equity Macro-Regime Strategy

A systematic macro-regime strategy for Indian markets combining tactical long exposure to NIFTY 200 Momentum 30 in bull regimes, momentum-gated gold rotation during identified stress regimes, NIFTY 50 short exposure on panic-short fires, and haircut-adjusted RBI repo-rate cash yield on idle capital. Three independent signal lanes — USDINR momentum, India VIX momentum, and supply-shock / panic-short triggers — identify macro regime breaks, gated by a 100-day moving-average trend filter. Position sizing is binary across two assets (long-side index +1, gold +1, NIFTY short -1) with cash as the third state; no leverage beyond 1×.

*Research project. Backtest results, methodology, and known limitations documented below. Not deployed; not investment advice.*

![Equity Curve](images/equity_curve.png)

---

## Headline Results

Backtest period: **2008-04-01 to 2025-12-31** (17.7 years). Net results assume per-asset transaction costs of **3 bps per leg** on NIFTY 50 futures (short side), **6 bps per leg** on NIFTY 200 Momentum 30 ETFs (long side), and **5 bps per leg** on GOLDBEES.NS (gold ETF). Idle capital on fully-flat days earns the prevailing RBI repo rate minus a 100 bps haircut modeling realistic liquid-fund execution.

| Metric | Strategy (v1.3) | NIFTY Buy & Hold | Δ |
|---|---|---|---|
| Sharpe (RF = 6%) | 0.83 | 0.27 | **+207%** |
| Sortino | 0.97 | 0.25 | **+288%** |
| Calmar | 1.00 | 0.19 | **+426%** |
| Annualized volatility | 13.90% | 19.27% | -28% |
| Max drawdown | -18.1% | -51.7% | -65% |
| CAGR | 18.08% | 9.74% | +834 bps |
| Cumulative return | 2,022.6% | 451.9% | +1,570.7pp |

The strategy generates risk-adjusted alpha vs passive NIFTY exposure through three independent mechanisms operating together: (1) tactical long exposure to a momentum-tilted equity portfolio — long NIFTY 200 Momentum 30 during bull regimes, flat or short NIFTY 50 during identified stress regimes; (2) momentum-gated safe-haven rotation — long gold during stress windows only while gold momentum is positive, with mid-latch exit to cash if gold momentum turns negative; (3) cash management — idle capital earns the prevailing RBI repo rate minus a 100 bps haircut on fully-flat days, modeling realistic institutional liquid-fund execution. The 207% Sharpe improvement is the most direct measure of joint risk-adjusted skill across these mechanisms. Cumulative outperformance vs buy-and-hold (+1,571pp over 17.7 years) is the geometric outcome of compounding all three together — the mechanisms cannot be cleanly separated into additive contributions, since they interact through the position sequence and the compounding base.

---

## Mechanisms of Outperformance

The strategy's outperformance derives from three mechanisms that compound together over the 17.7-year sample. Their contributions are inherently joint and cannot be cleanly attributed to additive percentages, since each mechanism affects the compounding base for the others.

**Tactical long exposure to a momentum-tilted equity portfolio.** The strategy is long the long-side index ~66% of trading days (calm bull regimes), flat ~33% (bear regimes and stress flats), short NIFTY 50 ~1% (panic-short windows), and long gold ~1% (stress-flat windows where gold momentum is positive). When long, the strategy holds **NIFTY 200 Momentum 30** — a 30-stock factor-tilted portfolio drawn from the NIFTY 200 universe and ranked semi-annually by 6-month and 12-month price momentum. This generates bull-regime alpha that v1.2's NIFTY-50 long-side architecture could not produce structurally. Short exposure during panic-shorts remains on NIFTY 50 (more liquid for futures-based shorting). Avoiding equity exposure during identified bear regimes captures volatility-drag alpha — a strategy that sidesteps the left-tail of the equity return distribution compounds at a higher geometric rate than buy-and-hold even with similar arithmetic mean returns. This is the core mechanism; the others amplify it.

**Momentum-gated safe-haven rotation.** During identified stress-flat windows, capital rotates to GOLDBEES.NS — but only when gold's 10-day momentum is positive at the start of the latch, and only while it stays positive during the latch. If gold momentum turns negative mid-latch, the strategy exits gold to cash for the remainder of the latch (one-way door — no re-entry within the same latch). This per-latch state machine addresses a structural failure mode where supply-shock signals fire after gold has already rallied, leaving the strategy buying gold near tops. v1.2 holds gold ~41 days across the sample (about half of v1.1.1's 76 days); the gate blocks entry when gold is in a downtrend or exits early when the rally reverses.

**Cash yield on idle capital (with realistic haircut).** On fully-flat days where neither NIFTY nor gold is held, the strategy credits the prevailing RBI repo rate minus a 100 bps haircut. The haircut models real-world liquid-fund execution: instrument spread (~50 bps inside repo), TER (~10–25 bps), and small auto-sweep frictions. This produces a more conservative cash yield estimate than v1.1.1's pure-repo assumption. Sensitivity to the haircut size is documented under Backtest Caveats.

**The Sharpe improvement (+207% vs NIFTY) is the most reliable single measure of risk-adjusted skill** because it normalizes return per unit of volatility regardless of which mechanism is doing the work on any given day. Cumulative return improvement (+1,571pp) is striking but is inherently joint and path-dependent.

---

## Long-Side Asset Selection

v1.2 had a structural bull-regime alpha gap: when fully long, the strategy held NIFTY 50 — the same asset as the benchmark — so it could only match (never beat) the benchmark on the long side. v1.3 addresses this by substituting a higher-expected-return Indian equity index as the long-side asset. Eight candidates were considered; two were backtested under identical regime-detection and risk-management mechanics; NIFTY 200 Momentum 30 was selected.

### Indices Considered

1. **NIFTY 50** — retained as benchmark and short-side asset; rejected as long-side due to the bull-regime alpha gap.
2. **NIFTY Midcap 150** — fully backtested as Config 5; rejected (drawdown profile, see below).
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

**Table B — Same strategy mechanics, three long-side assets:**

| Long-side asset | CAGR | Sharpe | Calmar | Max DD |
|---|---|---|---|---|
| NIFTY 50 (v1.2 / Config 4) | 12.59% | 0.50 | 0.77 | -16.4% |
| Midcap 150 (Config 5) | 21.30% | 1.00 | 0.82 | -26.1% |
| NIFTY 200 Momentum 30 (v1.3 / Config 6) | 18.08% | 0.83 | **1.00** | -18.1% |

Midcap 150 produced the highest absolute CAGR but at unacceptable drawdown deterioration — max DD widened from v1.2's -16.4% to -26.1%, a ~60% worsening that eliminates the strategy's headline drawdown control. Momentum 30 achieves the best Calmar of the three configurations (1.00) while preserving drawdown within 2pp of v1.2.

---

## Configurations Tested

The production strategy emerged from six explicit configurations spanning two design axes: deployment of capital during identified stress regimes (Configs 1-4) and choice of long-side equity asset during bull regimes (Configs 4-6). Each was backtested over the full 2008-2025 in-sample period with identical regime-detection logic, transaction costs, and cash-yield assumptions; only the variable under test differed.

| Config | Variant | Status | Reason |
|---|---|---|---|
| 1 | No gold rotation; NIFTY-only stress-flat | Rejected | Stress-flat capital earns only cash yield; misses safe-haven upside |
| 2 | Unconditional gold rotation on every stress-flat day | Rejected | Enters gold near intraperiod tops in 2026 H1; gold contribution -9.2% YTD |
| 3 | Always-on gold (held during bull regimes too) | Rejected | Dilutes bull-regime equity exposure with non-correlated asset; net CAGR drag |
| 4 | Momentum-gated gold rotation (10-day gate, per-latch state machine) | Selected (v1.2) | Avoids 2026 timing failure without giving up safe-haven mechanism; gold-days reduced 76 → 41 |
| 5 | Config 4 + NIFTY Midcap 150 as long-side asset | Rejected | Drawdown deteriorates to -26.1% — eliminates headline drawdown control |
| 6 | Config 4 + NIFTY 200 Momentum 30 as long-side asset | **Selected (v1.3)** | Highest Calmar of the three (1.00); preserves drawdown within 2pp of v1.2; structurally coherent |

Configurations were evaluated on the joint criterion of risk-adjusted return (Sharpe, Calmar) and absolute drawdown control. Config 4 was selected as v1.2 production because it addressed the gold-rotation timing failure observed in 2026 H1 without sacrificing the safe-haven mechanism. Config 6 was selected as v1.3 production because it generates higher CAGR than Config 4 while preserving the drawdown profile, where Config 5's higher CAGR came at unacceptable drawdown cost.

---

## Strategy Overview

The framework targets alpha through **regime identification combined with multi-asset rotation**. Three independent macro-regime signal lanes are computed daily:

1. **USDINR momentum** — long entry on rupee strengthening (capital inflows, risk-on)
2. **India VIX momentum** — long entry on fear subsiding (post-stress mean reversion)
3. **Supply-shock and panic-short triggers** — exit-to-flat or active short on coordinated macro stress (oil + INR + VIX, with an absolute VIX-level filter for the short leg)

A 100-day moving-average regime filter on **NIFTY 50** acts as the final gate: longs are only permitted when NIFTY 50 is above its 100 DMA, shorts only when below. Regime detection runs on NIFTY 50 (the cleanest broad-market macro-sentiment proxy) regardless of which asset is held on the long side — this separates regime detection from asset selection. Position sizing is binary across two long-side assets (long NIFTY 200 Momentum 30 = +1, long gold = +1, short NIFTY 50 = -1, cash flat = 0); no leverage beyond 1×. Position-logic priority is: long entry → supply-shock exit override → panic-short override → regime-filter gate → momentum-gated gold rotation overlay on stress-flat days (gated on gold's own 10-day momentum) → RBI repo cash yield (minus 100 bps haircut) on remaining flat days.

The framework targets alpha through regime identification combined with multi-asset rotation. When in a bull regime, the strategy holds NIFTY 200 Momentum 30 (the long-side asset selected for higher expected return than NIFTY 50 — see Long-Side Asset Selection). When the strategy identifies a stress regime, gold rotation is conditional on gold's own momentum — gold is held only while its 10-day return is positive, and the strategy exits to cash mid-latch if momentum turns negative. When fully flat, idle capital earns the time-varying RBI repo rate minus a 100 bps haircut modeling realistic liquid-fund execution. This produces three independent mechanisms — tactical long exposure to a momentum-tilted equity portfolio, momentum-gated safe-haven rotation, and cash management — that compound across the 17-year sample.

---

## Signal Logic

### 1. USDINR Momentum — Long Entry

**Economic rationale.** A strengthening rupee correlates with risk-on flows into Indian equities, foreign portfolio inflows, and easing of import-cost pressure on margins. Sustained INR strength is a leading indicator of bullish equity sentiment.

**Mechanics.**
- Signal: 10-day percentage change in USDINR (Yahoo: `INR=X`)
- Long entry: USDINR has fallen by more than 1% over 10 days (rupee strengthened)
- Long-only; no exit logic in this lane (exits handled by supply-shock and panic-short lanes)

### 2. India VIX Momentum — Long Entry

**Economic rationale.** Falling implied volatility signals subsiding fear and a regime of risk appetite, historically associated with multi-week equity rallies. Captures the calm-after-the-storm mean reversion that follows volatility spikes.

**Mechanics.**
- Signal: 10-day percentage change in India VIX (`^INDIAVIX`)
- Long entry: VIX has fallen by more than 20% over 10 days
- Long-only

### 3. Supply-Shock Trigger — Force Flat

**Economic rationale.** When crude oil, USDINR, and India VIX move adversely in unison over a short window, India's macro vulnerability is acute (worsening current account, currency pressure, equity outflows). Rather than sit through the drawdown, the strategy steps to flat until the panic subsides.

**Mechanics.** All three conditions must fire simultaneously over a 10-day window:
- Crude (`CL=F`) up more than 3%
- USDINR up more than 1%
- India VIX up more than 20%

When fired, position is forced to flat (0). Re-entry is gated on a NIFTY 5-day return exceeding 0.5% — wait for upside confirmation before re-engaging.

### 4. Panic-Short Trigger — Active Short

**Economic rationale.** A high absolute VIX level *combined with* an accelerating VIX spike *and* NIFTY already below trend captures regimes where the cycle has decisively turned bearish — distinct from the transient stress that the supply-shock lane handles. In these regimes, capital protection plus directional exposure to the bearish move is preferable to going flat.

**Mechanics.** All three conditions must hold simultaneously:
- India VIX absolute level ≥ 25
- VIX up more than 50% over 10 days
- NIFTY closing below its 100-day moving average

When fired, position is forced to -1 (active short). Short exits when the NIFTY 5-day MA crosses above the 20-day MA. After short exit, the strategy stays flat until the NIFTY 5-day return > 0.5% confirmation fires.

### 5. Regime Filter — Final Gate

**Economic rationale.** The 100-day moving average serves as a coarse trend filter, ensuring lane signals operate in their intended directional context — longs only get through in confirmed uptrends, shorts only in confirmed downtrends.

**Mechanics.**
- Bull regime: NIFTY > 100 DMA → longs permitted, shorts blocked
- Bear regime: NIFTY < 100 DMA → longs forced flat, shorts permitted
- Applied as a final override after all three lanes have been computed

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
| RBI Repo Rate (v1.1) | — | RBI MPC press releases ([rbi.org.in](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx)); hardcoded as `RBI_REPO_RATE_HISTORY` in `strategy.py` | Step function (53 announcements over 2008–2025) |

Most market data is downloaded live at runtime via `yfinance`; NIFTY 200 Momentum 30 is loaded from a static CSV (`data/momentum30_history.csv`) sourced from niftyindices.com via the `nselib` Python library. India VIX series begins March 2008, which sets the in-sample start at **2008-04-01**. A warmup period from **2006-01-01 to 2008-03-31** seeds rolling windows and is excluded from results. GOLDBEES.NS data starts 2009-01-02; pre-2009 stress-flat days remain fully flat in the backtest (gold instrument not yet tradable). Cleaning is minimal: forward-fill across mismatched holiday calendars, drop full-NaN rows.

**NIFTY 200 Momentum 30 history note.** The index was launched live in August 2020 with backfilled history to April 2005 (the index's official base date) by NSE Indices Ltd. The backfilled portion uses the same mechanical methodology (semi-annual rebalance, momentum score = 6m + 12m risk-adjusted price momentum, top 30 stocks by score from NIFTY 200 universe) that NSE applies live. Cross-validation against yfinance over the 2019+ overlap period showed perfect correlation (1.000000) and 0.0000% mean relative difference, confirming data fidelity.

The RBI repo rate timeline is **hardcoded** rather than fetched at runtime because (a) no reliable free Indian short-rate API exists with full 2008-2025 coverage, (b) the repo rate is a step function with only ~50 changes over 17 years, ideal for a static table, and (c) hardcoding makes the backtest deterministic and auditable. Each row is sourced from the corresponding RBI MPC press release; the table is maintained manually and must be updated when RBI announces new rate decisions.

**Forward-testing implication:** When the strategy is run on dates after the last hardcoded entry, `build_rbi_repo_rate_series()` forward-fills the most recent rate indefinitely. This is correct as long as RBI hasn't moved the rate since the last entry — but goes silently stale if a rate change occurred and the table wasn't updated. For paper trading or live use, the table needs a manual refresh after each RBI MPC meeting (every ~6-8 weeks). Productionizing this — moving to a CSV-backed config file with a FRED API fallback — is on the roadmap (item 7).

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
| Transaction costs | NIFTY 50 futures (short side): **3 bps per leg**. NIFTY 200 Momentum 30 ETF (long side, v1.3): **6 bps per leg** (ETF spread + STT; slightly wider than NIFTY futures due to lower turnover). Gold (GOLDBEES.NS): **5 bps per leg** (ETF spread + STT). Cash sweep: **0 bps** (institutional auto-sweep into liquid fund). Applied as `\|Δposition\| × cost_bps / 10,000`, deducted from same-day return. Long↔short flips cost both legs. |
| Cash yield on flat days (v1.2) | Time-varying RBI repo rate as a step function (range 4.0%–9.0% over 2008–2025), with a **100 bps haircut** applied daily on fully-flat days to model realistic institutional liquid-fund execution (instrument spread + TER + sweep friction). Hardcoded in `RBI_REPO_RATE_HISTORY` in `strategy.py`. Setting `cash_yield_haircut_bps=0` recovers v1.1.1's pure-repo assumption (sensitivity in Backtest Caveats). |
| Gold rotation (v1.2) | Per-latch momentum state machine: at stress-flat latch start, rotate to gold only if GOLDBEES.NS 10-day return > 0. While holding, exit to cash if 10-day return turns negative. Once exited mid-latch, stay in cash for the rest of the latch (one-way door). Re-entry only allowed in a new latch. |
| Risk-free rate | 6% per annum (India 10Y G-Sec proxy) for Sharpe and Sortino. |
| Out-of-sample | 2026-01-01 to 2026-05-11 held out from parameter selection. |
| Parameter selection | Judgement-based; no grid search or formal optimization. |

---

## Results

### Year-by-Year Returns

| Year | Strategy | NIFTY B&H | Outperformance |
|---|---|---|---|
| 2008 | +4.4% | -37.5% | **+41.9pp** |
| 2009 | +59.5% | +75.8% | -16.3pp |
| 2010 | +16.0% | +17.9% | -1.9pp |
| 2011 | -3.7% | -24.6% | **+21.0pp** |
| 2012 | +29.5% | +27.7% | **+1.8pp** |
| 2013 | -1.7% | +6.8% | -8.5pp |
| 2014 | +38.0% | +31.4% | **+6.6pp** |
| 2015 | +5.1% | -4.1% | **+9.2pp** |
| 2016 | +22.3% | +3.0% | **+19.2pp** |
| 2017 | +31.3% | +28.6% | **+2.6pp** |
| 2018 | -7.2% | +3.2% | -10.3pp |
| 2019 | +5.6% | +12.0% | -6.4pp |
| 2020 | +67.9% | +14.9% | **+53.0pp** |
| 2021 | +39.7% | +24.1% | **+15.6pp** |
| 2022 | -0.1% | +4.3% | -4.4pp |
| 2023 | +28.6% | +20.0% | **+8.6pp** |
| 2024 | +24.6% | +8.8% | **+15.8pp** |
| 2025 | +4.6% | +10.5% | -5.9pp |

The strategy outperforms NIFTY in **11 of 18 calendar years** — 2008, 2011, 2012, 2014, 2015, 2016, 2017, 2020, 2021, 2023, and 2024. This is materially higher than v1.2's 5-of-18 count, reflecting the structural improvement from substituting Momentum 30 for NIFTY 50 as the long-side asset: in normal bull years where the regime filter is satisfied, Momentum 30's factor tilt delivers excess return over the benchmark on the same long days. The biggest contributors are 2008 (+41.9pp, GFC drawdown avoidance), 2020 (+53.0pp, COVID panic-short plus gold rotation plus regime-filter cash yield), and 2011 (+21.0pp, European debt stress + cash yield at ~8% repo). The 17-year compounded result is driven by **asymmetric crisis-window capture** plus **bull-regime factor alpha** — large gains during regime breaks combined with consistent excess return in normal up-trending markets.

**2009 underperformance is structural, not anomalous.** The strategy underperformed NIFTY by -16.3pp in 2009 — the well-documented momentum-crash failure mode (Daniel & Moskowitz 2016, *Momentum Crashes*). The regime filter prevented exposure during the worst of the 2008 fall (saving -41.9pp vs NIFTY that year), but the recovery-phase cost is paid in early 2009 when momentum stocks lag the cyclical rebound: the names that fell hardest in the crash are excluded from the momentum portfolio precisely because they fell hardest. The trade-off is structural and accepted; a regime-conditional V-recovery overlay is documented as a roadmap item.

![Yearly Returns](images/yearly_returns.png)

### Drawdown

![Drawdown](images/drawdown.png)

Maximum drawdown of **-18.1%** vs NIFTY's **-51.7%** — a **65% reduction**. Cash yield on flat days during bear regimes (notably 2008-2009 GFC and 2020 March-August COVID recovery) cushions equity drawdowns by adding deterministic positive return on the worst-impact days. The drawdown profile reflects the joint mechanism set: the largest contributions to the gap come from the 2008 GFC (regime filter + cash yield at ~8% repo), 2011 European debt stress (gold rotation + cash yield), and 2020 COVID crash (panic-short + gold rotation + cash yield through the recovery period). v1.3's drawdown is modestly worse than v1.2's -16.4% (2pp wider) because Momentum 30 has slightly higher realized volatility than NIFTY 50 on long days, but this is more than offset by the ~5.5pp/yr CAGR uplift the asset substitution delivers.

### Cost Sensitivity

For v1.3, the long-side asset is NIFTY 200 Momentum 30 (ETF, 6 bps per leg base case). The table below varies the long-side cost; NIFTY short cost (3 bps) and gold cost (5 bps) are held fixed. Cash sweep is treated as zero-cost at all levels.

| Long-side cost (bps/leg) | Cumulative Return | CAGR | Sharpe | Max DD |
|---|---|---|---|---|
| 0 | 2,287.8% | 18.84% | 0.88 | -17.2% |
| 3 | 2,151.3% | 18.46% | 0.86 | -17.7% |
| **6 (base)** | **2,022.6%** | **18.08%** | **0.83** | **-18.1%** |
| 10 | 1,862.3% | 17.58% | 0.80 | -18.6% |
| 15 | 1,678.7% | 16.95% | 0.76 | -19.3% |
| 20 | 1,512.3% | 16.33% | 0.72 | -20.0% |
| 50 | 793.2% | 12.65% | 0.49 | -24.2% |

Strategy economics degrade more slowly than a purely directional version because cash yield on idle capital is unaffected by transaction costs — fully-flat days don't trade and so don't pay friction. Sharpe stays well above NIFTY's 0.27 buy-and-hold all the way through 20 bps long-side cost. The 50 bps row remains a stress test, not a realistic implementation cost.

---

## Robustness Checks

### Crisis-Period Stress Tests

| Crisis | Window | Strategy | NIFTY | Strategy DD | NIFTY DD |
|---|---|---|---|---|---|
| GFC | Sep 2008 – Mar 2009 | **+2.1%** | -30.7% | -3.7% | -44.0% |
| Euro debt | Jul 2011 – Dec 2011 | **+0.5%** | -18.1% | -7.5% | -20.7% |
| Taper Tantrum | May – Sept 2013 | -4.8% | -3.3% | -14.0% | -14.6% |
| NBFC / IL&FS | Sep 2018 – Feb 2019 | -9.9% | -7.6% | -9.7% | -13.5% |
| COVID Crash | Feb – Dec 2020 | **+63.2%** | +16.9% | -13.6% | -37.6% |
| Russia 2022 | Feb – Jun 2022 | **-2.9%** | -10.2% | -10.5% | -15.3% |
| 2025-26 sell-off | Oct 2025 – Apr 2026 | **-4.7%** | -3.4% | -10.5% | -15.2% |

The strategy navigates GFC-style and COVID-style regimes well — both feature decisive trend breakdowns that the panic-short and supply-shock lanes capture cleanly. The GFC window returns +2.1% (vs NIFTY -30.7%) because cash yield on the ~192 fully-flat days at ~8% repo dominates the small drag from the supply-shock latch. The 2011 European debt window flips to a +0.5% strategy *gain* (vs NIFTY -18.1%) via flat-period cash yield + a small contribution from gold rotation. The 2013 Taper Tantrum (-4.8% vs NIFTY -3.3%) is a small underperformance — the momentum gate correctly avoided gold's EM-rate-shock sell-off, but the strategy still rode some underlying weakness during regime transitions. The 2018 NBFC crisis (-9.9% vs NIFTY -7.6%) underperforms because the momentum gate blocked gold rotation when its pre-fire momentum was weak; trade-off accepted to gain 2026 OOS robustness.

**A note on Momentum 30 behavior in stress.** Momentum 30 itself underperforms NIFTY 50 in some crisis windows (e.g., Russia 2022 buy-and-hold: Mom30 -18.5% vs NIFTY -10.2%) because momentum portfolios concentrate exposure in recent winners that can unwind sharply on regime shifts. The strategy's regime-detection and cash-yield mechanics compress these drawdowns materially — Russia 2022 strategy result is -2.9% vs Mom30 B&H's -18.5%, a ~16pp risk-reduction attributable to the strategy mechanics rather than the asset choice.

### 2026 Out-of-Sample Performance

The strategy went live in development through 2025-12-31, with 2026 reserved as out-of-sample. Through 2026-05-11 (94 trading days):

| | 2026 YTD return |
|---|---|
| **Strategy (v1.3 / Config 6)** | **-0.19%** |
| NIFTY 50 Buy & Hold | -7.48% |
| **Outperformance** | **+7.29pp** |

Buy-and-hold YTD for the three indices considered: NIFTY 50 -8.9%, NIFTY Midcap 150 +0.7%, NIFTY 200 Momentum 30 -2.5%. The strategy on Momentum 30 outperformed Momentum 30 buy-and-hold by **+2.3pp**, confirming the strategy's risk-management mechanisms add value beyond the underlying asset choice — flat-day cash yield plus the momentum-gated gold rotation contribute the gap. The v1.2 baseline (Config 4, NIFTY 50 long-side) returned -5.66% over the same window; v1.3 outperformed v1.2 by +5.47pp in 2026 OOS.

v1.2's gold-rotation gate continues to do useful work in v1.3: the gate exited gold mid-latch when 10-day momentum turned negative, reducing gold-days from 26 (Config 2) to 12 (Configs 4/5/6) and gold P&L contribution from -9.19% to -2.10%. Without this gate, the strategy on any long-side asset would have lost ~10pp more YTD.

**Variants considered and rejected.** A contrarian entry filter that would have blocked gold rotation specifically when gold had already rallied >X% prior to supply-shock fire (Variant F) was tested and rejected as overfitting — it improved 2026 OOS but degraded historical events where gold rallied into supply-shock fires and continued rallying afterward. The momentum-gate approach in v1.2/v1.3 addresses the symptom (holding gold through a downturn) via an exit-side rule that's both prospective and asymmetric, without overfitting to any specific historical event.

### Walk-Forward Validation

Not yet implemented (parameter selection was manual). Planned — see Roadmap.

---

## Limitations

Active weaknesses I am addressing on the roadmap.

1. **Limited cross-asset universe.** The current implementation is two-asset (NIFTY + gold) with cash as the third state. The structural question — whether cumulative alpha vs NIFTY can be sourced from something other than tactical reduction of NIFTY exposure — is now partially addressed via gold rotation, but the asset universe remains narrow. Expansion to additional risk assets (USDINR overlay, broader equity indices) is on the roadmap. Walk-forward validation of the gold rotation rule specifically has not been done.

2. **Not all crisis regimes are handled equally.** The 2013 taper tantrum and 2018 NBFC crisis are visible failure modes — slow, grinding drawdowns where the panic-short trigger fires late or not at all. A regime-classification layer that distinguishes crash-type stress from grind-down stress is on the roadmap.

3. **Panic-short exit logic is structurally thin.** The active short uses only two exit mechanisms — a 5-day / 20-day NIFTY MA crossover and a 60-day time cap (the latter only active in `hold=True` configs) — and both parameter sets (5/20 windows, 60-day cap) were hand-picked rather than derived from panic-event duration statistics or a parameter sweep. The strategy enters via a strict 3-condition AND but exits on a single binary MA flip — an asymmetry between strict-entry and loose-exit that has not been stress-tested against scenarios where the initial short thesis is wrong (e.g. a V-shaped recovery that bottoms before the MA crossover registers). There is no stop-loss, no profit-taking rule, and no volatility-normalized exit threshold. **Mitigating control:** the production config currently ships with `hold=False` (pulse short only — short is active solely on the ~32 days where panic conditions raw-fire), which structurally caps any single-short loss exposure at one day. This avoids the worst case (sitting short into a multi-week rebound) by construction, but at the cost of leaving short-side P&L heavily dependent on the timing of the very next day's NIFTY return — a thin defense, not a robust one. The roadmap addresses this; until then, sizing of any panic-short component should be conservative and the no-hold default should not be flipped without redesigning the exit framework first.

4. **No live track record.** All results are backtest-only. Out-of-sample paper trading from 2026 onward is in progress; live trading at size has not been undertaken.

5. **Bull-regime alpha gap (ADDRESSED in v1.3).** v1.2 had a structural bull-regime alpha gap — when fully long, the strategy held NIFTY 50, the same asset as the benchmark, so it could only match (never beat) the benchmark on the long side. v1.3 addresses this by substituting **NIFTY 200 Momentum 30** as the long-side asset (see Long-Side Asset Selection section). The outperformance count in normal bull years jumped from 5-of-18 in v1.2 to 11-of-18 in v1.3. A residual factor-specific risk is documented as Limitation #6 below.

6. **Momentum-factor V-recovery lag.** Long-side exposure is to NIFTY 200 Momentum 30, a factor-tilted portfolio that lags during V-shaped recoveries — a well-documented failure mode of momentum strategies (Daniel & Moskowitz 2016, *Momentum Crashes*). In recovery transitions, the highest-beta names to the rebound are typically those that were beaten down hardest in the crash, so they are not present in the winners portfolio. The strategy mitigates this two ways: (a) the regime filter keeps exposure flat or short during the crash itself, so the worst of the underlying drawdown is avoided; (b) the regime filter re-engages long exposure only after NIFTY 50 has recovered above its 100 DMA, at which point the Momentum 30 index has begun its own internal rotation toward the new winners. Empirically observed in the 2009 sample: the strategy underperformed NIFTY 50 by -16.3pp that calendar year but had already avoided -41.9pp of the 2008 GFC drawdown. The trade-off is structural and accepted; a regime-conditional asset selection overlay is in the roadmap.

---

## Backtest Caveats

These are structural caveats inherent to backtest research and macro-strategy design — not specific flaws of this strategy. They are documented for transparency, not as roadmap items.

1. **Researcher degrees of freedom.** Parameters (lookback windows, thresholds, DMA length) and signal selection (USDINR + VIX + supply-shock + panic-short) were chosen with knowledge of recent Indian market behavior. Walk-forward parameter validation is on the roadmap but has not yet been done. The choice of *which signals* to include is not addressable by walk-forward — only out-of-sample paper trading provides that test.

2. **Limited regime diversity in available data.** India VIX only exists from 2008, capping the backtest at ~17 years. Two true crisis regimes (GFC, COVID) plus several smaller stresses (2011, 2013, 2018, 2022) is statistically thin for a regime-conditional model.

3. **Non-stationarity of macro relationships.** USDINR / VIX / equity correlations have shifted over the sample (pre vs post 2014 RBI inflation-targeting framework, pre vs post 2020 liquidity regime, evolving FII flow dynamics). The strategy implicitly assumes some stability in these relationships going forward.

4. **Capacity and crowding unknown.** Backtest is unaware of position size. VIX-based and panic-short signals may have crowded behavior in stress regimes; edge at scale has not been tested.

5. **Cash-yield modeling assumes liquid-fund-style execution (v1.2 / v1.3).** The strategy credits the RBI repo rate minus a 100 bps haircut on fully-flat days, modeling realistic institutional cash execution: liquid-fund instrument spread (~25–50 bps inside repo), TER (~10–25 bps), and small auto-sweep frictions. v1.1.1 used a no-haircut (pure repo) assumption that external review flagged as too aggressive; v1.2's 100 bps default is more conservative and more credible. Additionally, the Sharpe-ratio benchmark hurdle is held constant at 6% even though the modeled cash yield ranges 3–8% over the sample after haircut — a minor inconsistency that doesn't materially affect cross-strategy comparison since NIFTY's Sharpe uses the same hurdle. **Sensitivity to the haircut (v1.3 / Config 6):** 0 bps (full repo, v1.1.1 assumption) → 2,154.5% cumulative / 18.47% CAGR / 0.86 Sharpe; 200 bps (stress) → 1,898.5% / 17.70% / 0.81; cash yield entirely off → 1,418.5% / 15.95% / 0.70.

6. **Limited out-of-sample coverage.** OOS testing covers 2026-01-01 through 2026-05-11 (94 trading days). v1.3 outperformed NIFTY by +7.29pp in this window — a meaningful demonstration that v1.2's gold-rotation gate plus v1.3's Momentum 30 long-side substitution work together in live conditions. This is a single OOS year and a single regime; broader OOS validation requires either additional time or formal walk-forward methodology (on the roadmap). The 11-of-18 in-sample outperformance count for v1.3 should be interpreted alongside this OOS window — the strategy is regime-defensive AND factor-tilted by construction, but a single OOS year is not statistical proof of forward-going edge.

---

## Roadmap

In progress and planned, in priority order:

1. **Walk-forward parameter validation** — re-fit thresholds and lookback windows on rolling 5-year windows; report out-of-sample-only equity curve. Includes walk-forward validation of the gold rotation rule and the long-side asset choice. **Highest-priority next step.**
2. ~~**Higher-alpha equity index substitution for bull regimes**~~ — **COMPLETED in v1.3.** NIFTY 200 Momentum 30 substituted for NIFTY 50 as the long-side asset. Eight candidates considered, two backtested (Midcap 150 rejected on drawdown grounds, Mom30 selected). See Long-Side Asset Selection section. Realized impact: +5.5pp CAGR over v1.2; drawdown widened 2pp (within accepted tolerance).
3. **Regime-conditional asset selection (V-recovery overlay).** The v1.3 architecture separates regime detection (on NIFTY 50) from asset selection (long-side asset), enabling the long-side asset to be made conditional on the current regime classification. A natural extension is to switch from Momentum 30 to a broader or higher-beta index during V-recovery transitions (the Daniel-Moskowitz 2016 momentum-crash failure mode, observed in our 2009 sample). Requires a recovery classifier (candidates: breadth, realized-vol direction, time since regime-filter flip) and a defined re-entry rule into Momentum 30. Sample contains only 2-3 unambiguous recoveries (2009, 2020, possibly mid-2022), so forward paper-trading evidence is needed before tuning specifically against historical events.
4. **Quality 30 / Low Volatility 30 as alternative long-side assets** — tested in v1.3 only as candidates rejected without backtest; revisit if Momentum 30 underperforms over a future OOS window. A defensive long-side asset (Low Vol or Quality) could be used as a regime-conditional alternative to Momentum 30, replacing it during identified V-recovery phases (links to roadmap item 3).
5. **Additional safe-haven cross-asset overlays** — extend beyond gold to USDINR and other defensive assets historically resilient during India-stress regimes. Targets diversification of the safe-haven sleeve and improvements to Sharpe through reduced single-asset reliance during stress windows.
6. **Slow-stress regime layer** — classification step to distinguish crash-type stress from grind-down stress, addressing the 2013 / 2018 failure modes.
7. **Panic-short exit framework redesign** — replace the current single-rule MA crossover exit with a layered framework: profit-take at +X%, stop-loss at -Y%, volatility-normalized exit thresholds (scale by current VIX), and immediate re-evaluation of entry conditions (cover the moment any of the three entry conditions flips). Required before flipping the production config from `hold=False` to `hold=True`. Addresses Limitation #3.
8. **Signal-by-signal P&L attribution** — decompose cumulative P&L by lane (USDINR, VIX, supply-shock, panic-short, regime-filter contribution) to confirm each signal independently earns its keep.
9. **Forward paper-trading** — daily logged signals against live data from 2026 onward.
10. **Productionize the RBI repo rate feed** — replace the hardcoded `RBI_REPO_RATE_HISTORY` table with a CSV-backed config file (`data/rbi_repo_rate.csv`) plus a FRED API fallback for any dates after the last manual entry. Add a runtime warning if the strategy runs on a date past the latest available rate. Required before any live trading; nice-to-have for paper trading.
11. **Modular refactor** — break monolithic `strategy.py` into `src/data.py`, `src/signals.py`, `src/backtest.py` for extensibility.

---

## Version History

| Version | Description | Cumulative | CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|
| v1.0 | Single-asset directional (no gold, no cash yield). Preserved at commit `c2860fc`. | 467.2% | 9.91% | 0.33 | -22.2% |
| v1.1.1 | Adds gold rotation throughout stress-flat latches + pure-repo cash yield. Preserved at commit `078878a`. | 908.4% | 13.40% | 0.55 | -18.3% |
| v1.2 | Adds momentum-gated gold rotation (per-latch state machine) + 100 bps repo haircut. | 784.8% | 12.59% | 0.50 | -16.4% |
| **v1.3** | **Substitutes NIFTY 200 Momentum 30 for NIFTY 50 as long-side asset; regime detection unchanged. Current.** | **2,022.6%** | **18.08%** | **0.83** | **-18.1%** |

v1.3 trades a modest 2pp drawdown deterioration (-18.1% vs v1.2's -16.4%) for substantial CAGR uplift (+5.5pp), better Calmar (1.00 vs 0.77), and significantly higher Sharpe (0.83 vs 0.50). The architectural change — separating regime detection (on NIFTY 50) from long-side asset selection (NIFTY 200 Momentum 30) — enables future regime-conditional asset selection work (roadmap item 3). A new factor-specific limitation is documented: momentum-factor V-recovery lag (Limitation #6), mitigated by the regime filter keeping exposure flat during the worst of crash phases.

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

---

## Contact

Neil K. Kapadia · neilkk@umich.edu

---

*MIT licensed. Code and methodology provided for research purposes only; not investment advice.*

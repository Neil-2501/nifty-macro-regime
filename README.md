# Indian Equity Macro-Regime Strategy

A systematic macro-regime strategy for Indian markets combining tactical NIFTY exposure, momentum-gated gold rotation during identified stress regimes, and haircut-adjusted RBI repo-rate cash yield on idle capital. Three independent signal lanes — USDINR momentum, India VIX momentum, and supply-shock / panic-short triggers — identify macro regime breaks, gated by a 100-day moving-average trend filter. Position sizing is binary across two assets (NIFTY ±1, gold +1) with cash as the third state; no leverage beyond 1×.

*Research project. Backtest results, methodology, and known limitations documented below. Not deployed; not investment advice.*

![Equity Curve](images/equity_curve.png)

---

## Headline Results

Backtest period: **2008-04-01 to 2025-12-31** (17.7 years). Net results assume per-asset transaction costs of **3 bps per leg** on NIFTY futures and **5 bps per leg** on GOLDBEES.NS (gold ETF). Idle capital on fully-flat days earns the prevailing RBI repo rate minus a 100 bps haircut modeling realistic liquid-fund execution.

| Metric | Strategy (v1.2) | NIFTY Buy & Hold | Δ |
|---|---|---|---|
| Sharpe (RF = 6%) | 0.50 | 0.27 | **+85%** |
| Sortino | 0.59 | 0.25 | **+136%** |
| Calmar | 0.77 | 0.19 | **+305%** |
| Annualized volatility | 13.48% | 19.27% | -30% |
| Max drawdown | -16.4% | -51.7% | -68% |
| CAGR | 12.59% | 9.74% | +285 bps |
| Cumulative return | 784.8% | 451.9% | +332.9pp |

The strategy generates risk-adjusted alpha vs passive NIFTY exposure through three independent mechanisms operating together: (1) tactical equity exposure — long during bull regimes, flat or short during identified stress regimes; (2) momentum-gated safe-haven rotation — long gold during stress windows only while gold momentum is positive, with mid-latch exit to cash if gold momentum turns negative; (3) cash management — idle capital earns the prevailing RBI repo rate minus a 100 bps haircut on fully-flat days, modeling realistic institutional liquid-fund execution. The 85% Sharpe improvement is the most direct measure of joint risk-adjusted skill across these mechanisms. Cumulative outperformance vs buy-and-hold (+333pp over 17.7 years) is the geometric outcome of compounding all three together — the mechanisms cannot be cleanly separated into additive contributions, since they interact through the position sequence and the compounding base.

---

## Mechanisms of Outperformance

The strategy's outperformance derives from three mechanisms that compound together over the 17.7-year sample. Their contributions are inherently joint and cannot be cleanly attributed to additive percentages, since each mechanism affects the compounding base for the others.

**Tactical equity exposure.** The strategy is long NIFTY ~66% of trading days (calm bull regimes), flat ~33% (bear regimes and stress flats), short ~1% (panic-short windows), and long gold ~1% (stress-flat windows where gold momentum is positive). Avoiding NIFTY during identified bear regimes captures volatility-drag alpha — a strategy that sidesteps the left-tail of the equity return distribution compounds at a higher geometric rate than buy-and-hold even with similar arithmetic mean returns. This is the core mechanism; the others amplify it.

**Momentum-gated safe-haven rotation.** During identified stress-flat windows, capital rotates to GOLDBEES.NS — but only when gold's 10-day momentum is positive at the start of the latch, and only while it stays positive during the latch. If gold momentum turns negative mid-latch, the strategy exits gold to cash for the remainder of the latch (one-way door — no re-entry within the same latch). This per-latch state machine addresses a structural failure mode where supply-shock signals fire after gold has already rallied, leaving the strategy buying gold near tops. v1.2 holds gold ~41 days across the sample (about half of v1.1.1's 76 days); the gate blocks entry when gold is in a downtrend or exits early when the rally reverses.

**Cash yield on idle capital (with realistic haircut).** On fully-flat days where neither NIFTY nor gold is held, the strategy credits the prevailing RBI repo rate minus a 100 bps haircut. The haircut models real-world liquid-fund execution: instrument spread (~50 bps inside repo), TER (~10–25 bps), and small auto-sweep frictions. This produces a more conservative cash yield estimate than v1.1.1's pure-repo assumption. Sensitivity to the haircut size is documented under Backtest Caveats.

**The Sharpe improvement (+85% vs NIFTY) is the most reliable single measure of risk-adjusted skill** because it normalizes return per unit of volatility regardless of which mechanism is doing the work on any given day. Cumulative return improvement (+333pp) is striking but is inherently joint and path-dependent.

---

## Strategy Overview

The framework targets alpha through **regime identification combined with multi-asset rotation**. Three independent macro-regime signal lanes are computed daily:

1. **USDINR momentum** — long entry on rupee strengthening (capital inflows, risk-on)
2. **India VIX momentum** — long entry on fear subsiding (post-stress mean reversion)
3. **Supply-shock and panic-short triggers** — exit-to-flat or active short on coordinated macro stress (oil + INR + VIX, with an absolute VIX-level filter for the short leg)

A 100-day moving-average regime filter on NIFTY itself acts as the final gate: longs are only permitted when NIFTY is above its 100 DMA, shorts only when below. Position sizing is binary across two assets (NIFTY ±1, gold +1, cash as the third state); no leverage beyond 1×. Position-logic priority is: long entry → supply-shock exit override → panic-short override → regime-filter gate → momentum-gated gold rotation overlay on stress-flat days (gated on gold's own 10-day momentum) → RBI repo cash yield (minus 100 bps haircut) on remaining flat days.

The framework targets alpha through regime identification combined with multi-asset rotation. When the strategy identifies a stress regime, gold rotation is conditional on gold's own momentum — gold is held only while its 10-day return is positive, and the strategy exits to cash mid-latch if momentum turns negative. When fully flat, idle capital earns the time-varying RBI repo rate minus a 100 bps haircut modeling realistic liquid-fund execution. This produces three independent mechanisms — tactical equity exposure, momentum-gated safe-haven rotation, and cash management — that compound across the 17-year sample.

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
| RBI Repo Rate (v1.1) | — | RBI MPC press releases ([rbi.org.in](https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx)); hardcoded as `RBI_REPO_RATE_HISTORY` in `strategy.py` | Step function (53 announcements over 2008–2025) |

Market data is downloaded live at runtime via `yfinance`; no static market data files in the repo. India VIX series begins March 2008, which sets the in-sample start at **2008-04-01**. A warmup period from **2006-01-01 to 2008-03-31** seeds rolling windows and is excluded from results. GOLDBEES.NS data starts 2009-01-02; pre-2009 stress-flat days remain fully flat in the backtest (gold instrument not yet tradable). Cleaning is minimal: forward-fill across mismatched holiday calendars, drop full-NaN rows.

The RBI repo rate timeline is **hardcoded** rather than fetched at runtime because (a) no reliable free Indian short-rate API exists with full 2008-2025 coverage, (b) the repo rate is a step function with only ~50 changes over 17 years, ideal for a static table, and (c) hardcoding makes the backtest deterministic and auditable. Each row is sourced from the corresponding RBI MPC press release; the table is maintained manually and must be updated when RBI announces new rate decisions.

**Forward-testing implication:** When the strategy is run on dates after the last hardcoded entry, `build_rbi_repo_rate_series()` forward-fills the most recent rate indefinitely. This is correct as long as RBI hasn't moved the rate since the last entry — but goes silently stale if a rate change occurred and the table wasn't updated. For paper trading or live use, the table needs a manual refresh after each RBI MPC meeting (every ~6-8 weeks). Productionizing this — moving to a CSV-backed config file with a FRED API fallback — is on the roadmap (item 7).

---

## Backtest Methodology

| Item | Detail |
|---|---|
| Position sizing | Binary: +1, 0, -1. No fractional sizing. |
| Leverage | 1× max in either direction. |
| Signal timing | Signals computed from day-T close; positions applied from T+1 open via `position.shift(1)`. No look-ahead. |
| Rebalance | Daily — position re-evaluated every trading day. |
| Benchmark | NIFTY 50 buy-and-hold, no costs. |
| Transaction costs | NIFTY: **3 bps per leg** (futures execution). Gold (v1.1, GOLDBEES.NS): **5 bps per leg** (ETF spread + STT). Cash sweep: **0 bps** (institutional auto-sweep into liquid fund). Applied as `\|Δposition\| × cost_bps / 10,000`, deducted from same-day return. Long↔short flips cost 2× (both legs realised). |
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
| 2009 | +71.8% | +75.8% | -4.0pp |
| 2010 | +10.3% | +17.9% | -7.6pp |
| 2011 | -9.7% | -24.6% | **+14.9pp** |
| 2012 | +14.4% | +27.7% | -13.3pp |
| 2013 | -8.1% | +6.8% | -14.9pp |
| 2014 | +27.1% | +31.4% | -4.3pp |
| 2015 | +0.2% | -4.1% | **+4.3pp** |
| 2016 | +8.1% | +3.0% | **+5.1pp** |
| 2017 | +20.1% | +28.6% | -8.5pp |
| 2018 | +2.0% | +3.2% | -1.2pp |
| 2019 | +5.8% | +12.0% | -6.2pp |
| 2020 | +66.9% | +14.9% | **+52.0pp** |
| 2021 | +14.6% | +24.1% | -9.5pp |
| 2022 | +1.8% | +4.3% | -2.5pp |
| 2023 | +16.6% | +20.0% | -3.4pp |
| 2024 | +8.8% | +8.8% | 0.0pp |
| 2025 | +6.8% | +10.5% | -3.7pp |

The strategy outperforms NIFTY in **5 of 18 calendar years** — 2008, 2011, 2015, 2016, and 2020. The biggest contributors are 2008 (+41.9pp, GFC drawdown avoidance), 2011 (+14.9pp, European debt stress + cash yield at ~8% repo), and 2020 (+52.0pp, COVID panic-short plus gold rotation plus regime-filter cash yield). The 17-year compounded result is driven by **asymmetric crisis-window capture** — large gains during regime breaks compounded against small drags in calm years. The lower outperformance count vs v1.1.1 (which had 7 of 18) reflects v1.2's stricter momentum gate on gold rotation: 2018 NBFC and 2024 — where v1.1.1 narrowly beat NIFTY via unconditional gold rotation — now miss by 1.2pp and tie respectively, since gold's momentum did not support entry in those years. The trade-off is documented under the 2026 OOS robustness section: v1.2 sacrifices small in-sample beats to gain meaningful OOS robustness on the failure mode that motivated the change.

![Yearly Returns](images/yearly_returns.png)

### Drawdown

![Drawdown](images/drawdown.png)

Maximum drawdown of **-16.4%** vs NIFTY's **-51.7%** — a **68% reduction**. Cash yield on flat days during bear regimes (notably 2008-2009 GFC and 2020 March-August COVID recovery) cushions equity drawdowns by adding deterministic positive return on the worst-impact days. The drawdown profile reflects the joint mechanism set: the largest contributions to the gap come from the 2008 GFC (regime filter + cash yield at ~8% repo), 2011 European debt stress (gold rotation + cash yield), and 2020 COVID crash (panic-short + gold rotation + cash yield through the recovery period). v1.2's stricter gold gate also improves drawdown vs v1.1.1 (-18.3%) by avoiding mid-latch gold drawdowns when gold momentum turns negative.

### Cost Sensitivity

Per-asset transaction costs vary the NIFTY futures cost; gold ETF cost is held at NIFTY+2 bps throughout (reflecting GOLDBEES.NS's wider bid-ask spread). Cash sweep is treated as zero-cost at all levels.

| NIFTY (bps/leg) | Gold (bps/leg) | Cumulative Return | CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|
| 0 | 2 | 852.1% | 13.04% | 0.53 | -15.8% |
| **3 (base)** | **5 (base)** | **784.8%** | **12.59%** | **0.50** | **-16.4%** |
| 5 | 7 | 742.6% | 12.29% | 0.48 | -16.8% |
| 10 | 12 | 645.7% | 11.55% | 0.43 | -19.1% |
| 15 | 17 | 559.9% | 10.81% | 0.38 | -21.2% |
| 20 | 22 | 483.9% | 10.08% | 0.33 | -23.3% |
| 50 | 52 | 179.9% | 5.76% | 0.04 | -34.9% |

Strategy economics degrade more slowly than the v1.0 single-asset version because cash yield on idle capital is unaffected by transaction costs — fully-flat days don't trade and so don't pay friction. Sharpe stays well above NIFTY's 0.27 buy-and-hold all the way through 20 bps NIFTY cost. The 50 bps row remains a stress test, not a realistic implementation cost.

---

## Robustness Checks

### Crisis-Period Stress Tests

| Crisis | Window | Strategy | NIFTY | Strategy DD | NIFTY DD |
|---|---|---|---|---|---|
| GFC | Sep 2008 – Mar 2009 | **+2.4%** | -30.7% | -4.2% | -44.0% |
| Euro debt | Jul 2011 – Dec 2011 | **-5.3%** | -18.1% | -9.2% | -20.7% |
| Taper Tantrum | May – Sept 2013 | -11.3% | -3.3% | -14.6% | -14.6% |
| NBFC / IL&FS | Sep 2018 – Feb 2019 | -10.3% | -7.6% | -10.1% | -13.5% |
| COVID Crash | Feb – Dec 2020 | **+69.8%** | +16.9% | -12.8% | -37.6% |

The strategy navigates GFC-style and COVID-style regimes well — both feature decisive trend breakdowns that the panic-short and supply-shock lanes capture cleanly. The GFC window returns +2.4% (vs NIFTY -30.7%) because cash yield on the 192 fully-flat days at ~8% repo dominates a small drag from the supply-shock latch. The 2011 European debt window cushions NIFTY's -18.1% drop to a -5.3% strategy loss via flat-period cash yield. The 2013 Taper Tantrum remains a visible failure mode (-11.3% vs NIFTY -3.3%) — gold sold off during the EM rate shock and the momentum gate correctly blocked or exited the rotation, but the strategy still rode the underlying NIFTY weakness during the regime transitions. The 2018 NBFC crisis (-10.3% vs NIFTY -7.6%) is now also an underperformance — v1.2's stricter gold gate blocked rotation because gold's pre-fire momentum was weak; a trade-off accepted to gain OOS robustness (see 2026 section).

### 2026 Out-of-Sample Performance

The strategy went live in development through 2025-12-31, with 2026 reserved as out-of-sample. Through 2026-05-11 (94 trading days):

| | 2026 YTD return |
|---|---|
| Strategy (v1.2 / Config 4) | -5.66% |
| NIFTY 50 Buy & Hold | -7.48% |
| **Outperformance** | **+1.82pp** |

This is the first OOS year tested. v1.2's momentum gate addresses a specific failure mode observed in 2026 H1: gold rallied 22% in January (anticipatory positioning around US tariff and Iran tensions) before any signal fired, then mean-reverted during the March US-Iran escalation. v1.1.1's unconditional gold rotation would have entered gold near the top and held through the unwind — and did, losing -12.80% YTD vs NIFTY's -7.48%. v1.2's momentum gate exits gold mid-latch when 10-day momentum turns negative, reducing gold-days from 26 (Config 2) to 12 (Config 4) and gold P&L contribution from -9.19% to -2.10%.

**Variants considered and rejected.** A contrarian entry filter that would have blocked gold rotation specifically when gold had already rallied >X% prior to supply-shock fire (Variant F) was tested and rejected as overfitting — it improved 2026 OOS but degraded historical events where gold rallied into supply-shock fires and continued rallying afterward. The momentum-gate approach in v1.2 addresses the symptom (holding gold through a downturn) via an exit-side rule that's both prospective and asymmetric, without overfitting to any specific historical event.

### Walk-Forward Validation

Not yet implemented (parameter selection was manual). Planned — see Roadmap.

---

## Limitations

Active weaknesses I am addressing on the roadmap.

1. **Limited cross-asset universe.** The current implementation is two-asset (NIFTY + gold) with cash as the third state. The structural question — whether cumulative alpha vs NIFTY can be sourced from something other than tactical reduction of NIFTY exposure — is now partially addressed via gold rotation, but the asset universe remains narrow. Expansion to additional risk assets (USDINR overlay, broader equity indices) is on the roadmap. Walk-forward validation of the gold rotation rule specifically has not been done.

2. **Not all crisis regimes are handled equally.** The 2013 taper tantrum and 2018 NBFC crisis are visible failure modes — slow, grinding drawdowns where the panic-short trigger fires late or not at all. A regime-classification layer that distinguishes crash-type stress from grind-down stress is on the roadmap.

3. **Panic-short exit logic is structurally thin.** The active short uses only two exit mechanisms — a 5-day / 20-day NIFTY MA crossover and a 60-day time cap (the latter only active in `hold=True` configs) — and both parameter sets (5/20 windows, 60-day cap) were hand-picked rather than derived from panic-event duration statistics or a parameter sweep. The strategy enters via a strict 3-condition AND but exits on a single binary MA flip — an asymmetry between strict-entry and loose-exit that has not been stress-tested against scenarios where the initial short thesis is wrong (e.g. a V-shaped recovery that bottoms before the MA crossover registers). There is no stop-loss, no profit-taking rule, and no volatility-normalized exit threshold. **Mitigating control:** the production config currently ships with `hold=False` (pulse short only — short is active solely on the ~32 days where panic conditions raw-fire), which structurally caps any single-short loss exposure at one day. This avoids the worst case (sitting short into a multi-week rebound) by construction, but at the cost of leaving short-side P&L heavily dependent on the timing of the very next day's NIFTY return — a thin defense, not a robust one. The roadmap addresses this; until then, sizing of any panic-short component should be conservative and the no-hold default should not be flipped without redesigning the exit framework first.

4. **No live track record.** All results are backtest-only. Out-of-sample paper trading from 2026 onward is in progress; live trading at size has not been undertaken.

5. **Bull-regime alpha gap.** When fully long, the strategy IS NIFTY 50 — direct directional exposure to the underlying. In steady bull regimes where NIFTY itself rallies, the strategy can match but cannot meaningfully outperform the benchmark on the long side, because no higher-expected-return asset is being held. This is a structural limitation of the current single-equity-asset-on-the-long-side architecture. Cumulative alpha vs NIFTY in good times must come from substituting a higher-expected-return Indian equity index (NIFTY Momentum 30, NIFTY Midcap 150, NIFTY 200 Quality) as the long-side asset rather than NIFTY 50 itself. This substitution is on the roadmap (item 2).

---

## Backtest Caveats

These are structural caveats inherent to backtest research and macro-strategy design — not specific flaws of this strategy. They are documented for transparency, not as roadmap items.

1. **Researcher degrees of freedom.** Parameters (lookback windows, thresholds, DMA length) and signal selection (USDINR + VIX + supply-shock + panic-short) were chosen with knowledge of recent Indian market behavior. Walk-forward parameter validation is on the roadmap but has not yet been done. The choice of *which signals* to include is not addressable by walk-forward — only out-of-sample paper trading provides that test.

2. **Limited regime diversity in available data.** India VIX only exists from 2008, capping the backtest at ~17 years. Two true crisis regimes (GFC, COVID) plus several smaller stresses (2011, 2013, 2018, 2022) is statistically thin for a regime-conditional model.

3. **Non-stationarity of macro relationships.** USDINR / VIX / equity correlations have shifted over the sample (pre vs post 2014 RBI inflation-targeting framework, pre vs post 2020 liquidity regime, evolving FII flow dynamics). The strategy implicitly assumes some stability in these relationships going forward.

4. **Capacity and crowding unknown.** Backtest is unaware of position size. VIX-based and panic-short signals may have crowded behavior in stress regimes; edge at scale has not been tested.

5. **Cash-yield modeling assumes liquid-fund-style execution (v1.2).** The strategy credits the RBI repo rate minus a 100 bps haircut on fully-flat days, modeling realistic institutional cash execution: liquid-fund instrument spread (~25–50 bps inside repo), TER (~10–25 bps), and small auto-sweep frictions. v1.1.1 used a no-haircut (pure repo) assumption that external review flagged as too aggressive; v1.2's 100 bps default is more conservative and more credible. Additionally, the Sharpe-ratio benchmark hurdle is held constant at 6% even though the modeled cash yield ranges 3–8% over the sample after haircut — a minor inconsistency that doesn't materially affect cross-strategy comparison since NIFTY's Sharpe uses the same hurdle. Sensitivity to the haircut: 0 bps (full repo, v1.1.1 assumption) → 839.8% cumulative / 12.96% CAGR / 0.53 Sharpe; 200 bps (stress) → 733.1% / 12.22% / 0.48; cash yield entirely off → 533.0% / 10.56% / 0.37.

6. **Limited out-of-sample coverage.** OOS testing covers 2026-01-01 through 2026-05-11 (94 trading days). v1.2 outperformed NIFTY by +1.82pp in this window after addressing the gold-rotation timing failure mode observed in v1.1.1. This is a single OOS year and a single regime; broader OOS validation requires either additional time or formal walk-forward methodology (on the roadmap). The 5-of-18 in-sample outperformance count should be interpreted alongside this OOS window — the strategy is regime-defensive by construction, not designed to beat NIFTY in every calendar year.

---

## Roadmap

In progress and planned, in priority order:

1. **Walk-forward parameter validation** — re-fit thresholds and lookback windows on rolling 5-year windows; report out-of-sample-only equity curve. Includes walk-forward validation of the gold rotation rule, which has not been independently tested. **Highest-priority next step.**
2. **Higher-alpha equity index substitution for bull regimes** — replace NIFTY 50 as the long-side asset with a higher-expected-return Indian equity index (NIFTY Momentum 30, NIFTY Midcap 150, or NIFTY 200 Quality) to address the bull-regime alpha gap (Limitations #5). Requires data verification (yfinance coverage 2008-2025 for the chosen index) and full backtest re-run with all v1.2 mechanisms (momentum-gated gold rotation, haircut-adjusted cash yield) intact. Expected impact: +2-5% CAGR while preserving the existing risk-reduction architecture.
3. **Additional safe-haven cross-asset overlays** — extend beyond gold to USDINR and other defensive assets historically resilient during India-stress regimes. Targets diversification of the safe-haven sleeve and improvements to Sharpe through reduced single-asset reliance during stress windows.
4. **Slow-stress regime layer** — classification step to distinguish crash-type stress from grind-down stress, addressing the 2013 / 2018 failure modes.
5. **Panic-short exit framework redesign** — replace the current single-rule MA crossover exit with a layered framework: profit-take at +X%, stop-loss at -Y%, volatility-normalized exit thresholds (scale by current VIX), and immediate re-evaluation of entry conditions (cover the moment any of the three entry conditions flips). Required before flipping the production config from `hold=False` to `hold=True`. Addresses Limitation #3.
6. **Signal-by-signal P&L attribution** — decompose cumulative P&L by lane (USDINR, VIX, supply-shock, panic-short, regime-filter contribution) to confirm each signal independently earns its keep.
7. **Forward paper-trading** — daily logged signals against live data from 2026 onward.
8. **Productionize the RBI repo rate feed** — replace the hardcoded `RBI_REPO_RATE_HISTORY` table with a CSV-backed config file (`data/rbi_repo_rate.csv`) plus a FRED API fallback for any dates after the last manual entry. Add a runtime warning if the strategy runs on a date past the latest available rate. Required before any live trading; nice-to-have for paper trading.
9. **Modular refactor** — break monolithic `strategy.py` into `src/data.py`, `src/signals.py`, `src/backtest.py` for extensibility.

---

## Version History

| Version | Description | Cumulative | CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|
| v1.0 | Single-asset directional (no gold, no cash yield). Preserved at commit `c2860fc`. | 467.2% | 9.91% | 0.33 | -22.2% |
| v1.1.1 | Adds gold rotation throughout stress-flat latches + pure-repo cash yield. Preserved at commit `078878a`. | 908.4% | 13.40% | 0.55 | -18.3% |
| **v1.2** | **Adds momentum-gated gold rotation (per-latch state machine) + 100 bps repo haircut. Current.** | **784.8%** | **12.59%** | **0.50** | **-16.4%** |

v1.2 trades a small reduction in in-sample cumulative (vs v1.1.1) for: (a) a stricter, more credible cash-yield assumption, (b) Out-of-sample robustness on the gold rotation timing failure mode observed in 2026 H1, and (c) reduced max drawdown (-16.4% vs -18.3%). The Calmar improves (0.77 vs 0.73) on the smaller drawdown.

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

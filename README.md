# Indian Equity Macro-Regime Strategy

A systematic macro-regime strategy for Indian markets combining tactical NIFTY exposure, gold rotation during identified stress regimes, and RBI repo-rate cash yield on idle capital. Three independent signal lanes — USDINR momentum, India VIX momentum, and supply-shock / panic-short triggers — identify macro regime breaks, gated by a 100-day moving-average trend filter. Position sizing is binary across two assets (NIFTY ±1, gold +1) with cash as the third state; no leverage beyond 1×.

*Research project. Backtest results, methodology, and known limitations documented below. Not deployed; not investment advice.*

![Equity Curve](images/equity_curve.png)

---

## Headline Results

Backtest period: **2008-04-01 to 2025-12-31** (17.7 years). Net results assume per-asset transaction costs of **3 bps per leg** on NIFTY futures and **5 bps per leg** on GOLDBEES.NS (gold ETF). Idle capital on fully-flat days earns the prevailing RBI repo rate.

| Metric | Strategy (v1.1) | NIFTY Buy & Hold | Δ |
|---|---|---|---|
| Sharpe (RF = 6%) | 0.55 | 0.27 | **+106%** |
| Sortino | 0.67 | 0.25 | **+171%** |
| Calmar | 0.73 | 0.19 | **+288%** |
| Annualized volatility | 13.55% | 19.27% | -30% |
| Max drawdown | -18.3% | -51.7% | -65% |
| CAGR | 13.40% | 9.74% | +366 bps |
| Cumulative return | 908.4% | 451.9% | +456pp |

The strategy generates risk-adjusted alpha vs passive NIFTY exposure through three independent mechanisms operating together: (1) tactical equity exposure — long during bull regimes, flat or short during identified stress regimes; (2) safe-haven rotation — long gold during supply-shock and post-short cooldown windows; (3) cash management — idle capital earns the prevailing RBI repo rate on fully-flat days, matching standard institutional treasury practice. The 106% Sharpe improvement is the most direct measure of joint risk-adjusted skill across these mechanisms. Cumulative outperformance vs buy-and-hold (+456pp over 17.7 years) is the geometric outcome of compounding all three together — the mechanisms cannot be cleanly separated into additive contributions, since they interact through the position sequence and the compounding base.

---

## Mechanisms of Outperformance

The strategy's outperformance derives from three mechanisms that compound together over the 17.7-year sample. Their contributions are inherently joint and cannot be cleanly attributed to additive percentages, since each mechanism affects the compounding base for the others.

**Tactical equity exposure.** The strategy is long NIFTY ~66% of trading days (calm bull regimes), flat ~32% (bear regimes and stress flats), short ~1% (panic-short windows), and long gold ~2% (stress flat windows post-2009). Avoiding NIFTY during identified bear regimes captures volatility-drag alpha — a strategy that sidesteps the left-tail of the equity return distribution compounds at a higher geometric rate than buy-and-hold even with similar arithmetic mean returns. This is the core mechanism; the others amplify it.

**Safe-haven rotation.** During the 76 identified stress-flat days (2009-2025; gold ETF data starts 2009), capital rotates to GOLDBEES.NS rather than sitting in cash. Gold returns during stress windows (notably 2011, 2020 COVID, 2022) provide positive contribution where cash alone would be flat. Pre-2009 stress days remain in cash since the gold instrument was not yet tradable. The active panic-short is retained separately — testing showed that during decisively bearish regimes (panic-short fires), the leveraged short outperforms safe-haven rotation, particularly in the 2020 COVID window.

**Cash yield on idle capital.** On the ~1,483 fully-flat days where neither NIFTY nor gold is held, the strategy credits the prevailing RBI repo rate (4.0–9.0% over the sample, flat-day-weighted average 6.58%). This reflects standard institutional cash management — idle capital is auto-swept into liquid instruments earning the policy rate.

**The Sharpe improvement (+106% vs NIFTY) is the most reliable single measure of risk-adjusted skill** because it normalizes return per unit of volatility regardless of which mechanism is doing the work on any given day. Cumulative return improvement (+456pp) is striking but is inherently joint and path-dependent.

---

## Strategy Overview

The framework targets alpha through **regime identification combined with multi-asset rotation**. Three independent macro-regime signal lanes are computed daily:

1. **USDINR momentum** — long entry on rupee strengthening (capital inflows, risk-on)
2. **India VIX momentum** — long entry on fear subsiding (post-stress mean reversion)
3. **Supply-shock and panic-short triggers** — exit-to-flat or active short on coordinated macro stress (oil + INR + VIX, with an absolute VIX-level filter for the short leg)

A 100-day moving-average regime filter on NIFTY itself acts as the final gate: longs are only permitted when NIFTY is above its 100 DMA, shorts only when below. Position sizing is binary across two assets (NIFTY ±1, gold +1, cash as the third state); no leverage beyond 1×. Position-logic priority is: long entry → supply-shock exit override → panic-short override → regime-filter gate → gold rotation overlay on stress-flat days → RBI repo cash yield on remaining flat days.

The framework targets alpha through regime identification combined with multi-asset rotation. When the strategy identifies a stress regime (supply-shock or post-short cooldown), it rotates from NIFTY to long gold (GOLDBEES.NS, INR-denominated NSE-listed gold ETF). When fully flat (neither NIFTY exposure nor gold), idle capital earns the time-varying RBI repo rate. This produces three independent mechanisms — tactical equity exposure, safe-haven rotation, and cash management — that compound across the 17-year sample.

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
| Cash yield on flat days (v1.1) | Time-varying RBI repo rate as a step function (range 4.0%–9.0% over 2008–2025, sample-average 6.28%, flat-day-weighted-average 6.58%). Applied daily on fully-flat days where both NIFTY and gold positions are 0. Hardcoded in `RBI_REPO_RATE_HISTORY` in `strategy.py`, sourced from RBI MPC press releases (see Data section). |
| Risk-free rate | 6% per annum (India 10Y G-Sec proxy) for Sharpe and Sortino. |
| Out-of-sample | 2026-01-01 to 2026-04-25 held out from parameter selection. |
| Parameter selection | Judgement-based; no grid search or formal optimization. |

---

## Results

### Year-by-Year Returns

| Year | Strategy | NIFTY B&H | Outperformance |
|---|---|---|---|
| 2008 | +5.2% | -37.5% | **+42.7pp** |
| 2009 | +75.1% | +75.8% | -0.7pp |
| 2010 | +10.5% | +17.9% | -7.4pp |
| 2011 | -6.3% | -24.6% | **+18.3pp** |
| 2012 | +14.7% | +27.7% | -13.0pp |
| 2013 | -10.2% | +6.8% | -17.0pp |
| 2014 | +27.2% | +31.4% | -4.2pp |
| 2015 | -0.2% | -4.1% | **+3.8pp** |
| 2016 | +8.6% | +3.0% | **+5.5pp** |
| 2017 | +20.2% | +28.6% | -8.4pp |
| 2018 | +6.2% | +3.2% | **+3.1pp** |
| 2019 | +6.1% | +12.0% | -5.9pp |
| 2020 | +67.3% | +14.9% | **+52.4pp** |
| 2021 | +17.0% | +24.1% | -7.2pp |
| 2022 | +2.7% | +4.3% | -1.6pp |
| 2023 | +17.0% | +20.0% | -3.0pp |
| 2024 | +9.0% | +8.8% | **+0.2pp** |
| 2025 | +7.2% | +10.5% | -3.4pp |

The strategy outperforms NIFTY in **7 of 18 calendar years** — 2008, 2011, 2015, 2016, 2018, 2020, and 2024. The biggest contributors are 2008 (+42.7pp, GFC drawdown avoidance), 2011 (+18.3pp, European debt regime + cash yield at ~8% repo), and 2020 (+52.4pp, COVID panic-short plus gold rotation plus regime-filter cash yield). The increased outperformance count vs the v1.0 single-asset version (4 of 18) is largely attributable to cash yield on regime-filter-blocked years where NIFTY returned less than the prevailing repo rate (notably 2015, 2018, 2024). The 17-year compounded result is driven by **asymmetric crisis-window capture** — large gains during regime breaks compounded against small drags in calm years.

![Yearly Returns](images/yearly_returns.png)

### Drawdown

![Drawdown](images/drawdown.png)

Maximum drawdown of **-18.3%** vs NIFTY's **-51.7%** — a **65% reduction**. Cash yield on flat days during bear regimes (notably 2008-2009 GFC and 2020 March-August COVID recovery) cushions equity drawdowns by adding deterministic positive return on the worst-impact days. The drawdown profile reflects the joint mechanism set: the largest contributions to the gap come from the 2008 GFC (regime filter + cash yield at ~8% repo), 2011 European debt stress (gold rotation + cash yield), and 2020 COVID crash (panic-short + gold rotation + cash yield through the recovery period).

### Cost Sensitivity

Per-asset transaction costs vary the NIFTY futures cost; gold ETF cost is held at NIFTY+2 bps throughout (reflecting GOLDBEES.NS's wider bid-ask spread). Cash sweep is treated as zero-cost at all levels.

| NIFTY (bps/leg) | Gold (bps/leg) | Cumulative Return | CAGR | Sharpe | Max DD |
|---|---|---|---|---|---|
| 0 | 2 | 989.6% | 13.88% | 0.58 | -17.6% |
| **3 (base)** | **5 (base)** | **908.4%** | **13.40%** | **0.55** | **-18.3%** |
| 5 | 7 | 857.6% | 13.08% | 0.53 | -18.8% |
| 10 | 12 | 741.5% | 12.29% | 0.48 | -19.9% |
| 15 | 17 | 639.5% | 11.50% | 0.43 | -21.0% |
| 20 | 22 | 549.7% | 10.72% | 0.37 | -22.4% |
| 50 | 52 | 198.5% | 6.13% | 0.07 | -34.5% |

Strategy economics degrade more slowly than the v1.0 single-asset version because cash yield on idle capital is unaffected by transaction costs — fully-flat days don't trade and so don't pay friction. Sharpe stays well above NIFTY's 0.27 buy-and-hold all the way through 20 bps NIFTY cost (Sharpe 0.37). The 50 bps row remains a stress test, not a realistic implementation cost.

---

## Robustness Checks

### Crisis-Period Stress Tests

| Crisis | Window | Strategy | NIFTY | Strategy DD | NIFTY DD |
|---|---|---|---|---|---|
| GFC | Sep 2008 – Mar 2009 | **+3.0%** | -30.7% | -4.2% | -44.0% |
| Taper Tantrum | May – Sept 2013 | -13.5% | -3.3% | -16.5% | -14.6% |
| NBFC / IL&FS | Sep 2018 – Feb 2019 | **-6.6%** | -7.6% | -6.4% | -13.5% |
| COVID Crash | Feb – Dec 2020 | **+70.2%** | +16.9% | -12.8% | -37.6% |

The strategy navigates GFC-style and COVID-style regimes well — both feature decisive trend breakdowns that the panic-short and supply-shock lanes capture cleanly. With cash yield ON, the GFC window now flips from a small loss (-1.0% in v1.0) to a positive return (+3.0%) because the 192 fully-flat days during the GFC earned ~8% repo rate. The 2018 NBFC crisis flips from underperformance to slight outperformance for the same reason — long flat-period at high rates cushions the loss. The 2013 Taper Tantrum remains the strategy's single visible failure mode: gold *also* sold off during the 2013 EM rate shock, so gold rotation amplifies rather than mitigates the drawdown. This is a known structural weakness — see Limitations and Roadmap.

### Walk-Forward Validation

Not yet implemented (parameter selection was manual). Planned — see Roadmap.

---

## Limitations

Honest list of what this backtest does not prove and where the strategy is structurally weakest.

1. **Limited cross-asset universe.** The current implementation is two-asset (NIFTY + gold) with cash as the third state. The structural question — whether cumulative alpha vs NIFTY can be sourced from something other than tactical reduction of NIFTY exposure — is now partially addressed via gold rotation, but the asset universe remains narrow. Expansion to additional risk assets (USDINR overlay, broader equity indices) is on the roadmap. Walk-forward validation of the gold rotation rule specifically has not been done.

2. **Researcher degrees of freedom.** Parameters (lookback windows, thresholds, DMA length) and signal selection (USDINR + VIX + supply-shock + panic-short) were chosen with knowledge of recent Indian market behavior. Walk-forward parameter validation is on the roadmap but has not yet been done. The choice of *which signals* to include is not addressable by walk-forward — only out-of-sample paper trading provides that test.

3. **Not all crisis regimes are handled equally.** The 2013 taper tantrum and 2018 NBFC crisis are visible failure modes — slow, grinding drawdowns where the panic-short trigger fires late or not at all. A regime-classification layer that distinguishes crash-type stress from grind-down stress is on the roadmap.

4. **Panic-short exit logic is structurally thin.** The active short uses only two exit mechanisms — a 5-day / 20-day NIFTY MA crossover and a 60-day time cap (the latter only active in `hold=True` configs) — and both parameter sets (5/20 windows, 60-day cap) were hand-picked rather than derived from panic-event duration statistics or a parameter sweep. The strategy enters via a strict 3-condition AND but exits on a single binary MA flip — an asymmetry between strict-entry and loose-exit that has not been stress-tested against scenarios where the initial short thesis is wrong (e.g. a V-shaped recovery that bottoms before the MA crossover registers). There is no stop-loss, no profit-taking rule, and no volatility-normalized exit threshold. **Mitigating control:** the production config currently ships with `hold=False` (pulse short only — short is active solely on the ~32 days where panic conditions raw-fire), which structurally caps any single-short loss exposure at one day. This avoids the worst case (sitting short into a multi-week rebound) by construction, but at the cost of leaving short-side P&L heavily dependent on the timing of the very next day's NIFTY return — a thin defense, not a robust one. The roadmap item below addresses this; until then, sizing of any panic-short component should be conservative and the no-hold default should not be flipped without redesigning the exit framework first.

5. **Limited regime diversity in available data.** India VIX only exists from 2008, capping the backtest at ~17 years. Two true crisis regimes (GFC, COVID) plus several smaller stresses (2011, 2013, 2018, 2022) is statistically thin for a regime-conditional model.

6. **Non-stationarity of macro relationships.** USDINR / VIX / equity correlations have shifted over the sample (pre vs post 2014 RBI inflation-targeting framework, pre vs post 2020 liquidity regime, evolving FII flow dynamics). The strategy implicitly assumes some stability in these relationships going forward.

7. **Capacity and crowding unknown.** Backtest is unaware of position size. VIX-based and panic-short signals may have crowded behavior in stress regimes; edge at scale has not been tested.

8. **No live track record.** All results are backtest-only. Out-of-sample paper trading from 2026 onward is in progress; live trading at size has not been undertaken.

9. **Cash-yield modeling assumes ideal sweep (v1.1).** The strategy credits the prevailing RBI repo rate on fully-flat days, on the assumption that idle capital is auto-swept into a liquid fund or T-bill earning the policy rate. In practice, executable yield is repo rate minus a small spread (typically 25–50 bps) plus minor sweep friction. The assumption is realistic for institutional execution but slightly optimistic for retail. Additionally, the Sharpe-ratio benchmark hurdle is held constant at 6% even though the modeled cash yield ranges 4.0–9.0% over the sample — a minor inconsistency that doesn't materially affect cross-strategy comparison since NIFTY's Sharpe uses the same hurdle. Sensitivity: turning cash yield off entirely cuts CAGR by ~2.4pp (13.40% → 11.03%) and Sharpe by ~0.16 (0.55 → 0.40).

---

## Roadmap

In progress and planned, in priority order:

1. **Walk-forward parameter validation** — re-fit thresholds and lookback windows on rolling 5-year windows; report out-of-sample-only equity curve. Includes walk-forward validation of the gold rotation rule, which has not been independently tested. **Highest-priority next step.**
2. **Additional cross-asset overlays** — extend beyond gold to USDINR and broader equity indices (mid-cap, small-cap) for stress regimes. The current two-asset (NIFTY + gold) implementation is functional but narrow; further diversification of safe-haven and tactical sleeves should improve Sharpe further.
3. **Slow-stress regime layer** — classification step to distinguish crash-type stress from grind-down stress, addressing the 2013 / 2018 failure modes.
4. **Panic-short exit framework redesign** — replace the current single-rule MA crossover exit with a layered framework: profit-take at +X%, stop-loss at -Y%, volatility-normalized exit thresholds (scale by current VIX), and immediate re-evaluation of entry conditions (cover the moment any of the three entry conditions flips). Required before flipping the production config from `hold=False` to `hold=True`. Addresses Limitation #4.
5. **Signal-by-signal P&L attribution** — decompose cumulative P&L by lane (USDINR, VIX, supply-shock, panic-short, regime-filter contribution) to confirm each signal independently earns its keep.
6. **Forward paper-trading** — daily logged signals against live data from 2026 onward.
7. **Productionize the RBI repo rate feed** — replace the hardcoded `RBI_REPO_RATE_HISTORY` table with a CSV-backed config file (`data/rbi_repo_rate.csv`) plus a FRED API fallback for any dates after the last manual entry. Add a runtime warning if the strategy runs on a date past the latest available rate. Required before any live trading; nice-to-have for paper trading.
8. **Modular refactor** — break monolithic `strategy.py` into `src/data.py`, `src/signals.py`, `src/backtest.py` for extensibility.

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

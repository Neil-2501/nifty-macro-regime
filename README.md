# Indian Equity Macro-Regime Strategy

A systematic macro-regime strategy targeting risk-adjusted alpha on NIFTY directional exposure. Three independent signal lanes — USDINR momentum, India VIX momentum, and supply-shock / panic-short triggers — identify macro regime breaks, gated by a 100-day moving-average trend filter. Position sizing is binary long / flat / short; no leverage beyond 1×.

*Research project. Backtest results, methodology, and known limitations documented below. Not deployed; not investment advice.*

![Equity Curve](images/equity_curve.png)

---

## Headline Results

Backtest period: **2008-04-01 to 2025-12-31** (17.7 years). Net results assume **3 bps per leg** transaction cost on NIFTY futures, the realistic execution assumption for institutional sizing.

| Metric | Strategy (3 bps) | NIFTY Buy & Hold | Δ |
|---|---|---|---|
| Sharpe (RF = 6%) | 0.33 | 0.27 | **+22%** |
| Sortino | 0.36 | 0.25 | **+44%** |
| Calmar | 0.45 | 0.19 | **+137%** |
| Annualized volatility | 13.26% | 19.27% | -31% |
| Max drawdown | -22.2% | -51.7% | -57% |
| CAGR | 9.91% | 9.74% | +17 bps |
| Cumulative return | 467.2% | 451.9% | +15.3pp |

The strategy generates risk-adjusted alpha relative to passive NIFTY exposure: a **22% improvement in Sharpe**, **44% in Sortino**, and **137% in Calmar**, with annualized volatility cut by nearly a third and maximum drawdown more than halved. Absolute compounding is comparable to buy-and-hold; the alpha is expressed through a materially different return *distribution* — the strategy correctly identifies regime breaks and steps aside or inverts directional exposure in 2008 GFC, 2011 European debt stress, and 2020 COVID, booking outperformance in those windows while tracking close to the index in calm regimes.

---

## Strategy Overview

The framework targets alpha through **regime identification**, not continuous directional prediction. Three independent macro-regime signal lanes are computed daily:

1. **USDINR momentum** — long entry on rupee strengthening (capital inflows, risk-on)
2. **India VIX momentum** — long entry on fear subsiding (post-stress mean reversion)
3. **Supply-shock and panic-short triggers** — exit-to-flat or active short on coordinated macro stress (oil + INR + VIX, with an absolute VIX-level filter for the short leg)

A 100-day moving-average regime filter on NIFTY itself acts as the final gate: longs are only permitted when NIFTY is above its 100 DMA, shorts only when below. Position sizing is binary (+1 / 0 / -1), with no leverage beyond 1×. Position-logic priority is: long entry → supply-shock exit override → panic-short override → regime-filter gate.

The alpha is sourced from accurately identifying when to step aside from or invert directional exposure. By construction, a single-asset long / flat / short strategy cannot outperform a fully-invested benchmark in steady up regimes — its alpha against the underlying *must* be sourced from regime breaks. The roadmap (cross-asset expansion) addresses this structural scope through additional alpha sources independent of NIFTY direction.

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

Data is downloaded live at runtime; no static data files in the repo. India VIX series begins March 2008, which sets the in-sample start at **2008-04-01**. A warmup period from **2006-01-01 to 2008-03-31** seeds rolling windows and is excluded from results. Cleaning is minimal: forward-fill across mismatched holiday calendars, drop full-NaN rows.

---

## Backtest Methodology

| Item | Detail |
|---|---|
| Position sizing | Binary: +1, 0, -1. No fractional sizing. |
| Leverage | 1× max in either direction. |
| Signal timing | Signals computed from day-T close; positions applied from T+1 open via `position.shift(1)`. No look-ahead. |
| Rebalance | Daily — position re-evaluated every trading day. |
| Benchmark | NIFTY 50 buy-and-hold, no costs. |
| Transaction costs | Base case **3 bps per leg**. Applied as `\|Δposition\| × cost_bps / 10,000`, deducted from same-day return. Long↔short flips cost 2× (both legs realised). |
| Risk-free rate | 6% per annum (India 10Y G-Sec proxy) for Sharpe and Sortino. |
| Out-of-sample | 2026-01-01 to 2026-04-25 held out from parameter selection. |
| Parameter selection | Judgement-based; no grid search or formal optimization. |

---

## Results

### Year-by-Year Returns

| Year | Strategy | NIFTY B&H | Outperformance |
|---|---|---|---|
| 2008 | -1.1% | -37.5% | **+36.4pp** |
| 2009 | +69.5% | +75.8% | -6.3pp |
| 2010 | +9.5% | +17.9% | -8.5pp |
| 2011 | -14.0% | -24.6% | **+10.6pp** |
| 2012 | +12.6% | +27.7% | -15.1pp |
| 2013 | -9.1% | +6.8% | -15.9pp |
| 2014 | +26.3% | +31.4% | -5.1pp |
| 2015 | -5.5% | -4.1% | -1.5pp |
| 2016 | +5.8% | +3.0% | +2.8pp |
| 2017 | +19.6% | +28.6% | -9.0pp |
| 2018 | -0.3% | +3.2% | -3.4pp |
| 2019 | +4.3% | +12.0% | -7.8pp |
| 2020 | +51.5% | +14.9% | **+36.6pp** |
| 2021 | +14.2% | +24.1% | -9.9pp |
| 2022 | +0.1% | +4.3% | -4.3pp |
| 2023 | +14.6% | +20.0% | -5.5pp |
| 2024 | +7.6% | +8.8% | -1.2pp |
| 2025 | +4.9% | +10.5% | -5.6pp |

The strategy outperforms NIFTY in 4 of 18 calendar years — 2008, 2011, 2016, 2020 — with three (2008, 2011, 2020) accounting for the bulk of cumulative alpha. This concentration is the structural signature of a single-asset directional strategy: alpha vs NIFTY can only be sourced from periods of underweight or short exposure during NIFTY drawdowns, since fully-long is already the maximum achievable position. The 17-year cumulative parity is achieved through asymmetry — small drag in calm years compounded into large gain capture in regime breaks. Cross-asset expansion (see Roadmap) is the structural response, adding alpha sources independent of NIFTY direction.

![Yearly Returns](images/yearly_returns.png)

### Drawdown

![Drawdown](images/drawdown.png)

Maximum drawdown of **-22.2%** vs NIFTY's **-51.7%** — a 57% reduction. The drawdown profile reflects the regime-identification thesis: the largest contributions to the gap come from the 2008 GFC, 2011 European debt stress, and 2020 COVID crash — the windows where the panic-short and supply-shock triggers fire cleanly.

### Cost Sensitivity

| Cost (bps/leg) | Cumulative Return | CAGR | Sharpe | Max DD |
|---|---|---|---|---|
| 0 | 506.0% | 10.30% | 0.35 | -21.0% |
| **3 (base)** | **467.2%** | **9.91%** | **0.33** | **-22.2%** |
| 5 | 442.8% | 9.64% | 0.31 | -22.9% |
| 10 | 386.2% | 8.99% | 0.26 | -24.8% |
| 15 | 335.4% | 8.34% | 0.22 | -26.6% |
| 20 | 289.9% | 7.69% | 0.17 | -28.3% |
| 50 | 100.9% | 3.87% | -0.09 | -38.0% |

The base 3 bps assumption reflects realistic NIFTY futures execution for institutional sizing. Strategy economics degrade meaningfully above ~15 bps, where Sharpe falls below NIFTY's 0.27 buy-and-hold. The 50 bps row is a stress test, not a realistic implementation cost.

---

## Robustness Checks

### Crisis-Period Stress Tests

| Crisis | Window | Strategy | NIFTY | Strategy DD | NIFTY DD |
|---|---|---|---|---|---|
| GFC | Sep 2008 – Mar 2009 | **-1.0%** | -30.7% | -4.2% | -44.0% |
| Taper Tantrum | May – Sept 2013 | -11.4% | -3.3% | -14.7% | -14.6% |
| NBFC / IL&FS | Sep 2018 – Feb 2019 | -11.9% | -7.6% | -11.6% | -13.5% |
| COVID Crash | Feb – Dec 2020 | **+54.1%** | +16.9% | -15.5% | -37.6% |

The strategy navigates GFC-style and COVID-style regimes well — both feature decisive trend breakdowns that the panic-short and supply-shock lanes capture cleanly. The 2013 taper tantrum and 2018 NBFC crisis were *not* well-handled: the strategy underperformed buy-and-hold in both. These are slower, more mean-reverting drawdowns where the panic-short trigger fires late or not at all, leaving the strategy short or flat into mid-window rebounds. This is a known weakness — see Limitations and Roadmap.

### Walk-Forward Validation

Not yet implemented (parameter selection was manual). Planned — see Roadmap.

---

## Limitations

Honest list of what this backtest does not prove and where the strategy is structurally weakest.

1. **Single-asset directional scope limits alpha sourcing.** By construction, a long / flat / short NIFTY-only strategy cannot outperform NIFTY in steady up regimes — fully-long is already the maximum achievable position. Alpha vs NIFTY is therefore necessarily sourced from correctly stepping aside or inverting during regime breaks. This is the structural reason for the concentrated outperformance pattern (4 of 18 years). Cross-asset expansion — adding gold and USDINR overlays during identified recession or supply-shock regimes — is the planned response and is the highest-priority roadmap item, since it adds an alpha source independent of NIFTY direction.

2. **Researcher degrees of freedom.** Parameters (lookback windows, thresholds, DMA length) and signal selection (USDINR + VIX + supply-shock + panic-short) were chosen with knowledge of recent Indian market behavior. Walk-forward parameter validation is on the roadmap but has not yet been done. The choice of *which signals* to include is not addressable by walk-forward — only out-of-sample paper trading provides that test.

3. **Not all crisis regimes are handled equally.** The 2013 taper tantrum and 2018 NBFC crisis are visible failure modes — slow, grinding drawdowns where the panic-short trigger fires late or not at all. A regime-classification layer that distinguishes crash-type stress from grind-down stress is on the roadmap.

4. **Limited regime diversity in available data.** India VIX only exists from 2008, capping the backtest at ~17 years. Two true crisis regimes (GFC, COVID) plus several smaller stresses (2011, 2013, 2018, 2022) is statistically thin for a regime-conditional model.

5. **Non-stationarity of macro relationships.** USDINR / VIX / equity correlations have shifted over the sample (pre vs post 2014 RBI inflation-targeting framework, pre vs post 2020 liquidity regime, evolving FII flow dynamics). The strategy implicitly assumes some stability in these relationships going forward.

6. **Capacity and crowding unknown.** Backtest is unaware of position size. VIX-based and panic-short signals may have crowded behavior in stress regimes; edge at scale has not been tested.

7. **No live track record.** All results are backtest-only. Out-of-sample paper trading from 2026 onward is in progress; live trading at size has not been undertaken.

---

## Roadmap

In progress and planned, in priority order:

1. **Cross-asset extension** — gold and USDINR overlays during identified recession or supply-shock regimes. Adds an alpha source independent of NIFTY direction, addressing the structural single-asset scope limit. **Highest-priority next step.**
2. **Walk-forward parameter validation** — re-fit thresholds and lookback windows on rolling 5-year windows; report out-of-sample-only equity curve.
3. **Slow-stress regime layer** — classification step to distinguish crash-type stress from grind-down stress, addressing the 2013 / 2018 failure modes.
4. **Signal-by-signal P&L attribution** — decompose cumulative P&L by lane (USDINR, VIX, supply-shock, panic-short, regime-filter contribution) to confirm each signal independently earns its keep.
5. **Forward paper-trading** — daily logged signals against live data from 2026 onward.
6. **Modular refactor** — break monolithic `strategy.py` into `src/data.py`, `src/signals.py`, `src/backtest.py` for extensibility.

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

# Experiments

Research scaffolding for tested-but-not-adopted variants of the production strategy. Scripts here do NOT modify `strategy.py` or affect production results; they apply variant logic via post-processing and report comparative metrics.

## Scripts

- **`test_entry_signal_gate.py`** — Tests a variant where USDINR or VIX momentum must fire during a flat period before re-engaging long. Backtested over the full 2008-2025 sample; produced 16.49% CAGR / 0.78 Sharpe vs production's 18.08% / 0.83. Documented under "Tested But Not Adopted" in the main README.

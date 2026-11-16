"""Download liquid-fund NAV history used for the strategy's idle-cash return.

Writes data/liquid_fund_navs.parquet with one NAV column per fund (date index).
Source: api.mfapi.in (AMFI NAV history). Regular-plan growth options are used
so the series reflects fund expenses (TER), i.e. a conservative real-world
cash return.

Funds:
  100835  Kotak Liquid Fund - Regular Plan - Growth
  100851  Nippon India Liquid Fund - Regular Plan - Growth

Both NAV series contain one unit/face-value change (a ~100x one-day jump);
strategy.py neutralises single-day moves larger than 5% when converting NAVs
to returns, so the raw NAVs are stored unchanged here.
"""
import os

import pandas as pd
import requests

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(REPO_ROOT, "data", "liquid_fund_navs.parquet")
FUNDS = {"kotak_liquid": 100835, "nippon_liquid": 100851}


def fetch(code: int) -> pd.Series:
    j = requests.get(f"https://api.mfapi.in/mf/{code}", timeout=30).json()
    d = pd.DataFrame(j["data"])
    d["date"] = pd.to_datetime(d["date"], format="%d-%m-%Y")
    d["nav"] = pd.to_numeric(d["nav"], errors="coerce")
    s = d.set_index("date")["nav"].sort_index().dropna()
    return s[s > 0]


def main():
    navs = pd.DataFrame({name: fetch(code) for name, code in FUNDS.items()})
    navs.index.name = "date"
    navs.to_parquet(OUT)
    print(f"Wrote {OUT}: {navs.index.min().date()} → {navs.index.max().date()}, {len(navs)} rows")


if __name__ == "__main__":
    main()

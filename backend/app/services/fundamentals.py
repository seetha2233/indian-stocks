"""Fundamentals snapshot from Yahoo Finance, and a 0-100 fundamental score.

The snapshot is today's values only (no history), so the fundamental score
can't be backtested and is not a model input. It's context for the signal.
"""

import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import text
from sqlalchemy.engine import Engine


FUNDAMENTALS_TABLE = "stock_fundamentals"

FIELDS = {
    "sector": "sector",
    "industry": "industry",
    "long_name": "longName",
    "market_cap": "marketCap",
    "pe": "trailingPE",
    "forward_pe": "forwardPE",
    "pb": "priceToBook",
    "roe": "returnOnEquity",
    "profit_margin": "profitMargins",
    "operating_margin": "operatingMargins",
    "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth",
    "debt_to_equity": "debtToEquity",
    "dividend_yield": "dividendYield",
    "beta": "beta",
    "book_value": "bookValue",
    "eps": "trailingEps",
}

# metric -> True if higher is better
PILLARS = {
    "valuation": {"pe": False, "pb": False},
    "quality": {"roe": True, "profit_margin": True, "operating_margin": True},
    "growth": {"revenue_growth": True, "earnings_growth": True},
    "leverage": {"debt_to_equity": False},
}

# Rank within sector only when it has enough peers
MIN_SECTOR_PEERS = 5

# Leverage isn't comparable for lenders (debt is their raw material)
NO_LEVERAGE_SECTORS = {"Financial Services"}


def _fetch_one(symbol: str, retries: int = 3) -> dict:

    info: dict = {}

    for attempt in range(1, retries + 1):
        try:
            info = yf.Ticker(symbol).info or {}
            break
        except Exception:
            time.sleep(2 * attempt)

    row = {"symbol": symbol}
    row.update({col: info.get(key) for col, key in FIELDS.items()})

    return row


TEXT_FIELDS = ("sector", "industry", "long_name")

CACHE_CSV = Path(__file__).resolve().parents[3] / "data" / "cache" / "fundamentals_raw.csv"

# Fundamentals change quarterly; reuse a lookup for this long
MAX_AGE_DAYS = 7


def _load_cache() -> pd.DataFrame:

    if not CACHE_CSV.exists():
        return pd.DataFrame(columns=["symbol", "fetched_at"])

    return pd.read_csv(CACHE_CSV, parse_dates=["fetched_at"])


def fetch_fundamentals(
    symbols: list[str],
    workers: int = 4,
    progress_every: int = 250,
    max_age_days: int = MAX_AGE_DAYS,
) -> pd.DataFrame:
    """Yahoo lookups for symbols not fetched in the last max_age_days.

    More than ~4 workers trips Yahoo's rate limit (HTTP 429), after which
    yfinance backs off silently. Results are appended to CACHE_CSV as they
    arrive, so an interrupted run keeps its progress.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed

    cache = _load_cache()
    fresh = cache[cache["fetched_at"] >= datetime.now() - timedelta(days=max_age_days)]
    todo = [s for s in symbols if s not in set(fresh["symbol"])]

    print(f"  {len(symbols) - len(todo)} cached (< {max_age_days} days old), fetching {len(todo)}", flush=True)

    CACHE_CSV.parent.mkdir(parents=True, exist_ok=True)
    header = not CACHE_CSV.exists()

    with ThreadPoolExecutor(max_workers=workers) as pool:

        futures = [pool.submit(_fetch_one, s) for s in todo]

        for n, future in enumerate(as_completed(futures), start=1):

            row = {**future.result(), "fetched_at": datetime.now()}
            pd.DataFrame([row]).to_csv(CACHE_CSV, mode="a", header=header, index=False)
            header = False

            if n % progress_every == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}", flush=True)

    df = (
        _load_cache()
        .sort_values("fetched_at")
        .drop_duplicates("symbol", keep="last")
    )
    df = df[df["symbol"].isin(symbols)].reset_index(drop=True)

    # Yahoo sometimes returns text ("Infinity", "") for numbers
    for col in FIELDS:
        if col not in TEXT_FIELDS:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.replace([np.inf, -np.inf], np.nan)

    # Yahoo rarely reports ROE for Indian stocks; derive it as EPS / book
    # value per share where it's missing
    derived = df["eps"] / df["book_value"].where(df["book_value"] > 0)
    df["roe"] = df["roe"].fillna(derived)

    return df


def _percentile(values: pd.Series, higher_is_better: bool) -> pd.Series:

    n = values.notna().sum()

    if n == 0:
        return values

    ranks = values.rank(pct=True)

    return ranks if higher_is_better else 1 - ranks + 1 / n


def fundamental_scores(df: pd.DataFrame) -> pd.DataFrame:
    """0-100 scores per pillar and overall, relative to sector peers."""

    df = df.copy()

    # A negative P/E means losses: treat as the most expensive
    df["pe"] = df["pe"].where(df["pe"] > 0, np.inf)
    df.loc[df["pe"].isna(), "pe"] = np.nan

    df.loc[df["sector"].isin(NO_LEVERAGE_SECTORS), "debt_to_equity"] = np.nan

    sector_size = df.groupby("sector")["symbol"].transform("count")
    peer_group = df["sector"].where(sector_size >= MIN_SECTOR_PEERS, "_all")

    out = df[["symbol"]].copy()

    for pillar, metrics in PILLARS.items():

        parts = []

        for metric, higher_better in metrics.items():

            pct = df.groupby(peer_group)[metric].transform(
                lambda s: _percentile(s, higher_better)
            )

            parts.append(pct)

        out[f"{pillar}_score"] = pd.concat(parts, axis=1).mean(axis=1) * 100

    pillar_cols = [f"{p}_score" for p in PILLARS]

    out["fundamental_score"] = out[pillar_cols].mean(axis=1)

    return out


def save_fundamentals(engine: Engine, df: pd.DataFrame) -> None:

    with engine.begin() as conn:
        df.to_sql(FUNDAMENTALS_TABLE, conn, if_exists="replace", index=False)


def load_fundamentals(engine: Engine) -> pd.DataFrame:

    return pd.read_sql(text(f"SELECT * FROM {FUNDAMENTALS_TABLE}"), engine)

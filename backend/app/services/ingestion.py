from datetime import datetime

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import StockPrice
from app.services.market_data import (
    MarketDataProvider,
    YahooMarketDataProvider
)


BATCH_SIZE = 1000

# Never store more than 6 months of history per stock
ALLOWED_PERIODS = ("1mo", "3mo", "6mo")
DEFAULT_PERIOD = "6mo"
MAX_HISTORY = pd.DateOffset(months=6)

# Symbols per Yahoo batch request
DOWNLOAD_BATCH = 100


def normalize_symbol(symbol: str) -> str:

    symbol = symbol.strip().upper()

    if not symbol.endswith((".NS", ".BO")):
        symbol = f"{symbol}.NS"

    return symbol


def to_rows(symbol: str, df: pd.DataFrame) -> list[dict]:

    df = df.dropna(subset=["Open", "High", "Low", "Close"])

    # Yahoo emits flat zero-volume placeholder bars on holidays/suspensions
    df = df[df["Volume"] > 0]

    # yfinance may return tz-aware IST timestamps; store the naive date
    timestamps = pd.to_datetime(df["Date"])
    if timestamps.dt.tz is not None:
        timestamps = timestamps.dt.tz_localize(None)

    return [
        {
            "symbol": symbol,
            "timestamp": ts.to_pydatetime(),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "adj_close": (
                float(row["Adj Close"])
                if pd.notna(row.get("Adj Close"))
                else None
            ),
            "volume": float(row["Volume"]),
        }
        for ts, (_, row) in zip(timestamps, df.iterrows())
    ]


def _upsert(db: Session, rows: list[dict]) -> None:

    for start in range(0, len(rows), BATCH_SIZE):

        stmt = insert(StockPrice).values(rows[start:start + BATCH_SIZE])

        stmt = stmt.on_conflict_do_update(
            constraint="uq_stock_timestamp",
            set_={
                col: stmt.excluded[col]
                for col in (
                    "open", "high", "low", "close",
                    "adj_close", "volume"
                )
            }
        )

        db.execute(stmt)


def _check_period(period: str) -> None:

    if period not in ALLOWED_PERIODS:
        raise ValueError(
            f"period must be one of {ALLOWED_PERIODS}, got {period!r}"
        )


def prune_old(db: Session) -> int:
    """Keep a rolling 6-month window as new days get added over time."""

    cutoff = (pd.Timestamp(datetime.now()) - MAX_HISTORY).normalize()

    result = db.execute(
        delete(StockPrice).where(StockPrice.timestamp < cutoff.to_pydatetime())
    )

    db.commit()

    return result.rowcount


def ingest_history(
    db: Session,
    symbol: str,
    period: str = DEFAULT_PERIOD,
    provider: MarketDataProvider | None = None
) -> int:
    """Fetch daily history for one stock and upsert it into stock_prices.

    Safe to re-run: existing (symbol, timestamp) rows are updated.
    """

    _check_period(period)

    provider = provider or YahooMarketDataProvider()

    symbol = normalize_symbol(symbol)

    rows = to_rows(symbol, provider.get_history(symbol=symbol, period=period))

    _upsert(db, rows)
    db.commit()

    return len(rows)


def ingest_many(
    db: Session,
    symbols: list[str],
    period: str = DEFAULT_PERIOD,
    on_batch=None
) -> tuple[dict[str, int], list[str]]:
    """Batch-download and upsert many stocks.

    Returns ({symbol: bars}, [symbols with no data]).
    """

    _check_period(period)

    provider = YahooMarketDataProvider()

    symbols = [normalize_symbol(s) for s in symbols]

    counts: dict[str, int] = {}
    missing: list[str] = []

    for start in range(0, len(symbols), DOWNLOAD_BATCH):

        batch = symbols[start:start + DOWNLOAD_BATCH]

        histories = provider.get_history_many(batch, period=period)

        for symbol in batch:

            rows = to_rows(symbol, histories[symbol]) if symbol in histories else []

            if not rows:
                missing.append(symbol)
                continue

            _upsert(db, rows)
            counts[symbol] = len(rows)

        db.commit()

        if on_batch:
            on_batch(start + len(batch), len(symbols))

    return counts, missing

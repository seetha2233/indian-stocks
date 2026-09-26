import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.core.cache import cached
from app.db.database import engine
from app.services.ingestion import normalize_symbol
from app.services.signals import SIGNALS_TABLE


router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("")
@cached(ttl=3600)
def list_stocks():
    """All stocks with a card today, for search boxes."""

    df = pd.read_sql(
        text(
            f"SELECT symbol, long_name, sector, industry, market_cap "
            f"FROM {SIGNALS_TABLE} WHERE timestamp = "
            f"(SELECT max(timestamp) FROM {SIGNALS_TABLE}) "
            f"ORDER BY market_cap DESC NULLS LAST"
        ),
        engine
    )

    df["symbol"] = df["symbol"].str.removesuffix(".NS")

    df = df.rename(columns={"long_name": "name"})

    return df.astype(object).where(df.notna(), None).to_dict("records")


@router.get("/{symbol}/history")
@cached(ttl=300)
def history(symbol: str, days: int = Query(250, ge=20, le=520)):
    """Daily OHLCV (as traded, not adjusted) plus 20/50-day averages."""

    symbol = normalize_symbol(symbol)

    df = pd.read_sql(
        text(
            "SELECT timestamp, open, high, low, close, volume "
            "FROM stock_prices WHERE symbol = :s ORDER BY timestamp"
        ),
        engine,
        params={"s": symbol},
        parse_dates=["timestamp"]
    )

    if df.empty:
        raise HTTPException(404, f"No price history for {symbol}")

    df["sma_20"] = df["close"].rolling(20).mean()
    df["sma_50"] = df["close"].rolling(50).mean()

    df = df.tail(days)
    df["date"] = df["timestamp"].dt.strftime("%Y-%m-%d")

    cols = ["date", "open", "high", "low", "close", "volume", "sma_20", "sma_50"]

    return {
        "symbol": symbol.removesuffix(".NS"),
        "bars": df[cols].round(2).astype(object).where(df[cols].notna(), None)
        .to_dict("records"),
    }

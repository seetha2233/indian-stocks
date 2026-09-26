from abc import ABC, abstractmethod

import pandas as pd
import yfinance as yf


class MarketDataProvider(ABC):

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        period: str = "1y"
    ) -> pd.DataFrame:
        pass


class YahooMarketDataProvider(MarketDataProvider):

    def get_history(
        self,
        symbol: str,
        period: str = "1y"
    ) -> pd.DataFrame:

        ticker = yf.Ticker(symbol)

        df = ticker.history(
            period=period,
            auto_adjust=False
        )

        if df.empty:
            raise ValueError(
                f"No market data found for {symbol}"
            )

        df = df.reset_index()

        return df
    

    def get_history_many(
        self,
        symbols: list[str],
        period: str = "6mo"
    ) -> dict[str, pd.DataFrame]:
        """Batch download; returns {symbol: history} for symbols with data."""

        raw = yf.download(
            symbols,
            period=period,
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False,
        )

        out = {}

        tickers = (
            raw.columns.get_level_values(0).unique()
            if isinstance(raw.columns, pd.MultiIndex) else []
        )

        for symbol in symbols:

            if symbol not in tickers:
                continue

            df = raw[symbol].dropna(how="all")

            if df.empty or df["Close"].notna().sum() == 0:
                continue

            df = df.reset_index().rename(columns={"index": "Date"})
            out[symbol] = df

        return out

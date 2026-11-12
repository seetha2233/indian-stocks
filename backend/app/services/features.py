"""Feature engineering for the ML dataset.

Every feature for day t uses only data up to and including day t's close,
so they are safe to pair with forward-looking labels.

All features are scale-free (ratios / percentages) so one model can be
trained across stocks with very different price levels.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import ta
from sqlalchemy import text
from sqlalchemy.engine import Engine


CORPORATE_ACTIONS_CSV = (
    Path(__file__).resolve().parents[3]
    / "data" / "universe" / "corporate_actions.csv"
)

FEATURES_TABLE = "stock_features"

# Per-stock features, computed from one stock's own history
STOCK_FEATURES = [
    # Returns
    "ret_1d", "ret_5d", "ret_10d", "ret_20d", "ret_40d",
    # Trend
    "dist_sma_10", "dist_sma_20", "dist_sma_50", "sma_10_50",
    "macd", "macd_signal", "macd_hist",
    # Momentum
    "rsi_14", "stoch_k_14",
    # Volatility
    "volatility_20d", "atr_14", "bb_pct_b", "bb_width",
    # Volume
    "volume_ratio_20", "volume_ratio_5_20",
    # Price position
    "range_pos_20", "dist_high_40", "dist_low_40",
    # Candle
    "gap", "intraday_ret", "range_pct",
]

# Cross-sectional features, computed across all stocks on the same day
MARKET_FEATURES = [
    "mkt_ret_1d", "mkt_ret_20d", "mkt_volatility_20d", "mkt_breadth_20",
    "rel_ret_5d", "rel_ret_20d", "rank_ret_20d", "rank_volume_ratio_20",
]

FEATURE_COLUMNS = STOCK_FEATURES + MARKET_FEATURES

# Longest lookback window (the 50-day average); with only 6 months of
# prices, shorter windows leave more usable rows
MIN_HISTORY = 50

# A one-day move beyond these is treated as a corporate action or data
# error (unadjusted split, demerger) and splits the series. NSE price bands
# make genuine moves this large very rare.
BREAK_DOWN = -0.40
BREAK_UP = 0.50


def load_prices(engine: Engine) -> pd.DataFrame:

    df = pd.read_sql(
        text(
            "SELECT symbol, timestamp, open, high, low, close, "
            "adj_close, volume FROM stock_prices "
            "ORDER BY symbol, timestamp"
        ),
        engine
    )

    # Adjust OHLC by the same factor as close, so gaps/ranges are
    # consistent with split/dividend-adjusted returns
    factor = (df["adj_close"] / df["close"]).fillna(1.0)

    for col in ("open", "high", "low"):
        df[col] = df[col] * factor

    df["close"] = df["adj_close"].fillna(df["close"])

    return df.drop(columns="adj_close")


def assign_segments(df: pd.DataFrame) -> pd.DataFrame:
    """Split each stock's series at corporate-action dates.

    Breaks come from the curated corporate_actions.csv plus any one-day
    move beyond BREAK_DOWN / BREAK_UP. Rolling windows never cross a
    segment boundary, so a demerger or unadjusted split can't show up as a
    fake crash in any feature or target.
    """

    df = df.sort_values(["symbol", "timestamp"]).copy()

    ret = df.groupby("symbol")["close"].pct_change()
    brk = (ret <= BREAK_DOWN) | (ret >= BREAK_UP)

    # data/ is gitignored, so a fresh clone has no curated list; fall back
    # to the one-day-move breaks alone
    if CORPORATE_ACTIONS_CSV.exists():
        events = pd.read_csv(CORPORATE_ACTIONS_CSV, parse_dates=["date"])
    else:
        print(f"  {CORPORATE_ACTIONS_CSV.name} not found; using only one-day-move breaks")
        events = pd.DataFrame(columns=["symbol", "date"])

    for event in events.itertuples():
        brk |= (df["symbol"] == event.symbol) & (df["timestamp"] == event.date)

    df["segment"] = brk.astype(int).groupby(df["symbol"]).cumsum()

    return df


def _stock_features(g: pd.DataFrame) -> pd.DataFrame:
    """Features for one contiguous (symbol, segment) series."""

    g = g.copy()

    close, high, low = g["close"], g["high"], g["low"]
    volume = g["volume"]

    # Returns
    for n in (1, 5, 10, 20, 40):
        g[f"ret_{n}d"] = close.pct_change(n)

    # Trend
    sma = {n: close.rolling(n).mean() for n in (10, 20, 50)}

    for n, s in sma.items():
        g[f"dist_sma_{n}"] = close / s - 1

    g["sma_10_50"] = sma[10] / sma[50] - 1

    macd = ta.trend.MACD(close=close)
    g["macd"] = macd.macd() / close
    g["macd_signal"] = macd.macd_signal() / close
    g["macd_hist"] = macd.macd_diff() / close

    # Momentum
    g["rsi_14"] = ta.momentum.RSIIndicator(close=close, window=14).rsi()

    g["stoch_k_14"] = ta.momentum.StochasticOscillator(
        high=high, low=low, close=close, window=14
    ).stoch()

    # Volatility
    log_ret = np.log(close).diff()
    g["volatility_20d"] = log_ret.rolling(20).std()

    g["atr_14"] = ta.volatility.AverageTrueRange(
        high=high, low=low, close=close, window=14
    ).average_true_range() / close

    bb = ta.volatility.BollingerBands(close=close, window=20)
    g["bb_pct_b"] = bb.bollinger_pband()
    g["bb_width"] = bb.bollinger_wband() / 100

    # Volume
    vol_sma_20 = volume.rolling(20).mean()
    g["volume_ratio_20"] = volume / vol_sma_20
    g["volume_ratio_5_20"] = volume.rolling(5).mean() / vol_sma_20

    # Price position
    high_20, low_20 = high.rolling(20).max(), low.rolling(20).min()
    g["range_pos_20"] = (close - low_20) / (high_20 - low_20)
    g["dist_high_40"] = close / high.rolling(40).max() - 1
    g["dist_low_40"] = close / low.rolling(40).min() - 1

    # Candle
    g["gap"] = g["open"] / close.shift(1) - 1
    g["intraday_ret"] = close / g["open"] - 1
    g["range_pct"] = (high - low) / close

    return g


def _market_features(
    df: pd.DataFrame,
    mkt_daily: pd.Series
) -> pd.DataFrame:
    """Market context from the whole universe on each day."""

    by_day = df.groupby("timestamp")

    df["mkt_ret_1d"] = by_day["ret_1d"].transform("mean")
    df["mkt_ret_20d"] = by_day["ret_20d"].transform("mean")

    # Rolling std of the equal-weighted market's daily return
    df["mkt_volatility_20d"] = df["timestamp"].map(
        mkt_daily.rolling(20).std()
    )

    # Share of stocks trading above their 20-day average
    df["mkt_breadth_20"] = by_day["dist_sma_20"].transform(
        lambda s: (s > 0).mean()
    )

    df["rel_ret_5d"] = df["ret_5d"] - by_day["ret_5d"].transform("mean")
    df["rel_ret_20d"] = df["ret_20d"] - df["mkt_ret_20d"]

    df["rank_ret_20d"] = by_day["ret_20d"].rank(pct=True)
    df["rank_volume_ratio_20"] = by_day["volume_ratio_20"].rank(pct=True)

    return df


def build_features(prices: pd.DataFrame) -> pd.DataFrame:

    df = assign_segments(prices)

    # Equal-weighted market daily return from every stock-day. Computed
    # before short series are dropped, so a day's value never depends on
    # how much history a stock goes on to accumulate later.
    mkt_daily = (
        df.groupby(["symbol", "segment"])["close"].pct_change()
        .groupby(df["timestamp"]).mean()
        .sort_index()
    )

    df = (
        pd.concat(
            _stock_features(g)
            for _, g in df.groupby(["symbol", "segment"])
            if len(g) > MIN_HISTORY
        )
        .sort_values(["symbol", "timestamp"])
        .reset_index(drop=True)
    )

    df = df.replace([np.inf, -np.inf], np.nan)

    # Market features only from stocks that have a full feature row
    # that day, so warm-up rows don't skew the averages
    ready = df.dropna(subset=STOCK_FEATURES).copy()

    ready = _market_features(ready, mkt_daily)

    ready = ready.dropna(subset=FEATURE_COLUMNS)

    return ready[
        ["symbol", "timestamp", "segment", "close"] + FEATURE_COLUMNS
    ].reset_index(drop=True)


def save_features(engine: Engine, features: pd.DataFrame) -> None:
    """Replace the stock_features table (fully derived, safe to rebuild)."""

    with engine.begin() as conn:

        features.to_sql(
            FEATURES_TABLE,
            conn,
            if_exists="replace",
            index=False,
            chunksize=5000,
            method="multi"
        )

        conn.execute(
            text(
                f"CREATE UNIQUE INDEX uq_{FEATURES_TABLE}_symbol_ts "
                f"ON {FEATURES_TABLE} (symbol, timestamp)"
            )
        )

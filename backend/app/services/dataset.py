"""ML dataset: features for day t joined with what happened after day t.

Targets are measured from day t's close, using trading days (a week = 5):

    target_ret_1d       close[t+1] / close[t] - 1
    target_ret_5d       close[t+5] / close[t] - 1
    target_high_1d      high[t+1] / close[t] - 1
    target_high_5d      max(high[t+1..t+5]) / close[t] - 1
    target_hit_5pct_5d  1 if target_high_5d >= 5% else 0
    target_high_20d     max(high[t+1..t+20]) / close[t] - 1
    target_hit_5pct_20d 1 if target_high_20d >= 5% else 0
    target_vol_20d      std of daily log returns over t+1..t+20 (risk)

Targets never cross a corporate-action boundary (same segments as the
features). Rows need complete 5-day targets; 20-day targets are NaN for
the most recent 20 days and each model trains on the rows it has.
"""

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.features import (
    FEATURE_COLUMNS,
    FEATURES_TABLE,
    assign_segments
)


DATASET_TABLE = "ml_dataset"

HORIZON_DAYS = 5

LONG_HORIZON_DAYS = 20

HIT_THRESHOLD = 0.05

REGRESSION_TARGETS = [
    "target_ret_1d",
    "target_ret_5d",
    "target_high_1d",
    "target_high_5d",
    "target_high_20d",
    "target_vol_20d",
]

CLASSIFICATION_TARGETS = ["target_hit_5pct_5d", "target_hit_5pct_20d"]

TARGET_COLUMNS = REGRESSION_TARGETS + CLASSIFICATION_TARGETS

# Every dataset row has these
SHORT_TARGETS = [
    "target_ret_1d", "target_ret_5d", "target_high_1d",
    "target_high_5d", "target_hit_5pct_5d",
]

# Forward window of each target, in trading days: rows this close to a
# test period must be dropped from training (see model.split_for_target)
TARGET_HORIZON = {
    "target_ret_1d": 1,
    "target_high_1d": 1,
    "target_ret_5d": HORIZON_DAYS,
    "target_high_5d": HORIZON_DAYS,
    "target_hit_5pct_5d": HORIZON_DAYS,
    "target_high_20d": LONG_HORIZON_DAYS,
    "target_hit_5pct_20d": LONG_HORIZON_DAYS,
    "target_vol_20d": LONG_HORIZON_DAYS,
}


def _forward_max(s: pd.Series, n: int) -> pd.Series:
    """max(s[t+1..t+n]), NaN when the window runs past the data."""

    return s.shift(-1).rolling(n).max().shift(-(n - 1))


def _hit(high_target: pd.Series) -> pd.Series:

    return pd.Series(
        np.where(
            high_target.isna(),
            np.nan,
            (high_target >= HIT_THRESHOLD).astype(float)
        ),
        index=high_target.index
    )


def _targets(g: pd.DataFrame) -> pd.DataFrame:
    """Forward targets for one contiguous (symbol, segment) series."""

    g = g.copy()

    close, high = g["close"], g["high"]
    n, n_long = HORIZON_DAYS, LONG_HORIZON_DAYS

    g["target_ret_1d"] = close.shift(-1) / close - 1
    g["target_ret_5d"] = close.shift(-n) / close - 1

    g["target_high_1d"] = high.shift(-1) / close - 1

    g["target_high_5d"] = _forward_max(high, n) / close - 1
    g["target_hit_5pct_5d"] = _hit(g["target_high_5d"])

    g["target_high_20d"] = _forward_max(high, n_long) / close - 1
    g["target_hit_5pct_20d"] = _hit(g["target_high_20d"])

    # std of log returns on days t+1..t+n_long
    log_ret = np.log(close).diff()
    g["target_vol_20d"] = (
        log_ret.shift(-1).rolling(n_long).std().shift(-(n_long - 1))
    )

    return g


def build_targets(prices: pd.DataFrame) -> pd.DataFrame:

    df = assign_segments(prices)

    df = pd.concat(
        _targets(g) for _, g in df.groupby(["symbol", "segment"])
    )

    return df[["symbol", "timestamp"] + TARGET_COLUMNS]


def build_dataset(engine: Engine, prices: pd.DataFrame) -> pd.DataFrame:

    features = pd.read_sql(
        text(f"SELECT * FROM {FEATURES_TABLE}"),
        engine,
        parse_dates=["timestamp"]
    )

    targets = build_targets(prices)

    df = features.merge(targets, on=["symbol", "timestamp"], how="inner")

    df = df.dropna(subset=SHORT_TARGETS)

    df = df.sort_values(["timestamp", "symbol"]).reset_index(drop=True)

    return df[
        ["symbol", "timestamp", "segment", "close"]
        + FEATURE_COLUMNS
        + TARGET_COLUMNS
    ]


def save_dataset(engine: Engine, df: pd.DataFrame) -> None:
    """Replace the ml_dataset table (fully derived, safe to rebuild)."""

    with engine.begin() as conn:

        df.to_sql(
            DATASET_TABLE,
            conn,
            if_exists="replace",
            index=False,
            chunksize=5000,
            method="multi"
        )

        conn.execute(
            text(
                f"CREATE UNIQUE INDEX uq_{DATASET_TABLE}_symbol_ts "
                f"ON {DATASET_TABLE} (symbol, timestamp)"
            )
        )

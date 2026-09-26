"""Predict for every stock on the latest day in stock_features.

Saves to the stock_predictions table and prints a ranked table.

Usage (from backend/):
    python -m app.scripts.predict
    python -m app.scripts.predict --top 20
"""

import argparse

import pandas as pd
from sqlalchemy import text

from app.db.database import engine
from app.db.utils import replace_day
from app.services.features import FEATURES_TABLE
from app.services.model import load_models, predict


PREDICTIONS_TABLE = "stock_predictions"


def main() -> None:

    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=100)
    args = parser.parse_args()

    features = pd.read_sql(
        text(
            f"SELECT * FROM {FEATURES_TABLE} WHERE timestamp = "
            f"(SELECT max(timestamp) FROM {FEATURES_TABLE})"
        ),
        engine,
        parse_dates=["timestamp"]
    )

    # Raw (unadjusted) close, so price targets match what the market shows
    prices = pd.read_sql(
        text(
            "SELECT symbol, timestamp, close AS price FROM stock_prices "
            "WHERE timestamp = :ts"
        ),
        engine,
        params={"ts": features["timestamp"].iloc[0].to_pydatetime()},
        parse_dates=["timestamp"]
    )

    out = predict(features, load_models())

    pred_cols = [c for c in out if c.startswith("pred_")]
    out[pred_cols] = out[pred_cols].astype("float64")

    out = out.merge(
        prices, on=["symbol", "timestamp"]
    )

    for h in ("1d", "5d", "20d"):
        out[f"high_price_{h}"] = out["price"] * (1 + out[f"pred_high_{h}"])

    out = out.sort_values(
        "pred_hit_5pct_5d", ascending=False
    ).reset_index(drop=True)

    replace_day(engine, PREDICTIONS_TABLE, out)

    day = out["timestamp"].iloc[0]

    show = pd.DataFrame({
        "stock": out["symbol"].str.removesuffix(".NS"),
        "price": out["price"].round(2),
        "1d %": (out["pred_ret_1d"] * 100).round(2),
        "1w %": (out["pred_ret_5d"] * 100).round(2),
        "1d high": out["high_price_1d"].round(2),
        "1d high %": (out["pred_high_1d"] * 100).round(2),
        "1w high": out["high_price_5d"].round(2),
        "1w high %": (out["pred_high_5d"] * 100).round(2),
        "P(+5% in 1w)": (out["pred_hit_5pct_5d"] * 100).round(1),
    })

    print(f"Predictions from close of {day:%Y-%m-%d} ({len(out)} stocks)\n")
    print(show.head(args.top).to_string(index=False))
    print(
        "\n1d/1w %: expected change in closing price\n"
        "high: median forecast of the intraday high (~50% chance of "
        "reaching it)\n"
        "P(+5% in 1w): chance the price touches +5% within 5 trading days"
    )


if __name__ == "__main__":
    main()

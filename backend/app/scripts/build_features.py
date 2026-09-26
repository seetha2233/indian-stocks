"""Compute ML features from stock_prices into the stock_features table.

Usage (from backend/):
    python -m app.scripts.build_features
"""

from app.db.database import engine
from app.services.features import (
    FEATURE_COLUMNS,
    FEATURES_TABLE,
    build_features,
    load_prices,
    save_features
)


def main() -> None:

    prices = load_prices(engine)

    print(
        f"Loaded {len(prices)} price rows for "
        f"{prices['symbol'].nunique()} stocks"
    )

    features = build_features(prices)

    save_features(engine, features)

    per_stock = features.groupby("symbol").size()

    print(
        f"Wrote {len(features)} rows x {len(FEATURE_COLUMNS)} features "
        f"to {FEATURES_TABLE}\n"
        f"Dates: {features['timestamp'].min():%Y-%m-%d} -> "
        f"{features['timestamp'].max():%Y-%m-%d}\n"
        f"Rows per stock: min {per_stock.min()} ({per_stock.idxmin()}), "
        f"median {int(per_stock.median())}, max {per_stock.max()}"
    )


if __name__ == "__main__":
    main()

"""Join features with forward targets into the ml_dataset table.

Run build_features first.

Usage (from backend/):
    python -m app.scripts.build_dataset
"""

from app.db.database import engine
from app.services.dataset import (
    DATASET_TABLE,
    REGRESSION_TARGETS,
    TARGET_COLUMNS,
    build_dataset,
    save_dataset
)
from app.services.features import load_prices


def main() -> None:

    prices = load_prices(engine)

    df = build_dataset(engine, prices)

    save_dataset(engine, df)

    print(f"Wrote {len(df)} rows to {DATASET_TABLE}\n")

    print(
        f"  {df['symbol'].nunique()} stocks, {df['timestamp'].nunique()} dates, "
        f"{df['timestamp'].min():%Y-%m-%d} -> {df['timestamp'].max():%Y-%m-%d}"
    )

    for target in TARGET_COLUMNS:
        labelled = df[df[target].notna()]
        print(
            f"  {target:20s} {len(labelled):7d} rows, "
            f"{labelled['timestamp'].nunique():3d} dates"
        )

    print("\nTargets (% move from today's close):")

    summary = (
        df[REGRESSION_TARGETS]
        .mul(100)
        .describe(percentiles=[0.1, 0.5, 0.9])
        .T[["mean", "10%", "50%", "90%"]]
        .round(2)
    )

    print(summary.to_string())


if __name__ == "__main__":
    main()

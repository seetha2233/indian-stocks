"""Snapshot fundamentals for the configured universe into stock_fundamentals.

Usage (from backend/):
    python -m app.scripts.ingest_fundamentals
"""

from app.core.config import settings
from app.db.database import engine
from app.services.fundamentals import (
    FIELDS,
    fetch_fundamentals,
    fundamental_scores,
    save_fundamentals
)
from app.services.universe import universe_table


def main() -> None:

    universe = universe_table(settings.UNIVERSE)

    print(f"Fetching fundamentals for {len(universe)} stocks...", flush=True)

    df = fetch_fundamentals(universe["symbol"].tolist())

    # Fall back to NSE's company name where Yahoo has none
    df["long_name"] = df["long_name"].fillna(df["symbol"].map(dict(zip(universe["symbol"], universe["long_name"]))))

    df = df.merge(fundamental_scores(df), on="symbol")

    save_fundamentals(engine, df)

    coverage = df[list(FIELDS)].notna().mean().mul(100).round(0)

    print("\nCoverage (% of stocks with a value):")
    print(coverage.to_string())

    print("\nTop 5 by fundamental score:")
    print(
        df.nlargest(5, "fundamental_score")[
            ["symbol", "sector", "fundamental_score"]
        ].round(1).to_string(index=False)
    )


if __name__ == "__main__":
    main()

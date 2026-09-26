"""Pull daily price history (max 6 months) into PostgreSQL.

Usage (from backend/):
    python -m app.scripts.ingest                          # the configured universe (all NSE by default)
    python -m app.scripts.ingest --universe nifty100
    python -m app.scripts.ingest --keep-list              # use the local stock lists as they are
    python -m app.scripts.ingest RELIANCE TCS --period 3mo

Each universe run first re-downloads the NSE and NIFTY 100 stock lists, so
new listings are picked up; if NSE can't be reached the local snapshot in
data/universe/ is used. --refresh-list makes a failed download fatal.
"""

import argparse
import sys

from sqlalchemy import func, select

from app.core.config import settings
from app.db.database import SessionLocal
from app.db.init_db import init_db
from app.db.models import StockPrice
from app.services.ingestion import (
    ALLOWED_PERIODS,
    DEFAULT_PERIOD,
    ingest_many,
    prune_old
)
from app.services.universe import UNIVERSES, load_universe, refresh_lists


# Fail the run if Yahoo returns nothing for more than this share of stocks
MAX_MISSING_SHARE = 0.10


def main() -> None:

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("symbols", nargs="*", help="Specific stocks instead of a universe")
    parser.add_argument("--universe", choices=UNIVERSES, default=settings.UNIVERSE)
    lists = parser.add_mutually_exclusive_group()
    lists.add_argument("--refresh-list", action="store_true", help="Fail if the stock lists can't be downloaded")
    lists.add_argument("--keep-list", action="store_true", help="Don't re-download the stock lists")
    parser.add_argument(
        "--period",
        default=DEFAULT_PERIOD,
        choices=ALLOWED_PERIODS,
        help="How much history to pull (max 6mo)"
    )

    # Kept for backwards compatibility with older commands
    parser.add_argument("--nifty100", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    universe = "nifty100" if args.nifty100 else args.universe

    if not args.symbols and not args.keep_list:
        print("Refreshing stock lists from NSE...", flush=True)
        for line in refresh_lists(strict=args.refresh_list):
            print(f"  {line}")

    symbols = args.symbols or load_universe(universe)

    init_db()

    print(f"Downloading {args.period} of daily prices for {len(symbols)} stocks...", flush=True)

    def progress(done: int, total: int) -> None:
        if done % 500 < 100 or done == total:
            print(f"  {done}/{total}", flush=True)

    with SessionLocal() as db:

        counts, missing = ingest_many(db, symbols, period=args.period, on_batch=progress)

        pruned = prune_old(db)

        stocks, rows, first, last = db.execute(
            select(
                func.count(func.distinct(StockPrice.symbol)),
                func.count(),
                func.min(StockPrice.timestamp),
                func.max(StockPrice.timestamp),
            )
        ).one()

    print(
        f"\nDone: {len(counts)} stocks with data, {len(missing)} with none"
        f"{' (e.g. ' + ', '.join(m.removesuffix('.NS') for m in missing[:8]) + ')' if missing else ''}"
    )
    print(f"Removed {pruned} rows older than 6 months")
    print(
        f"In DB: {stocks} stocks, {rows} rows, "
        f"{first:%Y-%m-%d} -> {last:%Y-%m-%d}"
    )

    if symbols and len(missing) / len(symbols) > MAX_MISSING_SHARE:
        print(f"More than {MAX_MISSING_SHARE:.0%} of stocks returned no data; failing")
        sys.exit(1)


if __name__ == "__main__":
    main()

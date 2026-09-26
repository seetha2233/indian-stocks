"""Run the full daily pipeline, in order, stopping at the first failure.

Usage (from backend/):
    python -m app.scripts.refresh
    python -m app.scripts.refresh --skip-fundamentals   # reuse last snapshot
    python -m app.scripts.refresh --backtest            # also rerun backtest

After every successful step the API cache is invalidated, so the API never
serves an older day than the database holds.
"""

import argparse
import subprocess
import sys
import time

from app.core.cache import bump_data_version


def main() -> None:

    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-fundamentals", action="store_true")
    parser.add_argument("--backtest", action="store_true")
    args = parser.parse_args()

    steps = [
        ["ingest"],
        ["build_features"],
        ["build_dataset"],
        ["train_model"],
        ["predict", "--top", "0"],
    ]

    if not args.skip_fundamentals:
        steps.append(["ingest_fundamentals"])

    steps += [["ingest_news"], ["build_signals"], ["index_research"]]

    if args.backtest:
        steps.append(["backtest"])

    for name, *step_args in steps:

        print(f"\n=== {name} ===", flush=True)

        started = time.time()

        result = subprocess.run(
            [sys.executable, "-m", f"app.scripts.{name}", *step_args]
        )

        if result.returncode != 0:
            print(f"\n{name} failed (exit {result.returncode}); stopping")
            sys.exit(result.returncode)

        bump_data_version()

        print(f"({time.time() - started:.0f}s)")

    print("\nRefresh complete")


if __name__ == "__main__":
    main()

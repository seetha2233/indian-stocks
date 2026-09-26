"""Build today's stock cards into the stock_signals table.

Run predict and ingest_fundamentals first.

Usage (from backend/):
    python -m app.scripts.build_signals
    python -m app.scripts.build_signals --show RELIANCE
"""

import argparse
import json

from app.db.database import engine
from app.db.utils import replace_day
from app.services.signals import SIGNALS_TABLE, build_signals, card


def main() -> None:

    parser = argparse.ArgumentParser()
    parser.add_argument("--show", help="Print the card for one stock")
    args = parser.parse_args()

    df = build_signals(engine)

    replace_day(engine, SIGNALS_TABLE, df)

    day = df["timestamp"].iloc[0]

    print(f"Signals for {day:%Y-%m-%d}: {len(df)} stocks")
    print(df["signal"].value_counts().to_string(), "\n")
    print(df["risk"].value_counts().to_string(), "\n")

    top = df.head(10)[[
        "symbol", "price", "signal", "composite_score", "technical_score",
        "momentum_score", "fundamental_score", "risk", "upside_prob_20d",
    ]].copy()
    top["symbol"] = top["symbol"].str.removesuffix(".NS")
    print("Top 10 by composite score:")
    print(top.round(2).to_string(index=False))

    if args.show:
        symbol = args.show.upper().removesuffix(".NS") + ".NS"
        row = df[df["symbol"] == symbol].iloc[0].to_dict()
        print("\n" + json.dumps(card(row), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

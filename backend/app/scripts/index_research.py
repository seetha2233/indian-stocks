"""Index today's stock cards and model/backtest results into Chroma.

Run after build_signals.

Usage (from backend/):
    python -m app.scripts.index_research
"""

import os
import sys

from app.db.database import engine
from app.services.research import index_research


def main() -> None:
    print(f"Indexed {index_research(engine)} research documents into Chroma")


if __name__ == "__main__":
    main()

    # onnxruntime (Chroma's local embeddings) can abort with "recursive_mutex
    # lock failed" while Python finalises on macOS. Chroma has already
    # committed every write by now, so skip finalisation on success.
    sys.stdout.flush()
    os._exit(0)

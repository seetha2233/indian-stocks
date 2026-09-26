"""Fetch news from RSS into news_articles, score sentiment (if an OpenAI key
is set) and index it into Chroma for research search.

Usage (from backend/):
    python -m app.scripts.ingest_news
"""

import os
import sys

from app.core.config import settings
from app.db.database import engine
from app.services import llm
from app.services.news import (
    MARKET,
    ensure_table,
    fetch_all,
    prune,
    save_articles,
    score_pending
)
from app.services.research import index_news
from app.services.universe import universe_table


def main() -> None:

    ensure_table(engine)

    universe = universe_table(settings.UNIVERSE)

    print(f"Fetching news for {len(universe)} stocks + market feeds...")

    articles = fetch_all(universe)

    new = save_articles(engine, articles)
    removed = prune(engine)

    stock_rows = sum(a["symbol"] != MARKET for a in articles)

    print(
        f"Fetched {len(articles)} article-stock pairs "
        f"({stock_rows} stock, {len(articles) - stock_rows} market); "
        f"{new} new, {removed} older than 90 days removed; using the last 5 days"
    )

    if llm.available():
        names = dict(zip(universe["symbol"], universe["long_name"]))
        c = score_pending(engine, names)
        print(
            f"Sentiment: {c['local']} ruled out locally (company not named), "
            f"{c['llm']} scored in {c['calls']} OpenAI calls"
            + (f" ({c['failed_calls']} failed, retried next run)" if c["failed_calls"] else "")
        )
    else:
        print("OPENAI_API_KEY not set: skipping sentiment (news score stays empty)")

    print(f"Indexed {index_news(engine)} articles into Chroma")


if __name__ == "__main__":
    main()

    # onnxruntime (Chroma's local embeddings) can abort with "recursive_mutex
    # lock failed" while Python finalises on macOS. Chroma has already
    # committed every write by now, so skip finalisation on success.
    sys.stdout.flush()
    os._exit(0)

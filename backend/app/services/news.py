"""News service: free RSS feeds -> news_articles table.

Sources:
  - Google News search, one query per stock (stock-specific news)
  - Market feeds (Economic Times, Livemint, Business Standard), matched to
    stocks when the headline or summary names the company; everything else
    is kept as market-wide news under symbol "MARKET"
"""

import hashlib
import html
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import feedparser
import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


NEWS_TABLE = "news_articles"

MARKET = "MARKET"

MARKET_FEEDS = {
    "Economic Times Markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "Economic Times Stocks": "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms",
    "Livemint Markets": "https://www.livemint.com/rss/markets",
    "Business Standard Markets": "https://www.business-standard.com/rss/markets-106.rss",
}

GOOGLE_NEWS = (
    "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
)

PER_STOCK_LIMIT = 10

LOOKBACK_DAYS = 5

# Tickers that are also everyday acronyms in market news ("BSE Sensex")
TICKER_STOPLIST = {"BSE", "NSE", "ITI", "LIC", "IDEA", "GOLD", "INDIA", "OIL", "MMTC"}

# Dropped from company names to get the name people actually write
NAME_SUFFIXES = r"\b(limited|ltd\.?|corporation|corp\.?|company|co\.?)$"


def clean_name(long_name: str) -> str:

    name = re.sub(r"\s+", " ", long_name).strip()
    name = re.sub(r"^the\s+", "", name, flags=re.I)

    while True:
        shorter = re.sub(NAME_SUFFIXES, "", name, flags=re.I).strip(" .,")
        if shorter == name:
            return name
        name = shorter


def _strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _published(entry) -> datetime:

    parsed = entry.get("published_parsed") or entry.get("updated_parsed")

    if not parsed:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    return datetime(*parsed[:6])


def _article_id(title: str) -> str:
    """Same headline from different feeds -> same id."""

    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return hashlib.sha1(normalized.encode()).hexdigest()[:16]


def _parse(feed_url: str, feed_name: str) -> list[dict]:

    feed = feedparser.parse(feed_url, agent="Mozilla/5.0")

    out = []

    for e in feed.entries:

        title = _strip_html(e.get("title", ""))
        source = feed_name

        # Google News titles end with " - Publisher"
        if e.get("source"):
            source = e["source"].get("title") or source
            title = re.sub(rf"\s+-\s+{re.escape(source)}$", "", title)

        summary = _strip_html(e.get("summary", ""))

        # Google News summaries are just the headline again as a link
        if summary.startswith(title[:40]):
            summary = ""

        out.append({
            "id": _article_id(title),
            "title": title,
            "summary": summary[:1000],
            "source": source,
            "url": e.get("link"),
            "published": _published(e),
            "feed": feed_name,
        })

    return out


def fetch_stock_news(symbol: str, long_name: str) -> list[dict]:

    query = urllib.parse.quote(
        f'"{clean_name(long_name)}" (share OR shares OR stock) '
        f"when:{LOOKBACK_DAYS}d"
    )

    articles = _parse(GOOGLE_NEWS.format(query=query), "Google News")

    articles.sort(key=lambda a: a["published"], reverse=True)

    return [{**a, "symbol": symbol} for a in articles[:PER_STOCK_LIMIT]]


def _short_aliases(universe: pd.DataFrame) -> dict[str, str]:
    """First two words of each name ("HDFC Life", "Tata Steel"), where that
    pair is unique in the universe and the name is longer than that."""

    words = {
        row.symbol: clean_name(row.long_name).split()
        for row in universe.itertuples()
    }

    pairs = {sym: " ".join(w[:2]) for sym, w in words.items() if len(w) > 2}

    counts = pd.Series(list(pairs.values())).value_counts()

    filler = {"of", "and", "the", "&", "india"}

    return {
        sym: pair for sym, pair in pairs.items()
        if counts[pair] == 1 and pair.split()[-1].lower() not in filler
    }


def _matchers(universe: pd.DataFrame) -> list[tuple[str, re.Pattern]]:
    """Regexes that identify each company in free text."""

    aliases = _short_aliases(universe)

    out = []

    for row in universe.itertuples():

        terms = [re.escape(clean_name(row.long_name))]

        if row.symbol in aliases:
            terms.append(re.escape(aliases[row.symbol]))

        ticker = row.symbol.removesuffix(".NS")

        # Tickers like TCS / ONGC / HDFCBANK are written as-is in headlines
        # (matched in capitals only); some collide with common acronyms
        if ticker.isalpha() and len(ticker) >= 3 and ticker not in TICKER_STOPLIST:
            terms.append(rf"(?-i:{re.escape(ticker)})")

        out.append(
            (row.symbol, re.compile(rf"\b(?:{'|'.join(terms)})\b", re.I))
        )

    return out


def fetch_market_news(universe: pd.DataFrame) -> list[dict]:

    matchers = _matchers(universe)

    rows = []

    for name, url in MARKET_FEEDS.items():

        for a in _parse(url, name):

            body = f"{a['title']} {a['summary']}"
            hits = [sym for sym, rx in matchers if rx.search(body)]

            for sym in hits or [MARKET]:
                rows.append({**a, "symbol": sym})

    return rows


def ensure_table(engine: Engine) -> None:

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {NEWS_TABLE} (
                id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                source TEXT,
                url TEXT,
                published TIMESTAMP NOT NULL,
                feed TEXT,
                fetched_at TIMESTAMP NOT NULL DEFAULT now(),
                relevant BOOLEAN,
                sentiment DOUBLE PRECISION,
                sentiment_reason TEXT,
                scored_at TIMESTAMP,
                PRIMARY KEY (id, symbol)
            )
        """))
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS ix_{NEWS_TABLE}_symbol_published "
            f"ON {NEWS_TABLE} (symbol, published DESC)"
        ))


def save_articles(engine: Engine, articles: list[dict]) -> int:
    """Insert new (id, symbol) pairs; existing rows keep their sentiment."""

    if not articles:
        return 0

    df = pd.DataFrame(articles).drop_duplicates(["id", "symbol"])

    cols = ["id", "symbol", "title", "summary", "source", "url", "published", "feed"]

    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"INSERT INTO {NEWS_TABLE} ({', '.join(cols)}) "
                f"VALUES ({', '.join(':' + c for c in cols)}) "
                f"ON CONFLICT (id, symbol) DO NOTHING"
            ),
            df[cols].to_dict("records")
        )

    return result.rowcount


def prune(engine: Engine, days: int = 90) -> int:

    with engine.begin() as conn:
        return conn.execute(
            text(f"DELETE FROM {NEWS_TABLE} WHERE published < :cutoff"),
            {"cutoff": datetime.now() - timedelta(days=days)}
        ).rowcount


def load_news(
    engine: Engine,
    symbol: str | None = None,
    days: int = LOOKBACK_DAYS,
    limit: int = 50
) -> pd.DataFrame:

    where = "published >= :cutoff"
    params: dict = {"cutoff": datetime.now() - timedelta(days=days), "limit": limit}

    if symbol:
        where += " AND symbol = :symbol"
        params["symbol"] = symbol

    return pd.read_sql(
        text(
            f"SELECT * FROM {NEWS_TABLE} WHERE {where} "
            f"ORDER BY published DESC LIMIT :limit"
        ),
        engine,
        params=params
    )


def fetch_all(universe: pd.DataFrame, workers: int = 8) -> list[dict]:
    """Market feeds plus one Google News search per stock, in parallel."""

    from concurrent.futures import ThreadPoolExecutor

    articles = fetch_market_news(universe)

    def one(row) -> list[dict]:
        try:
            return fetch_stock_news(row.symbol, row.long_name)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for found in pool.map(one, universe.itertuples()):
            articles += found

    return articles


# --- Sentiment -------------------------------------------------------------

# Articles per OpenAI call, mixed across stocks
SENTIMENT_BATCH = 50

# News score: recency-weighted mean sentiment, half-weight after ~3.5 days
SENTIMENT_DECAY_DAYS = 5

MIN_ARTICLES_FOR_SCORE = 2


def score_pending(engine: Engine, names: dict[str, str], workers: int = 8) -> dict:
    """Score unscored recent articles. Returns counts.

    To keep OpenAI calls down:
      - an article that never names the company (by full name, unique short
        name or ticker) is marked irrelevant locally, without a call;
      - the rest go in batches of SENTIMENT_BATCH mixed across stocks.
    Batches run in parallel; each is saved as it finishes, so an
    interrupted run keeps its progress and the rest stays pending.
    """

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from app.services.llm import score_sentiment

    pending = pd.read_sql(
        text(
            f"SELECT id, symbol, title, summary, source, published "
            f"FROM {NEWS_TABLE} WHERE scored_at IS NULL "
            f"AND symbol <> :market AND published >= :cutoff"
        ),
        engine,
        params={
            "market": MARKET,
            "cutoff": datetime.now() - timedelta(days=LOOKBACK_DAYS),
        }
    )

    counts = {"local": 0, "llm": 0, "calls": 0, "failed_calls": 0}

    if pending.empty:
        return counts

    universe = pd.DataFrame({"symbol": list(names), "long_name": list(names.values())})
    matchers = dict(_matchers(universe))

    def named(row) -> bool:
        rx = matchers.get(row.symbol)
        return bool(rx and rx.search(f"{row.title} {row.summary or ''}"))

    mask = pd.Series([named(r) for r in pending.itertuples()], index=pending.index)

    def save(updates: list[dict]) -> None:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"UPDATE {NEWS_TABLE} SET relevant = :relevant, "
                    f"sentiment = :sentiment, sentiment_reason = :reason, "
                    f"scored_at = now() WHERE id = :id AND symbol = :symbol"
                ),
                updates
            )

    unnamed = pending[~mask]
    if not unnamed.empty:
        save([
            {"id": r.id, "symbol": r.symbol, "relevant": False, "sentiment": None,
             "reason": "Company not named in the article"}
            for r in unnamed.itertuples()
        ])
        counts["local"] = len(unnamed)

    items = [
        {
            "key": f"{r.id}:{r.symbol}",
            "company": names.get(r.symbol, r.symbol),
            "symbol": r.symbol.removesuffix(".NS"),
            "title": r.title,
            "summary": (r.summary or "")[:300],
            "published": f"{r.published:%Y-%m-%d}",
        }
        for r in pending[mask].itertuples()
    ]

    batches = [items[i:i + SENTIMENT_BATCH] for i in range(0, len(items), SENTIMENT_BATCH)]

    def run(batch: list[dict]) -> list[dict]:

        wanted = {b["key"] for b in batch}

        return [
            {
                "id": r["key"].split(":", 1)[0],
                "symbol": r["key"].split(":", 1)[1],
                "relevant": r["relevant"],
                "sentiment": r["sentiment"] if r["relevant"] else None,
                "reason": r["reason"],
            }
            for r in score_sentiment(batch) if r["key"] in wanted
        ]

    with ThreadPoolExecutor(max_workers=workers) as pool:

        futures = [pool.submit(run, b) for b in batches]

        for future in as_completed(futures):

            counts["calls"] += 1

            try:
                updates = future.result()
            except Exception:
                counts["failed_calls"] += 1
                continue

            if updates:
                save(updates)
                counts["llm"] += len(updates)

    return counts


def news_scores(engine: Engine) -> pd.DataFrame:
    """0-100 news score per stock (50 = neutral), NaN with too little news."""

    df = pd.read_sql(
        text(
            f"SELECT symbol, published, sentiment FROM {NEWS_TABLE} "
            f"WHERE relevant AND sentiment IS NOT NULL AND published >= :cutoff"
        ),
        engine,
        params={"cutoff": datetime.now() - timedelta(days=LOOKBACK_DAYS)},
        parse_dates=["published"]
    )

    if df.empty:
        return pd.DataFrame(columns=["symbol", "news_score", "news_count"])

    age = (datetime.now() - df["published"]).dt.total_seconds() / 86400
    df["w"] = np.exp(-age.clip(lower=0) / SENTIMENT_DECAY_DAYS)
    df["ws"] = df["w"] * df["sentiment"]

    g = df.groupby("symbol").agg(ws=("ws", "sum"), w=("w", "sum"), n=("sentiment", "size"))

    g["news_score"] = 50 + 50 * g["ws"] / g["w"]
    g.loc[g["n"] < MIN_ARTICLES_FOR_SCORE, "news_score"] = np.nan

    return g.reset_index().rename(columns={"n": "news_count"})[
        ["symbol", "news_score", "news_count"]
    ]

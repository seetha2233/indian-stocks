"""LLM 'Why?' for stock cards, cached per stock per signal date."""

import json

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import settings
from app.services import llm
from app.services.news import load_news


EXPLANATIONS_TABLE = "stock_explanations"

NEWS_FOR_EXPLANATION = 10


def ensure_table(engine: Engine) -> None:

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {EXPLANATIONS_TABLE} (
                symbol TEXT NOT NULL,
                as_of DATE NOT NULL,
                model TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT now(),
                PRIMARY KEY (symbol, as_of)
            )
        """))


def _news_for(engine: Engine, symbol: str) -> list[dict]:

    try:
        df = load_news(engine, symbol=f"{symbol}.NS", limit=50)
    except Exception:
        return []

    # Prefer articles the sentiment pass judged relevant
    if "relevant" in df:
        df = df[df["relevant"].fillna(True).astype(bool)]

    df = df.head(NEWS_FOR_EXPLANATION)

    return [
        {
            "id": r.id,
            "title": r.title,
            "source": r.source,
            "published": f"{r.published:%Y-%m-%d}",
            "sentiment": None if pd.isna(r.sentiment) else round(r.sentiment, 2),
            "url": r.url,
        }
        for r in df.itertuples()
    ]


def _pct(x: float | None, digits: int = 1) -> str | None:
    return None if x is None else f"{x * 100:.{digits}f}%"


def _readable(card: dict) -> dict:
    """Card with fractions as percentages, so the LLM quotes them that way."""

    c = {k: v for k, v in card.items() if k != "disclaimer"}

    c["upside_prob_20d"] = _pct(card["upside_prob_20d"], 0)
    c["annual_volatility"] = _pct(card["annual_volatility"], 0)
    c["fundamentals"] = {**card["fundamentals"], "roe": _pct(card["fundamentals"]["roe"])}

    return c


def _fingerprint(card: dict, news: list[dict]) -> str:
    """Changes whenever the card's data or its news does."""

    import hashlib

    payload = json.dumps(
        {"card": {k: v for k, v in card.items() if k not in ("why", "definitions", "disclaimer")},
         "news": sorted(n["id"] for n in news)},
        sort_keys=True, default=str,
    )
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def get_explanation(engine: Engine, card: dict, refresh: bool = False) -> dict:
    """Cached per stock per day; regenerated only if the card or its news
    changed since (e.g. fundamentals arrived later), to spare OpenAI calls."""

    symbol, as_of = card["symbol"], card["as_of"]

    news = _news_for(engine, symbol)
    fingerprint = _fingerprint(card, news)

    fallback = {
        "source": "rules",
        "summary": None,
        "bullets": card["why"],
        "risks": [],
        "news": news,
    }

    if not llm.available():
        return {**fallback, "note": "LLM not configured; showing rule-based reasons."}

    ensure_table(engine)

    if not refresh:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT content, model, created_at FROM {EXPLANATIONS_TABLE} "
                    f"WHERE symbol = :s AND as_of = :d"
                ),
                {"s": symbol, "d": as_of}
            ).first()

        cached = json.loads(row.content) if row else None

        if cached and cached.get("fingerprint") == fingerprint:
            cached.pop("fingerprint", None)
            return {
                **cached,
                "source": "llm",
                "model": row.model,
                "generated_at": f"{row.created_at:%Y-%m-%d %H:%M}",
                "news": news,
            }

    prompt_card = _readable(card)
    prompt_news = [{k: n[k] for k in ("id", "title", "source", "published", "sentiment")} for n in news]

    try:
        content = llm.explain_card(prompt_card, prompt_news)
    except Exception as e:
        return {**fallback, "note": f"LLM call failed ({type(e).__name__}); showing rule-based reasons."}

    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {EXPLANATIONS_TABLE} (symbol, as_of, model, content) "
                f"VALUES (:s, :d, :m, :c) ON CONFLICT (symbol, as_of) DO UPDATE "
                f"SET content = EXCLUDED.content, model = EXCLUDED.model, "
                f"created_at = now()"
            ),
            {"s": symbol, "d": as_of, "m": settings.OPENAI_MODEL,
             "c": json.dumps({**content, "fingerprint": fingerprint})}
        )

    return {**content, "source": "llm", "model": settings.OPENAI_MODEL, "news": news}

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.cache import cached
from app.db.database import engine
from app.services import research
from app.services.explanations import get_explanation
from app.services.news import MARKET, load_news

from app.api.signals import get_signal


router = APIRouter(prefix="/api", tags=["research"])


@router.get("/news")
@cached(ttl=300)
def news(
    symbol: str | None = Query(None, description="e.g. RELIANCE, or MARKET"),
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(50, ge=1, le=200),
):
    if symbol and symbol.upper() != MARKET:
        symbol = symbol.upper().removesuffix(".NS") + ".NS"
    elif symbol:
        symbol = MARKET

    try:
        df = load_news(engine, symbol=symbol, days=days, limit=limit)
    except Exception:
        return []

    df = df.drop_duplicates("id") if not symbol else df

    # NULL text columns come back as NaN, which isn't valid JSON
    df = df.astype(object).where(df.notna(), None)

    return [
        {
            "id": r.id,
            "symbol": r.symbol.removesuffix(".NS"),
            "title": r.title,
            "summary": r.summary or None,
            "source": r.source,
            "url": r.url,
            "published": f"{r.published:%Y-%m-%d %H:%M}",
            "relevant": None if r.relevant is None else bool(r.relevant),
            "sentiment": None if r.sentiment is None else round(float(r.sentiment), 2),
            "sentiment_reason": r.sentiment_reason,
        }
        for r in df.itertuples()
    ]


@router.get("/signals/{symbol}/explanation")
def explanation(symbol: str, refresh: bool = False):
    """LLM 'Why?' for the card (cached per day); rule-based without a key."""

    return get_explanation(engine, get_signal(symbol), refresh=refresh)


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    symbol: str | None = None


@router.post("/research/ask")
def ask(q: Question):

    try:
        return research.ask(q.question, q.symbol)
    except Exception as e:
        raise HTTPException(502, f"Research failed: {type(e).__name__}: {e}")


@router.get("/research/search")
def search(q: str = Query(min_length=2), symbol: str | None = None):
    """Semantic search over cards, model docs and news (no LLM needed)."""

    return research.retrieve(q, symbol)

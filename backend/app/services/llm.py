"""OpenAI calls: news sentiment, stock-card explanations, research answers.

Every call returns JSON validated against a strict schema. When no
OPENAI_API_KEY is configured, calls raise LLMUnavailable and callers fall
back to non-LLM behaviour.
"""

import json
from functools import lru_cache

from app.core.config import settings


class LLMUnavailable(RuntimeError):
    pass


GUARDRAILS = (
    "You are a research assistant for Indian equities (NSE). Use only the "
    "facts provided in the input; if something isn't in the input, say you "
    "don't know. Never invent prices, targets, dates or news. This is "
    "research, not investment advice: don't tell the user to buy or sell, "
    "and be candid about uncertainty. The platform's own tests show its "
    "models estimate price range and volatility far better than direction, "
    "so treat any directional reading as weak."
)


@lru_cache
def _client():

    if not settings.OPENAI_API_KEY:
        raise LLMUnavailable("OPENAI_API_KEY is not set in backend/.env")

    from openai import OpenAI

    return OpenAI(api_key=settings.OPENAI_API_KEY)


def available() -> bool:
    return bool(settings.OPENAI_API_KEY)


def _json_call(instructions: str, payload: dict, name: str, schema: dict) -> dict:

    response = _client().responses.create(
        model=settings.OPENAI_MODEL,
        instructions=f"{GUARDRAILS}\n\n{instructions}",
        input=json.dumps(payload, ensure_ascii=False, default=str),
        text={
            "format": {
                "type": "json_schema",
                "name": name,
                "schema": schema,
                "strict": True,
            }
        },
    )

    return json.loads(response.output_text)


def _obj(properties: dict) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


SENTIMENT_SCHEMA = _obj({
    "articles": {
        "type": "array",
        "items": _obj({
            "key": {"type": "string"},
            "relevant": {"type": "boolean"},
            "sentiment": {"type": "number"},
            "reason": {"type": "string"},
        }),
    }
})


def score_sentiment(items: list[dict]) -> list[dict]:
    """Relevance and sentiment (-1 very negative .. +1 very positive) for
    many (article, company) pairs in one call.

    Each item: key, company, symbol, title, summary, published.
    """

    instructions = (
        "Each item pairs a news article with one NSE-listed company. Decide "
        "whether the article is materially about that company as a listed "
        "business: its operations, results, deals, management, regulation or "
        "share price. A different entity with a similar name, or a passing "
        "mention in a list, is not relevant. For relevant items, rate the "
        "likely effect on that company's share price from -1 (very negative) "
        "to +1 (very positive), 0 if neutral. Reason: under 12 words. Return "
        "every key exactly once."
    )

    out = _json_call(instructions, {"items": items}, "news_sentiment", SENTIMENT_SCHEMA)

    for item in out["articles"]:
        item["sentiment"] = max(-1.0, min(1.0, float(item["sentiment"])))

    return out["articles"]


EXPLANATION_SCHEMA = _obj({
    "summary": {"type": "string"},
    "bullets": {"type": "array", "items": {"type": "string"}},
    "risks": {"type": "array", "items": {"type": "string"}},
    "news_used": {"type": "array", "items": {"type": "string"}},
})


def explain_card(card: dict, news: list[dict]) -> dict:
    """Plain-English 'Why?' for a stock card, grounded in card + news."""

    instructions = (
        "Explain this stock card to a retail investor. Write a 1-2 sentence "
        "summary of the overall picture, then 3-5 short bullets on what "
        "drives the signal (technical, momentum, fundamentals, news, model "
        "estimates), then 1-3 key risks or caveats. Refer to news by what it "
        "says, and list the ids of the articles you relied on in news_used. "
        "Quote numbers exactly as given; write prices in rupees (e.g. "
        "₹1,214.59). Use the card's plain labels (Target 1, Target 2, stop "
        "loss, entry zone, 20-day upside probability, risk), never raw field "
        "names like target_1. Say what the targets and probabilities mean "
        "(statistical price-range estimates), not that the price will get "
        "there."
    )

    payload = {"card": card, "recent_news": news}

    return _json_call(instructions, payload, "card_explanation", EXPLANATION_SCHEMA)


ANSWER_SCHEMA = _obj({
    "answer": {"type": "string"},
    "cited": {"type": "array", "items": {"type": "integer"}},
})


def answer_question(question: str, sources: list[dict]) -> dict:
    """Answer from numbered sources; cite them as [n]."""

    instructions = (
        "Answer the question using only the numbered sources. Cite sources "
        "inline as [n]. If the sources don't answer it, say so plainly. "
        "Keep it under 250 words; use short paragraphs or bullets. List "
        "the numbers you cited in `cited`."
    )

    payload = {
        "question": question,
        "sources": [{"n": i + 1, **s} for i, s in enumerate(sources)],
    }

    return _json_call(instructions, payload, "research_answer", ANSWER_SCHEMA)

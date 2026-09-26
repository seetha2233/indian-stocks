from fastapi import APIRouter
from sqlalchemy import inspect, text

from app.core.cache import cache, data_version
from app.core.config import settings
from app.db.database import engine


router = APIRouter(tags=["health"])

FRESHNESS_TABLES = ("stock_prices", "stock_signals", "news_articles")


@router.get("/api/health")
def health() -> dict:

    out = {
        "status": "ok",
        "app": settings.APP_NAME,
        "cache": cache.backend,
        "data_version": data_version() or None,
        "llm": "configured" if settings.OPENAI_API_KEY else "not configured",
        "data": {},
    }

    try:
        with engine.connect() as conn:

            tables = set(inspect(conn).get_table_names())

            for table in FRESHNESS_TABLES:
                if table in tables:
                    col = "published" if table == "news_articles" else "timestamp"
                    latest = conn.execute(
                        text(f"SELECT max({col}) FROM {table}")
                    ).scalar()
                    out["data"][table] = latest and f"{latest:%Y-%m-%d %H:%M}"

    except Exception as e:
        out["status"] = "degraded"
        out["database"] = str(e).splitlines()[0]

    return out

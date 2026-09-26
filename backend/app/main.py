from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.market import router as market_router
from app.api.portfolio import router as portfolio_router
from app.api.research import router as research_router
from app.api.signals import router as signals_router
from app.api.stocks import router as stocks_router
from app.core.config import settings


app = FastAPI(
    title="Indian AI Stock Intelligence",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    health_router, market_router, stocks_router, signals_router,
    research_router, portfolio_router,
):
    app.include_router(router)

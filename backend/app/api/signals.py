import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.core.cache import cached
from app.db.database import engine
from app.services.model import MODEL_DIR
from app.services.signals import SIGNALS_TABLE, card, compact_card


router = APIRouter(prefix="/api", tags=["signals"])

BACKTEST_SUMMARY = (
    Path(__file__).resolve().parents[3] / "data" / "backtest" / "summary.csv"
)

SORTABLE = {
    "composite": "composite_score",
    "technical": "technical_score",
    "momentum": "momentum_score",
    "fundamental": "fundamental_score",
    "upside_prob": "upside_prob_20d",
    "risk_reward": "risk_reward",
    "volatility": "pred_vol_20d",
}


def _latest_signals() -> pd.DataFrame:

    return pd.read_sql(
        text(
            f"SELECT * FROM {SIGNALS_TABLE} WHERE timestamp = "
            f"(SELECT max(timestamp) FROM {SIGNALS_TABLE})"
        ),
        engine,
        parse_dates=["timestamp"]
    )


@router.get("/signals")
@cached(ttl=300)
def list_signals(
    signal: str | None = Query(None, description="WATCH | NEUTRAL | AVOID"),
    risk: str | None = Query(None, description="Low | Medium | High"),
    sector: str | None = None,
    nifty100: bool = False,
    sort: str = Query("composite", enum=list(SORTABLE)),
    limit: int = Query(5000, ge=1, le=5000),
    compact: bool = Query(False, description="Only the fields the screener table needs"),
):
    df = _latest_signals()

    if signal:
        df = df[df["signal"] == signal.upper()]
    if risk:
        df = df[df["risk"].str.lower() == risk.lower()]
    if sector:
        df = df[df["sector"].str.lower() == sector.lower()]
    if nifty100 and "nifty100" in df:
        df = df[df["nifty100"].fillna(False).astype(bool)]

    df = df.sort_values(SORTABLE[sort], ascending=False).head(limit)

    shape = compact_card if compact else card

    return [shape(row) for row in df.to_dict("records")]


@router.get("/signals/{symbol}")
@cached(ttl=300)
def get_signal(symbol: str):

    symbol = symbol.upper().removesuffix(".NS") + ".NS"

    df = _latest_signals()
    df = df[df["symbol"] == symbol]

    if df.empty:
        raise HTTPException(404, f"No stock card for {symbol} (not covered, or too little history)")

    return card(df.iloc[0].to_dict())


@router.get("/model/performance")
def model_performance():
    """Test-period model metrics and walk-forward backtest summary."""

    metrics_path = MODEL_DIR / "metrics.json"

    if not metrics_path.exists():
        raise HTTPException(404, "No trained model; run app.scripts.train_model")

    out = {"models": json.loads(metrics_path.read_text())}

    if BACKTEST_SUMMARY.exists():
        summary = pd.read_csv(BACKTEST_SUMMARY, index_col=0)
        out["backtest"] = json.loads(summary.to_json(orient="index"))

    return out

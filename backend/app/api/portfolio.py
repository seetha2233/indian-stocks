from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.cache import cached
from app.db.database import engine
from app.services import portfolio as pf


router = APIRouter(prefix="/api", tags=["portfolio"])

BACKTEST_DIR = Path(__file__).resolve().parents[3] / "data" / "backtest"


class NewPosition(BaseModel):
    symbol: str
    quantity: int = Field(gt=0)
    entry_price: float | None = Field(None, gt=0)
    target: float | None = Field(None, gt=0)
    stop_loss: float | None = Field(None, gt=0)
    note: str | None = Field(None, max_length=500)


@router.get("/portfolio")
def get_portfolio():
    pf.ensure_table(engine)
    return pf.portfolio(engine)


@router.post("/portfolio", status_code=201)
def add_position(p: NewPosition):

    try:
        position_id = pf.open_position(engine, **p.model_dump())
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"id": position_id}


@router.post("/portfolio/{position_id}/close")
def close(position_id: int):

    try:
        pf.close_position(engine, position_id)
    except KeyError:
        raise HTTPException(404, "No such position")
    except ValueError as e:
        raise HTTPException(409, str(e))

    return {"closed": position_id}


@router.delete("/portfolio/{position_id}", status_code=204)
def delete(position_id: int):
    pf.delete_position(engine, position_id)


@router.get("/portfolio/signal-tracker")
@cached(ttl=600)
def signal_tracker():
    return pf.signal_tracker(engine)


@router.get("/backtest")
@cached(ttl=3600)
def backtest():
    """Walk-forward backtest summary and equity curves."""

    summary_path = BACKTEST_DIR / "summary.csv"

    if not summary_path.exists():
        raise HTTPException(404, "No backtest yet; run app.scripts.backtest")

    summary = pd.read_csv(summary_path, index_col=0)

    curves = pd.read_csv(
        BACKTEST_DIR / "equity_curves.csv", index_col=0, parse_dates=True
    )

    return {
        "summary": [
            {"strategy": name, **{k: (None if pd.isna(v) else v) for k, v in r.items()}}
            for name, r in summary.iterrows()
        ],
        "curves": {
            "dates": [f"{d:%Y-%m-%d}" for d in curves.index],
            "series": {
                col: [None if pd.isna(v) else round(v, 4) for v in curves[col]]
                for col in curves
            },
        },
    }

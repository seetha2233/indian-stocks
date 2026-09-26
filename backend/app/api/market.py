import pandas as pd
import yfinance as yf
from fastapi import APIRouter
from sqlalchemy import text

from app.core.cache import cached
from app.db.database import engine
from app.services.features import FEATURES_TABLE
from app.services.signals import MIN_TURNOVER_CR, SIGNALS_TABLE


router = APIRouter(prefix="/api/market", tags=["market"])

INDICES = {
    "NIFTY 50": "^NSEI",
    "SENSEX": "^BSESN",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY IT": "^CNXIT",
}


def _latest(table: str) -> pd.DataFrame:

    return pd.read_sql(
        text(
            f"SELECT * FROM {table} WHERE timestamp = "
            f"(SELECT max(timestamp) FROM {table})"
        ),
        engine,
        parse_dates=["timestamp"]
    )


@router.get("/indices")
@cached(ttl=60)
def indices():
    """Live index levels from Yahoo (cached 60s)."""

    out = []

    for name, symbol in INDICES.items():

        try:
            hist = yf.Ticker(symbol).history(period="5d")["Close"].dropna()
            price, prev = float(hist.iloc[-1]), float(hist.iloc[-2])
        except Exception:
            continue

        out.append({
            "name": name,
            "symbol": symbol,
            "price": round(price, 2),
            "change": round(price - prev, 2),
            "change_percent": round((price / prev - 1) * 100, 2),
            "as_of": f"{hist.index[-1]:%Y-%m-%d}",
        })

    return out


@router.get("/overview")
@cached(ttl=300)
def overview():
    """Breadth, movers, sectors and signal mix across all covered stocks."""

    feats = _latest(FEATURES_TABLE)
    sig = _latest(SIGNALS_TABLE)

    df = feats.merge(
        sig[["symbol", "long_name", "sector", "signal", "risk", "price", "turnover_cr"]],
        on="symbol"
    )
    df["symbol"] = df["symbol"].str.removesuffix(".NS")

    def movers(frame: pd.DataFrame) -> list[dict]:
        return [
            {
                "symbol": r.symbol,
                "name": r.long_name,
                "price": round(r.price, 2),
                "change_percent": round(r.ret_1d * 100, 2),
            }
            for r in frame.itertuples()
        ]

    # Movers among tradable stocks only; otherwise the list fills up with
    # thinly traded stocks moving by their price band
    liquid = df[df["turnover_cr"].fillna(0) >= MIN_TURNOVER_CR]

    sectors = (
        df.groupby("sector")
        .agg(
            stocks=("symbol", "count"),
            ret_1d=("ret_1d", "mean"),
            ret_20d=("ret_20d", "mean"),
            above_sma_20=("dist_sma_20", lambda s: (s > 0).mean()),
        )
        .sort_values("ret_20d", ascending=False)
        .reset_index()
    )

    for col in ("ret_1d", "ret_20d", "above_sma_20"):
        sectors[col] = (sectors[col] * 100).round(2)

    return {
        "as_of": f"{df['timestamp'].iloc[0]:%Y-%m-%d}",
        "breadth": {
            "advancing": int((df["ret_1d"] > 0).sum()),
            "declining": int((df["ret_1d"] < 0).sum()),
            "unchanged": int((df["ret_1d"] == 0).sum()),
            "above_sma_20_pct": round(float((df["dist_sma_20"] > 0).mean() * 100), 1),
            "above_sma_50_pct": round(float((df["dist_sma_50"] > 0).mean() * 100), 1),
        },
        "market": {
            "equal_weight_ret_1d": round(float(df["ret_1d"].mean() * 100), 2),
            "equal_weight_ret_20d": round(float(df["ret_20d"].mean() * 100), 2),
            "volatility_20d": round(float(df["mkt_volatility_20d"].iloc[0] * 100), 2),
        },
        "stocks": int(len(df)),
        "movers_min_turnover_cr": MIN_TURNOVER_CR,
        "gainers": movers(liquid.nlargest(5, "ret_1d")),
        "losers": movers(liquid.nsmallest(5, "ret_1d")),
        "sectors": sectors.to_dict("records"),
        "signals": df["signal"].value_counts().to_dict(),
        "risk": df["risk"].value_counts().to_dict(),
    }

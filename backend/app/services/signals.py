"""Signal engine: turns features, model predictions and fundamentals into
the per-stock card (signal, entry zone, targets, stop loss, risk, scores).

What is validated and what isn't:
  - Targets, upside probability and risk come from the walk-forward-tested
    models (they rank volatility / range well; see models/xgb/metrics.json).
  - Technical, momentum and fundamental scores are percentile ranks within
    all covered stocks today. They describe a stock; they are not forecasts.
  - The WATCH / NEUTRAL / AVOID rule combines those scores. It is a
    transparent heuristic and has not been shown to beat the market.

Stocks that traded on the signal day but have too little history for the
models (new listings, or a recent corporate action restarting the count)
still get a limited card: price, fundamentals, news and liquidity, with
signal NEW or LIMITED and no targets, risk or technical scores.
"""

import json

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.features import FEATURES_TABLE, MIN_HISTORY
from app.services.fundamentals import load_fundamentals
from app.services.news import news_scores
from app.services.universe import listing_dates, load_nifty100, universe_table


SIGNALS_TABLE = "stock_signals"

PREDICTIONS_TABLE = "stock_predictions"

TRADING_DAYS = 248

# Score components: feature -> True if higher is more bullish
TECHNICAL = {
    "dist_sma_20": True,
    "dist_sma_50": True,
    "sma_10_50": True,
    "macd_hist": True,
    "range_pos_20": True,
}

MOMENTUM = {
    "ret_20d": True,
    "ret_40d": True,
    "rel_ret_20d": True,
    "rsi_14": True,
}

# Price levels, in multiples of ATR (average daily range)
ENTRY_ATR = 0.5
STOP_ATR = 2.0

WATCH_MIN_SCORE = 60

# WATCH needs at least this median daily traded value (Rs crore, 20 days),
# the same bar the backtest uses: thinner stocks can't be traded reliably
MIN_TURNOVER_CR = 5
AVOID_MAX_SCORE = 40

# Signals from the models; the other two mark cards without model output
MODEL_SIGNALS = ("WATCH", "NEUTRAL", "AVOID")
NEW_LISTING = "NEW"
LIMITED = "LIMITED"

# A stock is NEW if NSE lists it at most this many days before its first bar
LISTING_SLACK_DAYS = 10

DISCLAIMER = (
    "Research output, not investment advice. Targets and probabilities are "
    "statistical estimates of price range, not predictions of direction. "
    "See Backtest for how the models have actually performed."
)


def _latest(engine: Engine, table: str) -> pd.DataFrame:

    return pd.read_sql(
        text(
            f"SELECT * FROM {table} WHERE timestamp = "
            f"(SELECT max(timestamp) FROM {table})"
        ),
        engine,
        parse_dates=["timestamp"]
    )


def _score(df: pd.DataFrame, components: dict) -> pd.Series:
    """Average percentile rank across the universe, 0-100."""

    ranks = [
        df[col].rank(pct=True) if up else 1 - df[col].rank(pct=True)
        for col, up in components.items()
    ]

    return pd.concat(ranks, axis=1).mean(axis=1) * 100


def _risk_level(vol: pd.Series) -> pd.Series:
    """Terciles of predicted volatility within the universe."""

    return pd.qcut(
        vol.rank(method="first"), 3, labels=["Low", "Medium", "High"]
    ).astype(str)


def _signal(row: pd.Series) -> str:

    if (
        row["composite_score"] >= WATCH_MIN_SCORE
        and row["technical_score"] >= 50
        and row["risk"] != "High"
        and row["turnover_cr"] >= MIN_TURNOVER_CR
    ):
        return "WATCH"

    if row["composite_score"] < AVOID_MAX_SCORE or (
        row["technical_score"] < 30 and row["momentum_score"] < 30
    ):
        return "AVOID"

    return "NEUTRAL"


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def _reasons(row: pd.Series, universe: pd.DataFrame) -> list[str]:
    """Plain-language, rule-based reasons behind the card."""

    reasons = []

    d50 = row["dist_sma_50"]
    reasons.append(
        f"Price is {abs(d50) * 100:.1f}% {'above' if d50 > 0 else 'below'} "
        f"its 50-day average"
        + (" and the 10-day average is above the 50-day (uptrend)"
           if row["sma_10_50"] > 0 else
           " and the 10-day average is below the 50-day (downtrend)")
    )

    reasons.append(
        f"{_pct(row['ret_20d'])} over 20 days, "
        f"#{int(row['ret_20d_rank'])} of {len(universe)} stocks"
    )

    if row["rsi_14"] >= 70:
        reasons.append(f"RSI {row['rsi_14']:.0f}: overbought, pullbacks are common")
    elif row["rsi_14"] <= 30:
        reasons.append(f"RSI {row['rsi_14']:.0f}: oversold")

    if row["turnover_cr"] < MIN_TURNOVER_CR:
        reasons.append(
            f"Thinly traded: about Rs {row['turnover_cr']:.2f} crore a day, so "
            f"it can't be WATCH (needs Rs {MIN_TURNOVER_CR:.0f} crore)"
        )

    if row["volume_ratio_20"] >= 1.5:
        reasons.append(
            f"Volume {row['volume_ratio_20']:.1f}x its 20-day average"
        )

    reasons.append(
        f"Model: {row['pred_hit_5pct_20d']:.0%} chance of touching +5% within "
        f"20 trading days (median across stocks {row['upside_median']:.0%})"
    )

    reasons.append(
        f"{row['risk']} risk: expected daily swing about "
        f"{row['pred_vol_20d'] * 100:.1f}% over the next 20 days"
    )

    if pd.notna(row.get("news_score")):
        tone = (
            "positive" if row["news_score"] >= 60 else
            "negative" if row["news_score"] <= 40 else "mixed"
        )
        reasons.append(
            f"News tone {tone} ({row['news_score']:.0f}/100 from "
            f"{row['news_count']} relevant articles in 5 days)"
        )

    pillars = {
        "valuation": row.get("valuation_score"),
        "quality": row.get("quality_score"),
        "growth": row.get("growth_score"),
        "balance sheet": row.get("leverage_score"),
    }
    pillars = {k: v for k, v in pillars.items() if pd.notna(v)}

    if pillars:
        best = max(pillars, key=pillars.get)
        worst = min(pillars, key=pillars.get)
        reasons.append(
            f"Fundamentals vs peers: strongest on {best} "
            f"({pillars[best]:.0f}/100), weakest on {worst} "
            f"({pillars[worst]:.0f}/100)"
        )

    return reasons


def _turnover(engine: Engine) -> pd.DataFrame:
    """Median daily traded value over the last 20 trading days, Rs crore."""

    return pd.read_sql(
        text(
            "WITH ranked AS (SELECT symbol, close * volume AS v, "
            "row_number() OVER (PARTITION BY symbol ORDER BY timestamp DESC) AS n "
            "FROM stock_prices) "
            "SELECT symbol, percentile_cont(0.5) WITHIN GROUP (ORDER BY v) / 1e7 "
            "AS turnover_cr FROM ranked WHERE n <= 20 GROUP BY symbol"
        ),
        engine
    )


def _limited_reasons(row: pd.Series) -> list[str]:
    """Reasons for a card without model output."""

    bars, first = int(row["bars"]), pd.Timestamp(row["first_day"])
    days = f"{bars} trading day{'s' if bars != 1 else ''}"

    if row["signal"] == NEW_LISTING:
        listed = row["listed_on"] if pd.notna(row["listed_on"]) else first
        reasons = [
            f"New on the NSE main board (listed {listed:%d %b %Y}): "
            f"{days} of prices so far",
        ]
        if bars > 1:
            reasons.append(
                f"{_pct(row['price'] / row['first_close'] - 1)} since its first "
                f"close of Rs {row['first_close']:,.2f}"
            )
    elif bars <= MIN_HISTORY:
        reasons = [
            f"Rarely traded: only {days} with trades in the last 6 months "
            f"(first on {first:%d %b %Y})"
        ]
    else:
        reasons = [
            "Too little clean price history for the models: a corporate action "
            "or a one-day move of -40%/+50% restarts the count"
        ]

    reasons.append(
        f"Signal, targets, stop loss, risk and technical scores need "
        f"{MIN_HISTORY + 1} trading days (about 2.5 months) of prices; "
        f"they appear once it has them"
    )

    if row["turnover_cr"] < MIN_TURNOVER_CR:
        reasons.append(
            f"Thinly traded: about Rs {row['turnover_cr']:.2f} crore a day"
        )

    if pd.notna(row.get("news_score")):
        tone = (
            "positive" if row["news_score"] >= 60 else
            "negative" if row["news_score"] <= 40 else "mixed"
        )
        reasons.append(
            f"News tone {tone} ({row['news_score']:.0f}/100 from "
            f"{row['news_count']} relevant articles in 5 days)"
        )

    return reasons


def _limited_cards(
    engine: Engine,
    day: pd.Timestamp,
    covered: set[str],
    fundamentals: pd.DataFrame,
    news: pd.DataFrame,
) -> pd.DataFrame:
    """Cards for stocks that traded on `day` but have no feature row.

    These are mostly new listings (fewer than MIN_HISTORY + 1 days of
    prices); the rest lost their history to a corporate-action break.
    """

    df = pd.read_sql(
        text(
            "WITH s AS (SELECT symbol, count(*) AS bars, min(timestamp) AS first_day "
            "FROM stock_prices GROUP BY symbol) "
            "SELECT p.symbol, p.timestamp, p.close AS price, s.bars, s.first_day, "
            "f.close AS first_close FROM stock_prices p "
            "JOIN s ON s.symbol = p.symbol "
            "JOIN stock_prices f ON f.symbol = p.symbol AND f.timestamp = s.first_day "
            "WHERE p.timestamp = :ts"
        ),
        engine,
        params={"ts": pd.Timestamp(day).to_pydatetime()},
        parse_dates=["timestamp", "first_day"]
    )

    df = df[~df["symbol"].isin(covered)].reset_index(drop=True)

    if df.empty:
        return df

    df = (
        df.merge(
            fundamentals[[
                "symbol", "long_name", "sector", "industry", "market_cap",
                "pe", "pb", "roe", "valuation_score", "quality_score",
                "growth_score", "leverage_score", "fundamental_score",
            ]],
            on="symbol",
            how="left"
        )
        .merge(news, on="symbol", how="left")
        .merge(_turnover(engine), on="symbol", how="left")
    )

    df["news_score"] = df["news_score"].astype(float)
    df["news_count"] = df["news_count"].fillna(0).astype(int)
    df["turnover_cr"] = df["turnover_cr"].fillna(0.0)

    # NEW only if NSE's listing date is about where its prices start;
    # otherwise the short history is thin trading or a resumed stock
    df["listed_on"] = df["symbol"].map(listing_dates())
    new = (df["bars"] <= MIN_HISTORY) & (
        df["listed_on"].isna()
        | (df["listed_on"] >= df["first_day"] - pd.Timedelta(days=LISTING_SLACK_DAYS))
    )
    df["signal"] = np.where(new, NEW_LISTING, LIMITED)

    df["reasons"] = [
        json.dumps(_limited_reasons(row)) for _, row in df.iterrows()
    ]

    return df


def build_signals(engine: Engine) -> pd.DataFrame:

    features = _latest(engine, FEATURES_TABLE)
    preds = _latest(engine, PREDICTIONS_TABLE)

    if features["timestamp"].iloc[0] != preds["timestamp"].iloc[0]:
        raise ValueError(
            "stock_predictions is out of date; run app.scripts.predict first"
        )

    fundamentals = load_fundamentals(engine)

    df = (
        features.drop(columns=["close"])
        .merge(preds, on=["symbol", "timestamp"])
        .merge(
            fundamentals[[
                "symbol", "long_name", "sector", "industry", "market_cap",
                "pe", "pb", "roe", "valuation_score", "quality_score",
                "growth_score", "leverage_score", "fundamental_score",
            ]],
            on="symbol",
            how="left"
        )
        .reset_index(drop=True)
    )

    df["technical_score"] = _score(df, TECHNICAL)
    df["momentum_score"] = _score(df, MOMENTUM)

    try:
        news = news_scores(engine)
    except Exception:
        # No news table yet (ingest_news hasn't run)
        news = pd.DataFrame(columns=["symbol", "news_score", "news_count"])

    df = df.merge(news, on="symbol", how="left")
    df["news_score"] = df["news_score"].astype(float)
    df["news_count"] = df["news_count"].fillna(0).astype(int)

    score_cols = [
        "technical_score", "momentum_score", "fundamental_score", "news_score"
    ]
    df["composite_score"] = df[score_cols].mean(axis=1)

    df["risk"] = _risk_level(df["pred_vol_20d"])
    df["annual_vol"] = df["pred_vol_20d"] * np.sqrt(TRADING_DAYS)

    price = df["price"]
    atr = df["atr_14"] * price

    df["entry_low"] = price - ENTRY_ATR * atr
    df["entry_high"] = price
    df["target_1"] = df["high_price_5d"]
    # Quantile models can cross; keep targets ordered
    df["target_2"] = np.maximum(df["high_price_20d"], df["target_1"])
    df["stop_loss"] = price - STOP_ATR * atr
    df["risk_reward"] = (df["target_2"] - price) / (price - df["stop_loss"])

    df["upside_prob_20d"] = df["pred_hit_5pct_20d"]

    df = df.merge(_turnover(engine), on="symbol", how="left")
    df["turnover_cr"] = df["turnover_cr"].fillna(0.0)

    df["signal"] = df.apply(_signal, axis=1)

    df["ret_20d_rank"] = df["ret_20d"].rank(ascending=False, method="min")
    df["upside_median"] = df["pred_hit_5pct_20d"].median()

    df["reasons"] = [
        json.dumps(_reasons(row, df)) for _, row in df.iterrows()
    ]

    limited = _limited_cards(
        engine, df["timestamp"].iloc[0], set(df["symbol"]), fundamentals, news
    )

    if not limited.empty:
        df = pd.concat([df, limited], ignore_index=True)

    nifty100 = {f"{s}.NS" for s in load_nifty100()}
    df["nifty100"] = df["symbol"].isin(nifty100)

    names = universe_table("nse").set_index("symbol")["long_name"]
    df["long_name"] = df["long_name"].fillna(df["symbol"].map(names))

    columns = [
        "symbol", "timestamp", "long_name", "sector", "industry",
        "market_cap", "price", "signal",
        "entry_low", "entry_high", "target_1", "target_2", "stop_loss",
        "risk_reward", "upside_prob_20d", "pred_hit_5pct_5d",
        "pred_high_1d", "pred_high_5d", "pred_high_20d",
        "risk", "pred_vol_20d", "annual_vol",
        "technical_score", "momentum_score", "fundamental_score",
        "news_score", "news_count", "composite_score",
        "valuation_score", "quality_score", "growth_score", "leverage_score",
        "pe", "pb", "roe", "rsi_14", "ret_20d", "dist_sma_50",
        "turnover_cr", "nifty100", "reasons",
    ]

    return df[columns].sort_values(
        "composite_score", ascending=False
    ).reset_index(drop=True)


def card(row: dict) -> dict:
    """Shape one stock_signals row as the API's stock card."""

    def r(x, nd=2):
        return None if x is None or pd.isna(x) else round(float(x), nd)

    def t(x):
        # Text fields are NaN for stocks Yahoo has no profile for
        return None if x is None or (isinstance(x, float) and pd.isna(x)) else x

    return {
        "symbol": row["symbol"].removesuffix(".NS"),
        "name": t(row["long_name"]),
        "sector": t(row["sector"]),
        "as_of": pd.Timestamp(row["timestamp"]).strftime("%Y-%m-%d"),
        "price": r(row["price"]),
        "signal": row["signal"],
        "entry_zone": [r(row["entry_low"]), r(row["entry_high"])],
        "target_1": r(row["target_1"]),
        "target_2": r(row["target_2"]),
        "stop_loss": r(row["stop_loss"]),
        "risk_reward": r(row["risk_reward"]),
        "upside_prob_20d": r(row["upside_prob_20d"], 3),
        "risk": t(row["risk"]),
        "annual_volatility": r(row["annual_vol"], 3),
        "turnover_cr": r(row.get("turnover_cr"), 2),
        "nifty100": bool(row.get("nifty100")) if row.get("nifty100") is not None else False,
        "scores": {
            "technical": r(row["technical_score"], 0),
            "fundamental": r(row["fundamental_score"], 0),
            "news": r(row["news_score"], 0),
            "news_articles": (
                int(row["news_count"]) if pd.notna(row.get("news_count")) else 0
            ),
            "momentum": r(row["momentum_score"], 0),
            "composite": r(row["composite_score"], 0),
        },
        "fundamentals": {
            "pe": r(row["pe"], 1),
            "pb": r(row["pb"], 1),
            "roe": r(row["roe"], 3),
            "valuation": r(row["valuation_score"], 0),
            "quality": r(row["quality_score"], 0),
            "growth": r(row["growth_score"], 0),
            "balance_sheet": r(row["leverage_score"], 0),
        },
        "why": json.loads(row["reasons"]),
        "definitions": {
            "entry_zone": f"today's price down to {ENTRY_ATR} x ATR below it",
            "target_1": "median forecast of the 1-week high (~50% chance)",
            "target_2": "median forecast of the 20-day high (~50% chance)",
            "stop_loss": f"{STOP_ATR} x ATR below today's price",
            "upside_prob_20d": "chance the price touches +5% within 20 trading days",
            "risk": "tercile of predicted 20-day volatility across all covered stocks",
            "scores": "percentile vs all covered NSE stocks today (100 = best)",
            "news_score": "recency-weighted LLM sentiment of the last 5 days (50 = neutral); empty with fewer than 2 relevant articles",
            "liquidity": f"median daily traded value, last 20 days; WATCH needs Rs {MIN_TURNOVER_CR} crore",
        },
        "disclaimer": DISCLAIMER,
    }


COMPACT_FIELDS = (
    "symbol", "name", "sector", "price", "signal", "upside_prob_20d", "risk",
    "annual_volatility", "risk_reward", "turnover_cr", "nifty100", "scores",
)


def compact_card(row: dict) -> dict:
    """Just what the screener table needs."""

    c = card(row)
    return {k: c[k] for k in COMPACT_FIELDS}

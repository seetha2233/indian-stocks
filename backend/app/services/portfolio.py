"""Paper portfolio and forward signal tracking.

Paper positions close themselves on the first trading day after entry
whose low reaches the stop (checked first: conservative) or whose high
reaches the target. Gaps fill at the open. P&L includes the same round-trip
costs as the backtest.

The signal tracker measures what actually happened after each day's
WATCH / NEUTRAL / AVOID signals. It only has as much history as the daily
refresh has recorded, so it starts empty and grows.
"""

from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import bindparam, text
from sqlalchemy.engine import Engine

from app.services.backtest import ROUND_TRIP_COST
from app.services.ingestion import normalize_symbol
from app.services.signals import MODEL_SIGNALS, SIGNALS_TABLE


POSITIONS_TABLE = "paper_positions"

TRACK_HORIZONS = (5, 20)


def ensure_table(engine: Engine) -> None:

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {POSITIONS_TABLE} (
                id SERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                opened_on DATE NOT NULL,
                entry_price DOUBLE PRECISION NOT NULL,
                quantity INTEGER NOT NULL,
                target DOUBLE PRECISION,
                stop_loss DOUBLE PRECISION,
                signal TEXT,
                note TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                closed_on DATE,
                exit_price DOUBLE PRECISION,
                exit_reason TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT now()
            )
        """))


def _bars(engine: Engine, symbol: str, after: date) -> pd.DataFrame:
    """Raw (as traded) daily bars strictly after `after`."""

    return pd.read_sql(
        text(
            "SELECT timestamp::date AS day, open, high, low, close "
            "FROM stock_prices WHERE symbol = :s AND timestamp::date > :d "
            "ORDER BY timestamp"
        ),
        engine,
        params={"s": symbol, "d": after}
    )


def _latest_close(engine: Engine, symbol: str) -> tuple[date, float]:

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT timestamp::date, close FROM stock_prices "
                "WHERE symbol = :s ORDER BY timestamp DESC LIMIT 1"
            ),
            {"s": symbol}
        ).first()

    if row is None:
        raise ValueError(f"No prices for {symbol}")

    return row[0], float(row[1])


def open_position(
    engine: Engine,
    symbol: str,
    quantity: int,
    entry_price: float | None = None,
    target: float | None = None,
    stop_loss: float | None = None,
    note: str | None = None,
) -> int:
    """Open at the latest close unless a price is given. Target and stop
    default to the stock card's Target 2 and stop loss."""

    ensure_table(engine)

    symbol = normalize_symbol(symbol)

    day, close = _latest_close(engine, symbol)

    card = pd.read_sql(
        text(
            f"SELECT target_2, stop_loss, signal FROM {SIGNALS_TABLE} "
            f"WHERE symbol = :s ORDER BY timestamp DESC LIMIT 1"
        ),
        engine,
        params={"s": symbol}
    )

    signal = None
    if not card.empty:
        # NEW / LIMITED cards have no target or stop; the position then
        # stays open until closed by hand
        if target is None and pd.notna(card["target_2"].iloc[0]):
            target = float(card["target_2"].iloc[0])
        if stop_loss is None and pd.notna(card["stop_loss"].iloc[0]):
            stop_loss = float(card["stop_loss"].iloc[0])
        signal = card["signal"].iloc[0]

    with engine.begin() as conn:
        return conn.execute(
            text(
                f"INSERT INTO {POSITIONS_TABLE} (symbol, opened_on, entry_price, "
                f"quantity, target, stop_loss, signal, note) VALUES "
                f"(:symbol, :day, :price, :qty, :target, :stop, :signal, :note) "
                f"RETURNING id"
            ),
            {
                "symbol": symbol, "day": day,
                "price": entry_price if entry_price is not None else close,
                "qty": quantity, "target": target, "stop": stop_loss,
                "signal": signal, "note": note,
            }
        ).scalar()


def _check_exit(pos: dict, bars: pd.DataFrame) -> tuple[date, float, str] | None:

    stop, target = pos["stop_loss"], pos["target"]

    for bar in bars.itertuples():

        if stop is not None and bar.low <= stop:
            return bar.day, min(stop, bar.open), "stop"

        if target is not None and bar.high >= target:
            return bar.day, max(target, bar.open), "target"

    return None


def update_positions(engine: Engine) -> int:
    """Close open positions whose stop or target has been hit."""

    ensure_table(engine)

    positions = pd.read_sql(
        text(f"SELECT * FROM {POSITIONS_TABLE} WHERE status = 'open'"), engine
    )

    closed = 0

    for pos in positions.to_dict("records"):

        hit = _check_exit(pos, _bars(engine, pos["symbol"], pos["opened_on"]))

        if hit:
            close_position(engine, pos["id"], *hit)
            closed += 1

    return closed


def close_position(
    engine: Engine,
    position_id: int,
    day: date | None = None,
    price: float | None = None,
    reason: str = "manual",
) -> None:

    with engine.begin() as conn:

        pos = conn.execute(
            text(f"SELECT symbol, status FROM {POSITIONS_TABLE} WHERE id = :id"),
            {"id": position_id}
        ).first()

        if pos is None:
            raise KeyError(position_id)
        if pos.status != "open":
            raise ValueError("Position is already closed")

    if price is None:
        day, price = _latest_close(engine, pos.symbol)

    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {POSITIONS_TABLE} SET status = 'closed', closed_on = :d, "
                f"exit_price = :p, exit_reason = :r WHERE id = :id"
            ),
            {"d": day, "p": price, "r": reason, "id": position_id}
        )


def delete_position(engine: Engine, position_id: int) -> None:

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {POSITIONS_TABLE} WHERE id = :id"),
            {"id": position_id}
        )


def portfolio(engine: Engine) -> dict:

    update_positions(engine)

    df = pd.read_sql(
        text(f"SELECT * FROM {POSITIONS_TABLE} ORDER BY created_at DESC"), engine
    )

    half = ROUND_TRIP_COST / 2

    rows = []

    for p in df.to_dict("records"):

        if p["status"] == "open":
            as_of, price = _latest_close(engine, p["symbol"])
        else:
            as_of, price = p["closed_on"], p["exit_price"]

        cost_basis = p["entry_price"] * (1 + half) * p["quantity"]
        value = price * (1 - half) * p["quantity"]

        rows.append({
            "id": p["id"],
            "symbol": p["symbol"].removesuffix(".NS"),
            "status": p["status"],
            "signal": p["signal"],
            "opened_on": str(p["opened_on"]),
            "entry_price": round(p["entry_price"], 2),
            "quantity": p["quantity"],
            "target": None if pd.isna(p["target"]) else round(p["target"], 2),
            "stop_loss": None if pd.isna(p["stop_loss"]) else round(p["stop_loss"], 2),
            "price": round(price, 2),
            "as_of": str(as_of),
            "closed_on": None if p["closed_on"] is None or pd.isna(p["closed_on"]) else str(p["closed_on"]),
            "exit_reason": None if pd.isna(p["exit_reason"]) else p["exit_reason"],
            "cost_basis": round(cost_basis, 2),
            "value": round(value, 2),
            "pnl": round(value - cost_basis, 2),
            "pnl_pct": round((value / cost_basis - 1) * 100, 2),
            "note": None if pd.isna(p["note"]) else p["note"],
        })

    closed = [r for r in rows if r["status"] == "closed"]
    open_ = [r for r in rows if r["status"] == "open"]

    return {
        "positions": rows,
        "summary": {
            "open_positions": len(open_),
            "open_value": round(sum(r["value"] for r in open_), 2),
            "unrealized_pnl": round(sum(r["pnl"] for r in open_), 2),
            "closed_positions": len(closed),
            "realized_pnl": round(sum(r["pnl"] for r in closed), 2),
            "win_rate": (
                round(sum(r["pnl"] > 0 for r in closed) / len(closed) * 100, 1)
                if closed else None
            ),
            "costs_included": f"{ROUND_TRIP_COST:.1%} round trip",
        },
    }


def signal_tracker(engine: Engine) -> dict:
    """Forward returns after each recorded day's signals."""

    signals = pd.read_sql(
        text(
            f"SELECT symbol, timestamp, signal, price FROM {SIGNALS_TABLE} "
            f"WHERE signal IN :signals"
        ).bindparams(bindparam("signals", expanding=True)),
        engine,
        params={"signals": list(MODEL_SIGNALS)},
        parse_dates=["timestamp"]
    )

    prices = pd.read_sql(
        text("SELECT symbol, timestamp, close FROM stock_prices"),
        engine,
        parse_dates=["timestamp"]
    ).pivot(index="timestamp", columns="symbol", values="close")

    dates = prices.index
    pos = {d: i for i, d in enumerate(dates)}

    rows = []

    for r in signals.itertuples():

        i = pos.get(r.timestamp)
        if i is None:
            continue

        out = {"signal": r.signal, "date": r.timestamp}

        for h in TRACK_HORIZONS:
            if i + h < len(dates):
                out[f"ret_{h}d"] = prices[r.symbol].iloc[i + h] / prices[r.symbol].iloc[i] - 1

        rows.append(out)

    df = pd.DataFrame(rows)

    result = {
        "signal_days": int(signals["timestamp"].nunique()),
        "first_day": f"{signals['timestamp'].min():%Y-%m-%d}" if len(signals) else None,
        "horizons": {},
    }

    for h in TRACK_HORIZONS:

        col = f"ret_{h}d"

        if col not in df or df[col].notna().sum() == 0:
            result["horizons"][f"{h}d"] = {
                "status": f"waiting: needs {h} trading days after the first signal day"
            }
            continue

        done = df.dropna(subset=[col])
        all_mean = done[col].mean()

        result["horizons"][f"{h}d"] = {
            "signal_days": int(done["date"].nunique()),
            "all_stocks_avg": round(all_mean * 100, 2),
            "by_signal": {
                s: {
                    "count": int(len(g)),
                    "avg_return": round(g[col].mean() * 100, 2),
                    "vs_all": round((g[col].mean() - all_mean) * 100, 2),
                    "win_rate": round((g[col] > 0).mean() * 100, 1),
                }
                for s, g in done.groupby("signal")
            },
        }

    return result

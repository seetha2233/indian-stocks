"""Walk-forward backtest of the +5% model against simple baselines.

Run build_dataset first. Results go to data/backtest/.

Usage (from backend/):
    python -m app.scripts.backtest
"""

from pathlib import Path

import pandas as pd

from app.db.database import engine
from app.services.backtest import (
    MIN_TURNOVER,
    ROUND_TRIP_COST,
    TOP_N,
    Market,
    Strategy,
    buy_and_hold,
    run_strategy,
    summarize,
    walk_forward_predictions
)
from app.services.features import load_prices
from app.services.model import load_dataset


OUT_DIR = Path(__file__).resolve().parents[3] / "data" / "backtest"

STRATEGIES = [
    Strategy(f"Model top {TOP_N}, sell at +5%", "p_hit", "fixed"),
    Strategy(f"Model top {TOP_N}, sell at predicted high", "p_hit", "predicted"),
    Strategy(f"Most volatile {TOP_N}, sell at +5%", "atr_14", "fixed"),
    Strategy("All liquid stocks, sell at +5%", None, "fixed"),
    Strategy(f"Model top {TOP_N}, hold 5 days", "p_hit", "none"),
    Strategy("All liquid stocks, hold 5 days", None, "none"),
]


def main() -> None:

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    df = load_dataset(engine)

    print("Walk-forward training...")
    preds = walk_forward_predictions(df)

    start, end = preds["timestamp"].min(), preds["timestamp"].max()
    print(
        f"Out-of-sample signals: {start:%Y-%m-%d} -> {end:%Y-%m-%d} "
        f"({preds['timestamp'].nunique()} days)\n"
    )

    market = Market(load_prices(engine))

    curves, rows = [], {}

    for strategy in STRATEGIES:
        equity, trades = run_strategy(strategy, preds, market)
        curves.append(equity)
        rows[strategy.name] = summarize(equity, trades)

        gross, _ = run_strategy(strategy, preds, market, cost=0.0)
        rows[strategy.name]["gross_return"] = gross.iloc[-1] - 1
        trades.to_csv(
            OUT_DIR / f"trades_{strategy.score or 'all'}_{strategy.limit}.csv",
            index=False
        )

    bh = buy_and_hold(market, start, curves[0].index[-1])
    curves.append(bh)
    rows[bh.name] = summarize(bh, None)
    rows[bh.name]["gross_return"] = rows[bh.name]["total_return"]

    table = pd.DataFrame(rows).T

    table = table[["gross_return"] + [c for c in table if c != "gross_return"]]

    pct_cols = [
        "gross_return", "total_return", "annual_return", "annual_vol", "max_drawdown",
        "win_rate", "avg_trade", "hit_limit",
    ]

    show = table.copy()

    for col in pct_cols:
        show[col] = show[col].map(
            lambda x: "" if pd.isna(x) else f"{x * 100:.1f}%"
        )

    show["sharpe"] = show["sharpe"].map(lambda x: f"{x:.2f}")
    show["trades"] = show["trades"].map(
        lambda x: "" if pd.isna(x) else f"{int(x)}"
    )
    show["avg_days"] = show["avg_days"].map(
        lambda x: "" if pd.isna(x) else f"{x:.1f}"
    )

    show.columns = [
        "Before costs", "Total", "Annual", "Vol", "Sharpe", "Max DD",
        "Trades", "Win %", "Avg trade", "Hit limit", "Days held",
    ]

    pd.set_option("display.width", 220)

    print(
        f"Costs: {ROUND_TRIP_COST:.2%} per round trip. Only stocks trading at "
        f"least Rs {MIN_TURNOVER / 1e7:.0f} crore a day (median, 20 days).\n"
    )
    print(show.to_string())

    pd.concat(curves, axis=1).to_csv(OUT_DIR / "equity_curves.csv")
    table.to_csv(OUT_DIR / "summary.csv")
    preds.to_csv(OUT_DIR / "walk_forward_predictions.csv", index=False)

    print(f"\nSaved equity curves, trades and summary to {OUT_DIR}")


if __name__ == "__main__":
    main()

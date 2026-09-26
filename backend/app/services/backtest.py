"""Walk-forward backtest of the +5% model.

1. Walk-forward predictions: every RETRAIN_EVERY trading days, retrain on
   only the rows whose 5-day outcome was already known at that point, then
   predict the next RETRAIN_EVERY days. No prediction ever sees its future.

2. Trading rules, for each signal day t (after the close):
   - pick the top N stocks by a score
   - buy at the open of t+1
   - place a sell limit; exit there on the first day the high reaches it
     (at the open instead, if the stock gaps above it)
   - otherwise sell at the close of day t+5
   - skip a pick if t+1 opens at or above its limit already

3. Portfolio: capital split into 5 sleeves. Each day's picks go to one
   sleeve, which is busy for exactly 5 days, so every sleeve is always
   invested and no cohort overlaps another in the same sleeve.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.services.dataset import HIT_THRESHOLD, HORIZON_DAYS
from app.services.features import FEATURE_COLUMNS
from app.services.model import HOLDOUT_STOCKS, _make_model, _predict


RETRAIN_EVERY = 10

# First walk-forward fold starts after this many dates of history
# (sized for ~6 months of prices)
MIN_TRAIN_DATES = 30

# Only trade stocks with at least this median daily traded value over the
# last 20 days (Rs). Keeps out illiquid small caps, including ones locked
# at a price band where an order couldn't actually be filled.
MIN_TURNOVER = 5e7

# Round trip for NSE delivery: STT 0.1% x2, stamp duty, exchange/SEBI
# fees, GST, DP charge, plus slippage. Charged half on entry, half on exit.
ROUND_TRIP_COST = 0.003

TOP_N = 10

TRADING_DAYS = 248


def walk_forward_predictions(df: pd.DataFrame) -> pd.DataFrame:

    dates = np.sort(df["timestamp"].unique())

    out = []

    for start in range(MIN_TRAIN_DATES, len(dates), RETRAIN_EVERY):

        # At the close of dates[start], outcomes are known for rows
        # up to dates[start - HORIZON_DAYS]
        known = dates[: start - HORIZON_DAYS + 1]

        fit_rows = df[df["timestamp"].isin(known)]
        fold = df[df["timestamp"].isin(dates[start:start + RETRAIN_EVERY])]

        # Early stopping on held-out stocks, as in model.split_for_target
        symbols = fit_rows["symbol"].unique()
        rng = np.random.default_rng(start)
        holdout = rng.choice(symbols, int(len(symbols) * HOLDOUT_STOCKS), replace=False)
        in_holdout = fit_rows["symbol"].isin(holdout)
        train, valid = fit_rows[~in_holdout], fit_rows[in_holdout]

        preds = fold[["symbol", "timestamp", "atr_14"]].copy()

        for target, col in (
            ("target_hit_5pct_5d", "p_hit"),
            ("target_high_5d", "pred_high_5d"),
        ):
            model = _make_model(target)

            model.fit(
                train[FEATURE_COLUMNS], train[target],
                eval_set=[(valid[FEATURE_COLUMNS], valid[target])],
                verbose=False
            )

            preds[col] = _predict(model, fold[FEATURE_COLUMNS])

        out.append(preds)

    return pd.concat(out, ignore_index=True)


@dataclass
class Strategy:
    name: str
    # column to rank by (descending); None = trade every stock
    score: str | None
    # "fixed": entry * (1 + HIT_THRESHOLD); "predicted": close_t * (1 + pred);
    # "none": no limit, always sell at the day-5 close
    limit: str


class Market:
    """Wide date x symbol price matrices on the shared trading calendar."""

    def __init__(self, prices: pd.DataFrame):

        wide = prices.pivot(index="timestamp", columns="symbol")

        self.dates = wide.index
        self.symbols = wide.columns.get_level_values(1).unique()

        self.open = wide["open"]
        self.high = wide["high"]
        self.close = wide["close"]

        # For marking positions: last known close
        self.mark = self.close.ffill()

        self.pos = {d: i for i, d in enumerate(self.dates)}

        # NumPy views for the per-trade loop (pandas lookups are too slow
        # across thousands of stocks)
        self.col = {sym: j for j, sym in enumerate(self.close.columns)}
        self.open_np = self.open.to_numpy()
        self.high_np = self.high.to_numpy()
        self.close_np = self.close.to_numpy()
        self.mark_np = self.mark.to_numpy()

        turnover = (wide["close"] * wide["volume"]).rolling(20, min_periods=10).median()
        self.liquid_np = (turnover >= MIN_TURNOVER).to_numpy()


def simulate_trade(
    m: Market,
    symbol: str,
    t: int,
    limit_price: float | None,
    cost: float = ROUND_TRIP_COST
) -> tuple[list[float], dict] | None:
    """Simulate one trade signalled at date index t.

    Returns the position's value (entry cost = 1) at each close from t+1 to
    t+5, and a trade record. None if the trade can't or shouldn't happen.
    """

    half = cost / 2

    if t + HORIZON_DAYS >= len(m.dates):
        return None

    j = m.col[symbol]

    entry = m.open_np[t + 1, j]

    if not np.isfinite(entry):
        return None

    if limit_price is None:
        limit_price = entry * (1 + HIT_THRESHOLD)

    if entry >= limit_price:
        return None

    cost_basis = entry * (1 + half)

    path = []
    exit_price, exit_day = None, None

    for k in range(1, HORIZON_DAYS + 1):

        i = t + k

        if exit_price is None:

            day_open = m.open_np[i, j]
            day_high = m.high_np[i, j]

            if np.isfinite(day_high) and day_high >= limit_price:
                gapped = k > 1 and np.isfinite(day_open) and day_open >= limit_price
                exit_price = day_open if gapped else limit_price
                exit_day = k

            elif k == HORIZON_DAYS:
                exit_price = m.mark_np[i, j]
                exit_day = k

        if exit_price is not None:
            path.append(exit_price * (1 - half) / cost_basis)
        else:
            path.append(m.mark_np[i, j] / cost_basis)

    record = {
        "symbol": symbol,
        "signal_date": m.dates[t],
        "entry": entry,
        "limit": limit_price,
        "exit": exit_price,
        "days_held": exit_day,
        "hit_limit": exit_price >= limit_price,
        "return": path[-1] - 1,
    }

    return path, record


def run_strategy(
    strategy: Strategy,
    preds: pd.DataFrame,
    m: Market,
    top_n: int = TOP_N,
    cost: float = ROUND_TRIP_COST
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily portfolio equity and the list of trades."""

    signal_dates = np.sort(preds["timestamp"].unique())

    # Each sleeve holds 1/5 of capital; value path per sleeve, by date index
    n_sleeves = HORIZON_DAYS
    sleeve_value = [1.0 / n_sleeves] * n_sleeves
    daily: dict[int, list[float]] = {}

    trades = []

    by_day = dict(tuple(preds.groupby("timestamp")))

    first = m.pos[pd.Timestamp(signal_dates[0])]

    for n, day in enumerate(signal_dates):

        t = m.pos[pd.Timestamp(day)]
        sleeve = n % n_sleeves

        picks = by_day[day]

        # Tradable stocks only (see MIN_TURNOVER)
        liquid = m.liquid_np[t]
        picks = picks[[liquid[m.col[sym]] for sym in picks["symbol"]]]

        if strategy.score is not None:
            picks = picks.nlargest(top_n, strategy.score)

        paths = []

        for row in picks.itertuples():

            if strategy.limit == "predicted":
                limit = m.close_np[t, m.col[row.symbol]] * (1 + row.pred_high_5d)
            elif strategy.limit == "none":
                limit = np.inf
            else:
                limit = None

            result = simulate_trade(m, row.symbol, t, limit, cost)

            if result is None:
                continue

            path, record = result
            paths.append(path)
            trades.append(record)

        start_value = sleeve_value[sleeve]

        # No trades that day: the sleeve sits in cash for the 5 days
        if paths:
            cohort = np.mean(paths, axis=0)
        else:
            cohort = np.ones(HORIZON_DAYS)

        for k in range(HORIZON_DAYS):
            daily.setdefault(t + 1 + k, [0.0] * n_sleeves)
            daily[t + 1 + k][sleeve] = start_value * cohort[k]

        sleeve_value[sleeve] = start_value * cohort[-1]

    # Stitch sleeves into one equity curve. A sleeve that hasn't started
    # yet (first 4 days) is still cash at its starting value.
    equity = {}
    last = [1.0 / n_sleeves] * n_sleeves

    for i in range(first + 1, max(daily) + 1):
        vals = daily.get(i, last)
        vals = [v if v else last[s] for s, v in enumerate(vals)]
        last = vals
        equity[m.dates[i]] = sum(vals)

    return pd.Series(equity, name=strategy.name), pd.DataFrame(trades)


def buy_and_hold(m: Market, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Equal-weight all liquid stocks at the first open, hold to the end."""

    t = m.pos[start]
    entry = m.open.iloc[t + 1]

    liquid = pd.Series(m.liquid_np[t], index=m.close.columns)
    held = entry.index[entry.notna() & liquid.reindex(entry.index).fillna(False)]

    curve = (
        m.mark.loc[m.dates[t + 1]:end, held]
        .div(entry[held] * (1 + ROUND_TRIP_COST / 2))
        .mean(axis=1)
    )

    return curve.rename("Buy & hold (all liquid stocks)")


def summarize(equity: pd.Series, trades: pd.DataFrame | None) -> dict:

    daily_ret = equity.pct_change().dropna()

    years = len(daily_ret) / TRADING_DAYS

    total = equity.iloc[-1] / 1.0 - 1

    drawdown = equity / equity.cummax() - 1

    out = {
        "total_return": total,
        "annual_return": (1 + total) ** (1 / years) - 1,
        "annual_vol": daily_ret.std() * np.sqrt(TRADING_DAYS),
        "sharpe": (
            daily_ret.mean() / daily_ret.std() * np.sqrt(TRADING_DAYS)
            if daily_ret.std() > 0 else np.nan
        ),
        "max_drawdown": drawdown.min(),
    }

    if trades is not None and len(trades):
        out.update(
            trades=len(trades),
            win_rate=(trades["return"] > 0).mean(),
            avg_trade=trades["return"].mean(),
            hit_limit=trades["hit_limit"].mean(),
            avg_days=trades["days_held"].mean(),
        )

    return out

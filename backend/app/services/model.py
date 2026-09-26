"""XGBoost models for the ml_dataset targets.

One model per target:
    target_ret_1d, target_ret_5d      expected return (mean)
    target_high_1d/_5d/_20d           median high: ~50% chance of reaching it
    target_hit_5pct_5d/_20d           probability the high reaches +5%
    target_vol_20d                    risk model: next-20-day daily volatility

Evaluation is honest: fit on `train`, pick the number of trees on `valid`,
score once on `test`. The saved (final) models are refit on all labelled
rows with that tree count, for live predictions.
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from scipy.stats import spearmanr
from sklearn.metrics import log_loss, mean_absolute_error, roc_auc_score
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.services.dataset import (
    TARGET_HORIZON,
    CLASSIFICATION_TARGETS,
    DATASET_TABLE,
    REGRESSION_TARGETS,
    TARGET_COLUMNS
)
from app.services.features import FEATURE_COLUMNS


MODEL_DIR = Path(__file__).resolve().parents[3] / "models" / "xgb"

# Deliberately conservative: the data is small (~30k rows) and noisy
PARAMS = dict(
    n_estimators=2000,
    learning_rate=0.03,
    max_depth=4,
    min_child_weight=50,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_lambda=5.0,
    tree_method="hist",
    early_stopping_rounds=100,
    random_state=42,
    n_jobs=-1,
)

TOP_N = 10

# Share of the most recent dates held out as the test period
TEST_FRACTION = 0.25

# Share of stocks held out (on training dates) for early stopping
HOLDOUT_STOCKS = 0.2

# Highs are right-skewed (a few big spikes), so the mean overstates what's
# typically reachable. Predict the median instead.
HIGH_QUANTILE = 0.5


def load_dataset(engine: Engine) -> pd.DataFrame:

    return pd.read_sql(
        text(f"SELECT * FROM {DATASET_TABLE}"),
        engine,
        parse_dates=["timestamp"]
    )


def _make_model(target: str, n_estimators: int | None = None):

    params = dict(PARAMS)

    if n_estimators is not None:
        params["n_estimators"] = n_estimators
        params.pop("early_stopping_rounds")

    if target in CLASSIFICATION_TARGETS:
        return xgb.XGBClassifier(
            objective="binary:logistic", eval_metric="logloss", **params
        )

    if target.startswith("target_high"):
        return xgb.XGBRegressor(
            objective="reg:quantileerror",
            quantile_alpha=HIGH_QUANTILE,
            **params
        )

    return xgb.XGBRegressor(
        objective="reg:squarederror", eval_metric="mae", **params
    )


def _predict(model, X: pd.DataFrame) -> np.ndarray:

    if isinstance(model, xgb.XGBClassifier):
        return model.predict_proba(X)[:, 1]

    return model.predict(X)


def _daily_rank_ic(test: pd.DataFrame, pred: np.ndarray, target: str) -> float:
    """Mean per-day Spearman correlation between prediction and outcome.

    Measures how well the model ranks stocks against each other on the same
    day, which is what matters for picking stocks.
    """

    frame = pd.DataFrame(
        {"t": test["timestamp"].values, "p": pred, "y": test[target].values}
    )

    ics = [
        spearmanr(g["p"], g["y"]).statistic
        for _, g in frame.groupby("t")
        if len(g) >= 10 and g["p"].nunique() > 1
    ]

    return float(np.nanmean(ics))


def _top_n_mean(test: pd.DataFrame, pred: np.ndarray, target: str) -> float:
    """Average outcome of the TOP_N highest-predicted stocks each day."""

    frame = pd.DataFrame(
        {"t": test["timestamp"].values, "p": pred, "y": test[target].values}
    )

    return float(
        frame.sort_values("p", ascending=False)
        .groupby("t").head(TOP_N)["y"].mean()
    )


def _evaluate(
    target: str,
    train: pd.DataFrame,
    test: pd.DataFrame,
    pred: np.ndarray
) -> dict:

    y = test[target].to_numpy()

    metrics: dict = {
        "rank_ic": _daily_rank_ic(test, pred, target),
        f"top{TOP_N}_actual": _top_n_mean(test, pred, target),
        "all_actual": float(y.mean()),
    }

    if target in CLASSIFICATION_TARGETS:

        base_rate = float(train[target].mean())

        metrics.update(
            auc=float(roc_auc_score(y, pred)),
            log_loss=float(log_loss(y, pred)),
            baseline_log_loss=float(
                log_loss(y, np.full_like(pred, base_rate))
            ),
            mean_predicted=float(pred.mean()),
        )

        return metrics

    center = (
        train[target].quantile(HIGH_QUANTILE)
        if target.startswith("target_high")
        else train[target].mean()
    )

    baseline = np.full_like(y, center)

    metrics.update(
        mae=float(mean_absolute_error(y, pred)),
        baseline_mae=float(mean_absolute_error(y, baseline)),
    )

    if target.startswith("target_ret"):
        nonzero = y != 0
        metrics["direction_accuracy"] = float(
            (np.sign(pred[nonzero]) == np.sign(y[nonzero])).mean()
        )

    if target.startswith("target_high"):
        # How often the actual high reached the predicted high
        metrics["reached_predicted_high"] = float((y >= pred).mean())
        metrics["baseline_reached"] = float((y >= baseline).mean())

    if target == "target_vol_20d":
        # Naive risk forecast: next 20 days look like the last 20
        metrics["persistence_mae"] = float(
            mean_absolute_error(y, test["volatility_20d"])
        )

    return metrics


def _logit(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def _fit_calibration(pred: np.ndarray, y: np.ndarray) -> dict:

    from sklearn.linear_model import LogisticRegression

    lr = LogisticRegression(C=1e6).fit(_logit(pred).reshape(-1, 1), y)

    return {"a": float(lr.coef_[0][0]), "b": float(lr.intercept_[0])}


def _calibrate(pred: np.ndarray, c: dict) -> np.ndarray:
    return 1 / (1 + np.exp(-(c["a"] * _logit(pred) + c["b"])))


def split_for_target(df: pd.DataFrame, target: str) -> tuple[pd.DataFrame, ...]:
    """(train, early-stopping, test) rows for one target.

    Test: the last TEST_FRACTION of the dates that have this target.
    Train: dates before that, minus the target's horizon, so no training
    outcome overlaps the test period. Early stopping uses a random
    HOLDOUT_STOCKS share of stocks on the training dates: with only ~6
    months of prices there aren't enough dates for a separate validation
    period. It's slightly optimistic (same-day moves are correlated) but it
    only picks the tree count; every reported score comes from test.
    """

    rows = df.dropna(subset=[target])
    dates = np.sort(rows["timestamp"].unique())

    test_start = int(len(dates) * (1 - TEST_FRACTION))
    train_dates = dates[: max(0, test_start - TARGET_HORIZON[target])]

    test = rows[rows["timestamp"] >= dates[test_start]]
    fit_rows = rows[rows["timestamp"].isin(train_dates)]

    symbols = fit_rows["symbol"].unique()
    rng = np.random.default_rng(PARAMS["random_state"])
    holdout = set(rng.choice(symbols, int(len(symbols) * HOLDOUT_STOCKS), replace=False))

    in_holdout = fit_rows["symbol"].isin(holdout)

    return fit_rows[~in_holdout], fit_rows[in_holdout], test


def train_and_evaluate(df: pd.DataFrame) -> dict:

    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "features": FEATURE_COLUMNS,
        "stocks": int(df["symbol"].nunique()),
        "targets": {},
    }

    for target in TARGET_COLUMNS:

        train, stop, test = split_for_target(df, target)
        labelled = df.dropna(subset=[target])

        model = _make_model(target)

        model.fit(
            train[FEATURE_COLUMNS], train[target],
            eval_set=[(stop[FEATURE_COLUMNS], stop[target])],
            verbose=False
        )

        n_trees = model.best_iteration + 1

        pred = _predict(model, test[FEATURE_COLUMNS])

        metrics = _evaluate(target, train, test, pred)

        if target in CLASSIFICATION_TARGETS:
            # Platt scaling on the test period: with few dates the raw
            # probabilities drift from observed hit rates
            metrics["calibration"] = _fit_calibration(pred, test[target].to_numpy())
            cal = _calibrate(pred, metrics["calibration"])
            metrics["calibrated_mean_predicted"] = float(cal.mean())

        metrics.update(
            n_trees=n_trees,
            train_rows=len(train),
            train_dates=int(train["timestamp"].nunique()),
            test_rows=len(test),
            test_dates=int(test["timestamp"].nunique()),
            test_period=[
                f"{test['timestamp'].min():%Y-%m-%d}",
                f"{test['timestamp'].max():%Y-%m-%d}",
            ],
        )

        importance = pd.Series(
            model.feature_importances_, index=FEATURE_COLUMNS
        ).nlargest(8)
        metrics["top_features"] = importance.round(4).to_dict()

        # Final model on all labelled data, same tree count
        final = _make_model(target, n_estimators=n_trees)
        final.fit(labelled[FEATURE_COLUMNS], labelled[target], verbose=False)
        final.save_model(MODEL_DIR / f"{target}.json")

        report["targets"][target] = metrics

    # Headline test period: the 5-day targets'
    report["test_period"] = report["targets"]["target_hit_5pct_5d"]["test_period"]

    (MODEL_DIR / "metrics.json").write_text(json.dumps(report, indent=2))

    return report


def load_models() -> dict:

    models = {}

    for target in TARGET_COLUMNS:
        model = _make_model(target, n_estimators=1)
        model.load_model(MODEL_DIR / f"{target}.json")
        models[target] = model

    return models


def predict(features: pd.DataFrame, models: dict) -> pd.DataFrame:

    out = features[["symbol", "timestamp"]].copy()

    X = features[FEATURE_COLUMNS]

    metrics_path = MODEL_DIR / "metrics.json"
    targets = json.loads(metrics_path.read_text())["targets"] if metrics_path.exists() else {}

    for target, model in models.items():
        pred = _predict(model, X)
        if "calibration" in targets.get(target, {}):
            pred = _calibrate(pred, targets[target]["calibration"])
        out[target.replace("target_", "pred_")] = pred

    return out

"""Train XGBoost models on ml_dataset and report test-period results.

Run build_dataset first. Models are saved to models/xgb/.

Usage (from backend/):
    python -m app.scripts.train_model
"""

from app.db.database import engine
from app.services.model import MODEL_DIR, TOP_N, load_dataset, train_and_evaluate


def pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def main() -> None:

    report = train_and_evaluate(load_dataset(engine))

    print(f"{report['stocks']} stocks\n")

    for target, m in report["targets"].items():

        start, end = m["test_period"]
        print(
            f"{target}  ({m['n_trees']} trees; trained on {m['train_dates']} dates, "
            f"tested on {m['test_dates']} dates {start} -> {end})"
        )

        if "auc" in m:
            print(
                f"  AUC {m['auc']:.3f} | log loss {m['log_loss']:.4f} "
                f"vs baseline {m['baseline_log_loss']:.4f}\n"
                f"  mean predicted prob {m['mean_predicted']:.1%} "
                f"(calibrated {m['calibrated_mean_predicted']:.1%}) "
                f"vs actual {m['all_actual']:.1%}\n"
                f"  hit rate of daily top {TOP_N}: {m[f'top{TOP_N}_actual']:.1%}"
            )
        else:
            gain = 1 - m["mae"] / m["baseline_mae"]
            print(
                f"  MAE {m['mae'] * 100:.3f}% vs baseline "
                f"{m['baseline_mae'] * 100:.3f}% ({gain:+.1%})\n"
                f"  daily top {TOP_N} averaged {pct(m[f'top{TOP_N}_actual'])} "
                f"vs all stocks {pct(m['all_actual'])}"
            )

            if "direction_accuracy" in m:
                print(f"  direction accuracy {m['direction_accuracy']:.1%}")

            if "persistence_mae" in m:
                gain = 1 - m["mae"] / m["persistence_mae"]
                print(
                    f"  vs 'last 20 days' forecast: MAE "
                    f"{m['persistence_mae'] * 100:.3f}% ({gain:+.1%})"
                )

            if "reached_predicted_high" in m:
                print(
                    "  actual high reached prediction "
                    f"{m['reached_predicted_high']:.1%} of the time "
                    f"(baseline {m['baseline_reached']:.1%})"
                )

        print(f"  rank IC {m['rank_ic']:+.3f}")
        print(f"  top features: {', '.join(list(m['top_features'])[:5])}\n")

    print(f"Saved models + metrics.json to {MODEL_DIR}")


if __name__ == "__main__":
    main()

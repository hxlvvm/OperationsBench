"""Pre-registered evaluation (DESIGN.md): does a learned ranking find more future acute use than prior acute
use alone, at a fixed review budget? Fits on the 2023-12-31 snapshot, scores the 2024-12-31 snapshot once.

Usage: python -m opsbench.evaluate <csv_dir> <out_dir>
"""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from opsbench import warehouse

TRAIN_SNAPSHOT, TEST_SNAPSHOT = "2023-12-31", "2024-12-31"
BUDGET = 0.10  # review the top 10% of eligible patients
FEATURES = ["age", "female", "acute_12m", "acute_12_24m", "urgent_12m", "office_12m", "wellness_24m",
            "post_acute_24m", "log_cost_12m", "days_since_acute", "n_active_disorders"]
CANDIDATES = {
    **{f"logreg_C{c}": make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=2000)) for c in (0.01, 0.1, 1.0)},
    "hgb": HistGradientBoostingClassifier(random_state=0),
}


def bucket(patient_id):
    """Stable 0-99 bucket per patient, so a patient is in the same split at every snapshot."""
    return int(hashlib.sha256(patient_id.encode()).hexdigest(), 16) % 100


def baseline_score(df):
    """Prior acute use: last 12 months first, the 12 months before that as tie-break."""
    return (df.acute_12m + 0.01 * df.acute_12_24m).to_numpy(float)


def capture(y, score, budget=BUDGET):
    """Share of positives in the top `budget` fraction. Ties at the threshold count by their expected share,
    so a score with many ties (the baseline) is not helped or hurt by row order."""
    k = budget * len(y)
    order = np.sort(score)[::-1]
    threshold = order[int(np.ceil(k)) - 1]
    above, tied = score > threshold, score == threshold
    slots = k - above.sum()
    return (y[above].sum() + y[tied].sum() * slots / tied.sum()) / y.sum()


def metrics(y, score):
    return {"auroc": roc_auc_score(y, score), "ap": average_precision_score(y, score),
            f"capture_top{int(BUDGET * 100)}pct": capture(y, score)}


def paired_bootstrap(y, a, b, n=2000, seed=0):
    """95% CI of metric(b) - metric(a), resampling patients."""
    rng = np.random.default_rng(seed)
    diffs = {"ap": [], "capture": []}
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].sum() == 0:
            continue
        diffs["ap"].append(average_precision_score(y[i], b[i]) - average_precision_score(y[i], a[i]))
        diffs["capture"].append(capture(y[i], b[i]) - capture(y[i], a[i]))
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in diffs.items()}


def main(csv_dir, out_dir):
    con = warehouse.build(csv_dir)
    train_all = warehouse.model_rows(con, TRAIN_SNAPSHOT)
    test = warehouse.model_rows(con, TEST_SNAPSHOT)
    train_all["bucket"] = train_all.patient_id.map(bucket)
    test = test[test.patient_id.map(bucket) >= 80]
    train, val = train_all[train_all.bucket < 60], train_all[train_all.bucket.between(60, 79)]

    val_ap = {}
    for name, model in CANDIDATES.items():
        model.fit(train[FEATURES], train.label)
        val_ap[name] = average_precision_score(val.label, model.predict_proba(val[FEATURES])[:, 1])
    chosen = max(val_ap, key=val_ap.get)

    y = test.label.to_numpy()
    base = baseline_score(test)
    prob = CANDIDATES[chosen].predict_proba(test[FEATURES])[:, 1]
    ci = paired_bootstrap(y, base, prob)
    result = {
        "snapshots": {"train": TRAIN_SNAPSHOT, "test": TEST_SNAPSHOT},
        "n": {"train": len(train), "validation": len(val), "test": len(test)},
        "positives": {"train": int(train.label.sum()), "validation": int(val.label.sum()), "test": int(y.sum())},
        "validation_ap": val_ap,
        "chosen_model": chosen,
        "test": {"baseline_prior_acute_use": metrics(y, base),
                 chosen: {**metrics(y, prob), "brier": brier_score_loss(y, prob)}},
        "model_minus_baseline_95ci": ci,
        "adopt_model": ci["capture"][0] > 0,
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "evaluation.json").write_text(json.dumps(result, indent=2, default=float))
    print(json.dumps(result, indent=2, default=float))


if __name__ == "__main__":
    main(*sys.argv[1:3])

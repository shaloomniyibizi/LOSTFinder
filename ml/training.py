"""
Train, evaluate and save the two models.

Match model
    Input: the features of a (lost, found) pair (ml.features).
    Output: probability that both reports describe the same object.
    Two algorithms are trained on the same split (logistic regression and a
    random forest); the one with the better F1 score is kept. The existing
    rule-based score (items.matching, "score >= 35") is evaluated on the same
    test set as a baseline.

Category model
    Input: report title and description.
    Output: the item category (TF-IDF + logistic regression).

Each model is saved with joblib as {"model": ..., "meta": ...} in
settings.ML_MODEL_DIR, and recorded as an active ml.ModelVersion.
"""

import json

import joblib
import numpy as np
import sklearn
from django.conf import settings
from django.utils import timezone
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, classification_report, confusion_matrix, f1_score,
    precision_score, recall_score, roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from items.matching import MIN_MATCH_SCORE, calculate_match

from . import dataset, synthetic
from .features import FEATURE_LABELS, FEATURE_NAMES, pair_features
from .models import ModelVersion


MATCH_FILE = "match_model.joblib"
CATEGORY_FILE = "category_model.joblib"
MATCH_THRESHOLD = 0.5


def model_path(kind):
    name = MATCH_FILE if kind == ModelVersion.Kind.MATCH else CATEGORY_FILE
    return settings.ML_MODEL_DIR / name


def _binary_metrics(y_true, y_pred, y_prob=None):
    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1]).tolist(),
    }
    if y_prob is not None and len(set(y_true)) > 1:
        metrics["roc_auc"] = roc_auc_score(y_true, y_prob)
    return {k: round(v, 4) if isinstance(v, float) else v for k, v in metrics.items()}


def _version(kind):
    return f"{kind}-{timezone.now():%Y%m%d-%H%M%S}"


def _save(kind, model, meta, register):
    path = model_path(kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "meta": meta}, path, compress=3)
    path.with_suffix(".json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if register:
        ModelVersion.objects.filter(kind=kind).update(is_active=False)
        ModelVersion.objects.update_or_create(
            version=meta["version"],
            defaults=dict(
                kind=kind, algorithm=meta["algorithm"],
                trained_at=meta["trained_at"], metrics=meta["metrics"],
                n_train=meta["samples"]["train"], n_test=meta["samples"]["test"],
                n_real=meta["samples"]["real"], n_synthetic=meta["samples"]["synthetic"],
                is_active=True,
            ),
        )
    return path


def train_match_model(real_pairs=(), n_objects=1500, seed=42, register=True):
    synthetic_pairs = synthetic.match_pairs(n_objects=n_objects, seed=seed)
    pairs = list(synthetic_pairs) + list(real_pairs)

    X = np.array([pair_features(lost, found) for lost, found, _ in pairs])
    y = np.array([label for _, _, label in pairs])
    # Rule-based score for the baseline comparison.
    rules = np.array([calculate_match(lost, found)[0] for lost, found, _ in pairs])

    X_train, X_test, y_train, y_test, _, rules_test = train_test_split(
        X, y, rules, test_size=0.2, random_state=seed, stratify=y,
    )

    candidates = {
        "Logistic regression": make_pipeline(
            StandardScaler(), LogisticRegression(max_iter=1000, class_weight="balanced"),
        ),
        "Random forest": RandomForestClassifier(
            n_estimators=150, max_depth=12, min_samples_leaf=3,
            class_weight="balanced", random_state=seed, n_jobs=-1,
        ),
    }
    results = {}
    for name, model in candidates.items():
        model.fit(X_train, y_train)
        prob = model.predict_proba(X_test)[:, 1]
        results[name] = _binary_metrics(y_test, (prob >= MATCH_THRESHOLD).astype(int), prob)

    best_name = max(results, key=lambda n: (results[n]["f1"], results[n].get("roc_auc", 0)))
    best = candidates[best_name]
    # Single-row predictions are faster without the process pool.
    if isinstance(best, RandomForestClassifier):
        best.set_params(n_jobs=1)

    if isinstance(best, RandomForestClassifier):
        weights = best.feature_importances_
    else:
        coef = np.abs(best[-1].coef_[0])
        weights = coef / coef.sum()
    importances = sorted(
        ({"feature": f, "label": FEATURE_LABELS[f], "importance": round(float(w), 4)}
         for f, w in zip(FEATURE_NAMES, weights)),
        key=lambda row: row["importance"], reverse=True,
    )

    baseline = _binary_metrics(
        y_test, (rules_test >= MIN_MATCH_SCORE).astype(int), rules_test / 100,
    )

    meta = {
        "kind": ModelVersion.Kind.MATCH,
        "version": _version("match"),
        "trained_at": timezone.now().isoformat(),
        "algorithm": best_name,
        "threshold": MATCH_THRESHOLD,
        "feature_names": FEATURE_NAMES,
        "feature_importances": importances,
        "metrics": results[best_name],
        "compared": results,
        "baseline_rules": baseline,
        "samples": {
            "train": len(y_train), "test": len(y_test),
            "real": len(real_pairs), "synthetic": len(synthetic_pairs),
            "positive": int(y.sum()), "negative": int(len(y) - y.sum()),
        },
        "sklearn": sklearn.__version__,
    }
    path = _save(ModelVersion.Kind.MATCH, best, meta, register)
    return meta, path


def train_category_model(real_samples=(), n_samples=3000, seed=7, register=True):
    synthetic_samples = synthetic.category_samples(n=n_samples, seed=seed)
    samples = list(synthetic_samples) + list(real_samples)
    texts = [f"{title}. {description}" for title, description, _ in samples]
    labels = [category for _, _, category in samples]

    # Stratify only when every category has at least two examples (a
    # category created on the site may have a single report).
    counts = {label: labels.count(label) for label in set(labels)}
    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.2, random_state=seed,
        stratify=labels if min(counts.values()) >= 2 else None,
    )
    model = make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1),
        LogisticRegression(max_iter=2000, C=5),
    )
    model.fit(X_train, y_train)
    predicted = model.predict(X_test)

    report = classification_report(y_test, predicted, output_dict=True, zero_division=0)
    classes = list(model.classes_)
    metrics = {
        "accuracy": round(accuracy_score(y_test, predicted), 4),
        "f1_macro": round(f1_score(y_test, predicted, average="macro"), 4),
        "per_class_f1": {c: round(report[c]["f1-score"], 4) for c in classes if c in report},
        "confusion_matrix": confusion_matrix(y_test, predicted, labels=classes).tolist(),
    }
    meta = {
        "kind": ModelVersion.Kind.CATEGORY,
        "version": _version("category"),
        "trained_at": timezone.now().isoformat(),
        "algorithm": "TF-IDF + logistic regression",
        "classes": classes,
        "metrics": metrics,
        "samples": {
            "train": len(y_train), "test": len(y_test),
            "real": len(real_samples), "synthetic": len(synthetic_samples),
        },
        "sklearn": sklearn.__version__,
    }
    path = _save(ModelVersion.Kind.CATEGORY, model, meta, register)
    return meta, path


def train_all(data=None, n_objects=1500, n_category_samples=3000, seed=42, register=True):
    """Train both models from an API snapshot (dict) plus synthetic data."""
    match_meta, _ = train_match_model(
        dataset.real_match_pairs(data), n_objects=n_objects, seed=seed, register=register,
    )
    category_meta, _ = train_category_model(
        dataset.real_category_samples(data), n_samples=n_category_samples,
        seed=seed, register=register,
    )
    return {"match": match_meta, "category": category_meta}

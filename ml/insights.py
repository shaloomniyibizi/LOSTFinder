"""
The "AI insights" part of the dashboard (dashboard.metrics.build_dashboard).

Reviewers see campus-wide numbers; everyone else sees predictions about
their own reports. Everything returned is JSON-safe, because the dashboard
page polls it and redraws the panel without reloading.
"""

from datetime import datetime

from django.db.models import Avg, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.timesince import timesince

from items.matching import MIN_MATCH_SCORE, ML_MATCH_THRESHOLD
from items.models import MatchSuggestion

from . import predictor
from .models import CategoryPrediction, ModelVersion


BINS = 10
LATEST = 8


def _pct(value):
    return "–" if value is None else f"{round(value * 100)}%"


def _suggestions(user, reviewer):
    queryset = MatchSuggestion.objects.filter(ml_probability__isnull=False)
    if not reviewer:
        queryset = queryset.filter(Q(lost_item__reporter=user) | Q(found_item__reporter=user))
    return queryset


def _category_predictions(user, reviewer):
    queryset = CategoryPrediction.objects.select_related(
        "lost_item__category", "found_item__category",
    )
    if not reviewer:
        queryset = queryset.filter(Q(lost_item__reporter=user) | Q(found_item__reporter=user))
    return queryset


def _agreement(suggestions):
    """How often the model agreed with the people who decided on a match."""
    decided = suggestions.exclude(status=MatchSuggestion.Status.PENDING)
    total = decided.count()
    if not total:
        return None, 0
    threshold = 0.5
    agreed = decided.filter(
        Q(status=MatchSuggestion.Status.ACCEPTED, ml_probability__gte=threshold)
        | Q(status=MatchSuggestion.Status.REJECTED, ml_probability__lt=threshold)
    ).count()
    return agreed / total, total


def _histogram(suggestions):
    counts = [0] * BINS
    for p in suggestions.values_list("ml_probability", flat=True):
        counts[min(int(p * BINS), BINS - 1)] += 1
    step = 100 // BINS
    return {
        "labels": [f"{n * step}–{(n + 1) * step}%" for n in range(BINS)],
        "values": counts,
    }


def _latest(suggestions):
    rows = []
    for s in suggestions.select_related("lost_item", "found_item").order_by("-created_at")[:LATEST]:
        rows.append({
            "lost": s.lost_item.title,
            "found": s.found_item.title,
            "probability": s.ml_percent,
            "rule_score": s.score,
            "model_only": s.score < MIN_MATCH_SCORE,
            "status": s.status,
            "status_display": s.get_status_display(),
            "when": timesince(s.created_at).split(",")[0],
            "url": reverse("lost_item_detail", args=[s.lost_item_id]),
        })
    return rows


def _category_rows(predictions):
    rows = []
    for p in predictions[:5]:
        item = p.item
        kind = "lost" if p.lost_item_id else "found"
        rows.append({
            "title": item.title,
            "kind": kind,
            "reported": item.category.name,
            "predicted": p.predicted_name,
            "confidence": round(p.confidence * 100),
            "agrees": p.agrees,
            "url": reverse(f"{kind}_item_detail", args=[item.pk]),
        })
    return rows


def _model_summary(kind):
    meta = predictor.model_info(kind)
    if meta is None:
        return None
    m, n = meta["metrics"], meta["samples"]
    summary = {
        "kind": kind,
        "label": ModelVersion.Kind(kind).label,
        "version": meta["version"],
        "algorithm": meta["algorithm"],
        "trained": timesince(datetime.fromisoformat(meta["trained_at"])).split(",")[0],
        "accuracy": _pct(m.get("accuracy")),
        "samples": n["train"] + n["test"],
        "real": n["real"],
        "synthetic": n["synthetic"],
    }
    if kind == ModelVersion.Kind.MATCH:
        summary.update(
            f1=_pct(m.get("f1")), auc=_pct(m.get("roc_auc")),
            baseline_f1=_pct(meta["baseline_rules"].get("f1")),
        )
    else:
        summary.update(f1=_pct(m.get("f1_macro")))
    return summary


def ml_dashboard(user, reviewer):
    suggestions = _suggestions(user, reviewer)
    categories = _category_predictions(user, reviewer)
    today = timezone.localdate()

    agreement, decided = _agreement(suggestions)
    avg = suggestions.filter(status=MatchSuggestion.Status.PENDING).aggregate(
        value=Avg("ml_probability"))["value"]
    category_total = categories.count()
    category_agree = categories.filter(agrees=True).count()

    match_meta = predictor.model_info(ModelVersion.Kind.MATCH)
    features = match_meta["feature_importances"] if match_meta else []

    return {
        "enabled": match_meta is not None,
        "threshold": round(ML_MATCH_THRESHOLD * 100),
        "stats": [
            {"key": "ml_scored_today", "label": "Matches scored today",
             "value": suggestions.filter(created_at__date=today).count(),
             "icon": "bi-cpu", "color": "primary",
             "hint": f"{suggestions.count()} in total"},
            {"key": "ml_avg_confidence", "label": "Avg. confidence (pending)",
             "value": _pct(avg), "icon": "bi-speedometer", "color": "info",
             "hint": "Mean model probability"},
            {"key": "ml_model_only", "label": "Found only by the model",
             "value": suggestions.filter(score__lt=MIN_MATCH_SCORE).count(),
             "icon": "bi-stars", "color": "warning",
             "hint": "Rule score too low to suggest"},
            {"key": "ml_agreement", "label": "Agrees with users",
             "value": _pct(agreement), "icon": "bi-hand-thumbs-up", "color": "success",
             "hint": f"Over {decided} decided match{'es' if decided != 1 else ''}"},
            {"key": "ml_category_agreement", "label": "Category agreement",
             "value": _pct(category_agree / category_total) if category_total else "–",
             "icon": "bi-tags", "color": "secondary",
             "hint": f"{category_total - category_agree} report(s) may be miscategorised"},
        ],
        "charts": {
            "ml_confidence": _histogram(suggestions),
            "ml_features": {
                "labels": [f["label"] for f in features],
                "values": [round(f["importance"] * 100, 1) for f in features],
            },
        },
        "latest": _latest(suggestions),
        "categories": _category_rows(categories),
        "models": [s for s in (_model_summary(k) for k in ModelVersion.Kind.values) if s],
    }

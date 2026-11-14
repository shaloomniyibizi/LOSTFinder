from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import is_reviewer, profile_completed_required
from items.models import ItemCategory

from . import dataset, predictor, training
from .models import ModelVersion
from .services import rescore_all


@login_required
@profile_completed_required
def model_report(request):
    """Full evaluation of the active models (security staff and admins)."""
    if not is_reviewer(request.user):
        raise PermissionDenied
    match = predictor.model_info(ModelVersion.Kind.MATCH)
    category = predictor.model_info(ModelVersion.Kind.CATEGORY)

    comparison = []
    if match:
        rows = list(match["compared"].items()) + [("Rule-based engine (baseline)", match["baseline_rules"])]
        comparison = [{"name": name, "kept": name == match["algorithm"], **values}
                      for name, values in rows]

    category_rows = []
    if category:
        matrix = category["metrics"]["confusion_matrix"]
        for name, row in zip(category["classes"], matrix):
            total = sum(row)
            category_rows.append({
                "name": name,
                "f1": category["metrics"]["per_class_f1"].get(name),
                "support": total,
                "cells": row,
            })

    return render(request, "ml/model_report.html", {
        "match": match,
        "category": category,
        "comparison": comparison,
        "category_rows": category_rows,
        "history": ModelVersion.objects.all()[:10],
        "snapshot": dataset.read_snapshot(),
    })


@login_required
@require_POST
def retrain(request):
    """Retrain both models from current data (staff only), then re-score."""
    if not request.user.is_staff:
        raise PermissionDenied
    # In-process, the same data the API's training-data endpoint serves.
    result = training.train_all(dataset.export_training_data())
    done = rescore_all()
    messages.success(
        request,
        f"Models retrained. Match model: {result['match']['algorithm']}, "
        f"F1 {result['match']['metrics']['f1']:.0%}. "
        f"Category model accuracy {result['category']['metrics']['accuracy']:.0%}. "
        f"{done['scored_suggestions']} suggestions re-scored.",
    )
    return redirect(request.POST.get("next") or "dashboard")


@login_required
@require_GET
def suggest_category(request):
    """The category model's guess while someone fills in the report form."""
    text = f"{request.GET.get('title', '')}. {request.GET.get('description', '')}".strip(". ")
    result = predictor.predict_category(text) if len(text) >= 3 else None
    if result is None:
        return JsonResponse({"category": None})
    category = ItemCategory.objects.filter(name__iexact=result["name"], is_active=True).first()
    return JsonResponse({
        "category": category and {"id": category.pk, "name": category.name},
        "confidence": result["confidence"],
        "alternatives": result["alternatives"],
    })

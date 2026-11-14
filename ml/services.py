"""Predictions recorded when a report is saved (called from items.services)."""

import logging

from items.matching import match_all_lost_items
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion

from . import predictor
from .features import category_text
from .models import CategoryPrediction


logger = logging.getLogger(__name__)


def record_category_prediction(item):
    """
    Predict the category of a saved report and store the result, so the
    dashboard can show how often the model agrees with reporters.
    """
    try:
        result = predictor.predict_category(category_text(item))
    except Exception:  # predictions are advisory: never block a save
        logger.exception("Category prediction failed for %r", item)
        return None
    if result is None:
        return None

    category = ItemCategory.objects.filter(name__iexact=result["name"]).first()
    owner = {"lost_item": item} if isinstance(item, LostItem) else {"found_item": item}
    prediction, _ = CategoryPrediction.objects.update_or_create(
        **owner,
        defaults=dict(
            predicted_category=category,
            predicted_name=result["name"],
            confidence=result["confidence"],
            agrees=category is not None and category.pk == item.category_id,
            model_version=result["model_version"],
        ),
    )
    return prediction


def score_existing_suggestions():
    """
    Give every saved suggestion (pending, accepted or rejected) the current
    match model's probability. Decided suggestions are never re-matched,
    so without this they would keep an old score or none at all.
    """
    suggestions = list(MatchSuggestion.objects.select_related("lost_item", "found_item"))
    probabilities = predictor.match_probabilities(
        [(s.lost_item, s.found_item) for s in suggestions]
    )
    if not probabilities:
        return 0
    for suggestion, probability in zip(suggestions, probabilities):
        suggestion.ml_probability = probability
    MatchSuggestion.objects.bulk_update(suggestions, ["ml_probability"])
    return len(suggestions)


def rescore_all():
    """After training: re-run matching and refresh every stored prediction."""
    live = match_all_lost_items()
    scored = score_existing_suggestions()
    reports = 0
    for model in (LostItem, FoundItem):
        for item in model.objects.all():
            reports += record_category_prediction(item) is not None
    return {"live_suggestions": live, "scored_suggestions": scored, "categorised_reports": reports}

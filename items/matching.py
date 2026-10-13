
import re
from difflib import SequenceMatcher

from django.db import transaction

from .models import LostItem, FoundItem, MatchSuggestion


# Only suggestions scoring at least this value are saved.
MIN_MATCH_SCORE = 35


def normalize_text(value):
    """Convert text to lowercase words for comparison."""
    return re.findall(r"\b[a-z0-9]+\b", (value or "").lower())


def text_similarity(first, second):
    """
    Return a similarity score between 0 and 1.
    Combines matching keywords with overall text similarity.
    """
    first_text = " ".join(normalize_text(first))
    second_text = " ".join(normalize_text(second))

    if not first_text or not second_text:
        return 0.0

    first_words = set(first_text.split())
    second_words = set(second_text.split())

    overlap = len(first_words & second_words) / len(
        first_words | second_words
    )
    sequence = SequenceMatcher(
        None, first_text, second_text
    ).ratio()

    return (overlap * 0.6) + (sequence * 0.4)


def calculate_match(lost_item, found_item):
    """
    Calculate a 0-100 compatibility score and explain the result.

    Weights:
    - Category: 30 points
    - Title similarity: 25 points
    - Description similarity: 15 points
    - Location similarity: 20 points
    - Date proximity: 10 points
    """
    score = 0
    reasons = []

    # 1. Category: 30 points
    if lost_item.category_id == found_item.category_id:
        score += 30
        reasons.append("Both reports have the same category (+30).")

    # 2. Title similarity: up to 25 points
    title_score = text_similarity(
        lost_item.title, found_item.title
    )
    title_points = round(title_score * 25)
    score += title_points

    if title_points:
        reasons.append(
            f"Item titles are similar (+{title_points})."
        )

    # 3. Description similarity: up to 15 points
    description_score = text_similarity(
        lost_item.description, found_item.description
    )
    description_points = round(description_score * 15)
    score += description_points

    if description_points:
        reasons.append(
            f"Descriptions share identifying details "
            f"(+{description_points})."
        )

    # 4. Location similarity: up to 20 points
    location_score = text_similarity(
        lost_item.location, found_item.location
    )
    location_points = round(location_score * 20)
    score += location_points

    if location_points:
        reasons.append(
            f"Reported locations are similar "
            f"(+{location_points})."
        )

    # 5. Date proximity: up to 10 points
    lost_date = lost_item.date_lost
    found_date = found_item.date_found

    if lost_date and found_date:
        days_apart = abs((lost_date - found_date).days)

        if days_apart == 0:
            date_points = 10
        elif days_apart <= 1:
            date_points = 8
        elif days_apart <= 3:
            date_points = 6
        elif days_apart <= 7:
            date_points = 3
        elif days_apart <= 14:
            date_points = 1
        else:
            date_points = 0

        score += date_points

        if date_points:
            reasons.append(
                f"Lost and found dates are {days_apart} "
                f"day(s) apart (+{date_points})."
            )

    score = max(0, min(100, score))

    if not reasons:
        reasons.append(
            "No strong similarities were identified."
        )

    explanation = " ".join(reasons)

    return score, explanation


ACTIVE_LOST_STATUSES = (LostItem.Status.OPEN, LostItem.Status.MATCHED)

# A found item with a pending claim still matches: the claimant may not
# be the real owner, so other people should still be able to see it.
MATCHABLE_FOUND_STATUSES = (
    FoundItem.Status.AVAILABLE,
    FoundItem.Status.CLAIM_PENDING,
)


def _refresh_suggestion(lost_item, found_item, existing):
    """
    Create, update, or remove the suggestion for one lost/found pair.

    Accepted or rejected suggestions are left untouched. Returns the
    pending suggestion, or None when the pair is not a match.
    """
    if existing and existing.status != MatchSuggestion.Status.PENDING:
        return None

    # Do not match a person's lost report against their own found report.
    if lost_item.reporter_id == found_item.reporter_id:
        if existing:
            existing.delete()
        return None

    score, explanation = calculate_match(lost_item, found_item)

    if score < MIN_MATCH_SCORE:
        # Remove a stale pending suggestion if the reports
        # no longer meet the minimum score.
        if existing:
            existing.delete()
        return None

    if existing:
        existing.score = score
        existing.reason = explanation
        existing.save(update_fields=["score", "reason"])
        return existing

    return MatchSuggestion.objects.create(
        lost_item=lost_item,
        found_item=found_item,
        score=score,
        reason=explanation,
        status=MatchSuggestion.Status.PENDING,
    )


def sync_lost_item_status(lost_item):
    """Flag a lost item as matched while it has live suggestions."""
    if lost_item.status not in ACTIVE_LOST_STATUSES:
        return

    has_matches = lost_item.match_suggestions.filter(
        status__in=[
            MatchSuggestion.Status.PENDING,
            MatchSuggestion.Status.ACCEPTED,
        ]
    ).exists()
    new_status = (
        LostItem.Status.MATCHED if has_matches else LostItem.Status.OPEN
    )

    if lost_item.status != new_status:
        lost_item.status = new_status
        lost_item.save(update_fields=["status", "updated_at"])


@transaction.atomic
def match_lost_item(lost_item):
    """
    Generate or refresh suggestions for one lost item.

    Existing accepted or rejected suggestions are preserved.
    Pending suggestions are updated when the reports change.
    """
    if lost_item.status not in ACTIVE_LOST_STATUSES:
        lost_item.match_suggestions.filter(
            status=MatchSuggestion.Status.PENDING
        ).delete()
        return []

    found_items = FoundItem.objects.filter(
        status__in=MATCHABLE_FOUND_STATUSES
    ).exclude(reporter_id=lost_item.reporter_id)

    existing = {
        s.found_item_id: s
        for s in lost_item.match_suggestions.all()
    }

    suggestions = []
    for found_item in found_items:
        suggestion = _refresh_suggestion(
            lost_item, found_item, existing.get(found_item.pk)
        )
        if suggestion:
            suggestions.append(suggestion)

    sync_lost_item_status(lost_item)

    return sorted(
        suggestions,
        key=lambda suggestion: suggestion.score,
        reverse=True,
    )


@transaction.atomic
def match_found_item(found_item):
    """
    Generate or refresh suggestions for one found item against
    every open lost report.
    """
    if found_item.status not in MATCHABLE_FOUND_STATUSES:
        stale = found_item.match_suggestions.filter(
            status=MatchSuggestion.Status.PENDING
        ).select_related("lost_item")
        affected = [s.lost_item for s in stale]
        stale.delete()
        for lost_item in affected:
            sync_lost_item_status(lost_item)
        return []

    lost_items = LostItem.objects.filter(
        status__in=ACTIVE_LOST_STATUSES
    ).exclude(reporter_id=found_item.reporter_id)

    existing = {
        s.lost_item_id: s
        for s in found_item.match_suggestions.all()
    }

    suggestions = []
    for lost_item in lost_items:
        suggestion = _refresh_suggestion(
            lost_item, found_item, existing.get(lost_item.pk)
        )
        if suggestion:
            suggestions.append(suggestion)

        # Only lost items whose suggestions could have changed need
        # their status re-checked.
        if suggestion or lost_item.pk in existing:
            sync_lost_item_status(lost_item)

    return sorted(
        suggestions,
        key=lambda suggestion: suggestion.score,
        reverse=True,
    )


@transaction.atomic
def match_all_lost_items():
    """
    Generate or refresh suggestions for all eligible lost items.
    Returns the number of suggestions currently generated/refreshed.
    """
    lost_items = LostItem.objects.filter(status__in=ACTIVE_LOST_STATUSES)

    total_suggestions = 0

    for lost_item in lost_items:
        total_suggestions += len(match_lost_item(lost_item))

    return total_suggestions

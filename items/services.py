
"""
Report operations shared by the HTML views and the REST API (api/).

Keeping them here means both front doors apply the same rules: matching
runs after every save, deleting a found item re-checks the lost reports it
matched, and only the documented match decisions are accepted.
"""

from django.core.exceptions import ValidationError

from .matching import match_found_item, match_lost_item, sync_lost_item_status
from .models import FoundItem, LostItem, MatchSuggestion


def run_matching(item):
    """
    Refresh match suggestions for a saved lost or found report, and record
    the category model's prediction for it.
    """
    from ml.services import record_category_prediction  # ml depends on items

    matcher = match_lost_item if isinstance(item, LostItem) else match_found_item
    suggestions = matcher(item)
    record_category_prediction(item)
    return suggestions


def delete_report(item):
    """
    Delete a lost or found report.

    Raises django.db.models.ProtectedError when the report is linked to
    other records (for example, a found item that has claims).
    """
    # Deleting a found item cascades to its suggestions, so the lost items
    # it matched may no longer have a match.
    affected = []
    if isinstance(item, FoundItem):
        affected = list(
            LostItem.objects.filter(match_suggestions__found_item=item).distinct()
        )

    item.delete()

    for lost_item in affected:
        sync_lost_item_status(lost_item)


MATCH_DECISIONS = {
    "accept": MatchSuggestion.Status.ACCEPTED,
    "reject": MatchSuggestion.Status.REJECTED,
    "reset": MatchSuggestion.Status.PENDING,
}


def decide_match(suggestion, action):
    """Apply the lost item owner's decision ("accept", "reject", "reset")."""
    new_status = MATCH_DECISIONS.get(action)
    if new_status is None:
        raise ValidationError("Unknown action.")

    suggestion.status = new_status
    suggestion.save(update_fields=["status"])
    sync_lost_item_status(suggestion.lost_item)
    return suggestion

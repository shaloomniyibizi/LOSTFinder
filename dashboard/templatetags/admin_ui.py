
"""Helpers for the AdminLTE-styled Django admin (templates/admin/)."""

from django import template


register = template.Library()

# Sidebar icon per model (Bootstrap Icons); anything else gets a table icon.
MODEL_ICONS = {
    "User": "bi-person",
    "Group": "bi-people",
    "UserProfile": "bi-person-vcard",
    "ItemCategory": "bi-tags",
    "LostItem": "bi-search",
    "FoundItem": "bi-box-seam",
    "MatchSuggestion": "bi-link-45deg",
    "Claim": "bi-clipboard-check",
    "ClaimReviewLog": "bi-journal-text",
    "ItemHandover": "bi-box-arrow-in-right",
    "Notification": "bi-bell",
}


@register.filter
def admin_model_icon(object_name):
    return MODEL_ICONS.get(object_name, "bi-table")


@register.filter
def alert_class(message_tags):
    """Bootstrap alert colour for a Django message's tags."""
    tags = (message_tags or "").split()
    for tag, css in (("error", "danger"), ("warning", "warning"),
                     ("success", "success"), ("debug", "secondary")):
        if tag in tags:
            return css
    return "info"

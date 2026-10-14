
"""Small presentation helpers shared by the match, claim and list pages."""

import re

from django import template

from items.cards import report_card


register = template.Library()

# "Both reports have the same category (+30)." -> ("Both reports...", 30)
_REASON = re.compile(r"\s*(.+?)\s*\(\+(\d+)\)\.?")


@register.filter
def item_image(item):
    """Photo URL for a lost/found item, or its stable placeholder."""
    kind = "lost" if hasattr(item, "date_lost") else "found"
    return report_card(item, kind)["image_url"]


@register.filter
def item_placeholder(item):
    kind = "lost" if hasattr(item, "date_lost") else "found"
    return report_card(item, kind)["placeholder_url"]


@register.filter
def match_reasons(reason):
    """Split the matching engine's explanation into (text, points) parts."""
    parts = [
        {"text": text.rstrip("."), "points": int(points)}
        for text, points in _REASON.findall(reason or "")
    ]
    if parts or not reason:
        return parts
    # Unrecognised wording: show it as a single reason.
    return [{"text": reason, "points": None}]


CLAIM_STEPS = [
    ("submitted", "Submitted", "bi-send"),
    ("under_review", "In review", "bi-search"),
    ("approved", "Approved", "bi-check2-circle"),
    ("completed", "Collected", "bi-bag-check"),
]


@register.filter
def claim_steps(claim):
    """
    Progress steps for a claim: each is done, current or upcoming.

    Rejected and cancelled claims stop after the last step they reached,
    which is then marked as the point where the claim ended.
    """
    order = [key for key, _, _ in CLAIM_STEPS]
    ended = claim.status in ("rejected", "cancelled")

    if ended:
        # How far it got: under review if a reviewer touched it, else submitted.
        reached = 1 if claim.review_logs.filter(decision="under_review").exists() else 0
    else:
        reached = order.index(claim.status)

    steps = []
    for index, (key, label, icon) in enumerate(CLAIM_STEPS):
        if index < reached or (index == reached and claim.status == "completed"):
            state = "done"
        elif index == reached:
            state = "ended" if ended else "current"
        else:
            state = "upcoming"
        steps.append({"label": label, "icon": icon, "state": state})
    return steps


@register.simple_tag
def match_strength(score):
    """A word for a 0-100 match score."""
    if score >= 70:
        return "Strong match"
    if score >= 50:
        return "Good match"
    return "Possible match"

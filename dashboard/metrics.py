
"""
Dashboard numbers, chart series, and tables.

`build_dashboard(user)` is the single source for both the rendered page and
the JSON endpoint the page polls, so the two can never disagree.
"""

from datetime import timedelta
from itertools import chain

from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from accounts.decorators import is_reviewer
from claims.models import Claim, ItemHandover
from claims.services import ACTIVE_STATUSES
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion


ACTIVITY_DAYS = 14
TABLE_ROWS = 6
CUSTODY_STATUSES = (FoundItem.Status.AVAILABLE, FoundItem.Status.CLAIM_PENDING)
OPEN_LOST_STATUSES = (LostItem.Status.OPEN, LostItem.Status.MATCHED)


def _card(key, label, value, icon, color, url, hint=""):
    return {
        "key": key, "label": label, "value": value,
        "icon": icon, "color": color, "url": url, "hint": hint,
    }


# ---------- charts ----------

def _daily_counts(queryset, start):
    rows = (
        queryset.filter(created_at__date__gte=start)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(total=Count("id"))
    )
    return {row["day"]: row["total"] for row in rows}


def activity_chart():
    """Lost vs found reports per day for the last ACTIVITY_DAYS days."""
    today = timezone.localdate()
    start = today - timedelta(days=ACTIVITY_DAYS - 1)
    days = [start + timedelta(days=n) for n in range(ACTIVITY_DAYS)]

    lost = _daily_counts(LostItem.objects, start)
    found = _daily_counts(FoundItem.objects, start)

    return {
        "labels": [day.strftime("%b %d") for day in days],
        "lost": [lost.get(day, 0) for day in days],
        "found": [found.get(day, 0) for day in days],
    }


def category_chart(limit=6):
    categories = (
        ItemCategory.objects.annotate(
            total=Count("lost_items", distinct=True)
            + Count("found_items", distinct=True)
        )
        .filter(total__gt=0)
        .order_by("-total", "name")[:limit]
    )
    return {
        "labels": [c.name for c in categories],
        "values": [c.total for c in categories],
    }


def _status_chart(queryset, status_enum, title):
    counts = dict(
        queryset.values_list("status").annotate(total=Count("id"))
    )
    return {
        "title": title,
        "labels": [label for _, label in status_enum.choices],
        "values": [counts.get(value, 0) for value, _ in status_enum.choices],
    }


# ---------- tables ----------

def _report_rows(lost_qs, found_qs, limit=TABLE_ROWS):
    lost_qs = lost_qs.select_related("category", "reporter")[:limit]
    found_qs = found_qs.select_related("category", "reporter")[:limit]

    rows = sorted(
        chain(
            ({"kind": "Lost", "item": i,
              "url": reverse("lost_item_detail", args=[i.pk])} for i in lost_qs),
            ({"kind": "Found", "item": i,
              "url": reverse("found_item_detail", args=[i.pk])} for i in found_qs),
        ),
        key=lambda row: row["item"].created_at,
        reverse=True,
    )
    return rows[:limit]


def _claims(queryset):
    return queryset.select_related("found_item", "claimant")


# ---------- role dashboards ----------

def reviewer_dashboard(user):
    now = timezone.now()
    month_ago = now - timedelta(days=30)

    active_claims = Claim.objects.filter(status__in=ACTIVE_STATUSES)
    approved = Claim.objects.filter(status=Claim.Status.APPROVED)
    in_custody = FoundItem.objects.filter(status__in=CUSTODY_STATUSES)
    returned_30d = ItemHandover.objects.filter(handed_over_at__gte=month_ago)

    queue_url = reverse("review_queue")
    cards = [
        _card("claims_to_review", "Claims to review", active_claims.count(),
              "bi-clipboard-check", "warning", queue_url,
              "Submitted or under review"),
        _card("awaiting_handover", "Awaiting handover", approved.count(),
              "bi-box-arrow-in-right", "primary", f"{queue_url}?status=approved",
              "Approved, not yet collected"),
        _card("in_custody", "Items in custody", in_custody.count(),
              "bi-shield-lock", "info", reverse("found_item_list"),
              "Found items held by security"),
        _card("returned_30d", "Returned (30 days)", returned_30d.count(),
              "bi-arrow-repeat", "success", f"{queue_url}?status=closed",
              "Completed handovers"),
    ]

    lost_total = LostItem.objects.count()
    lost_returned = LostItem.objects.filter(status=LostItem.Status.RETURNED).count()
    stats = [
        _card("open_lost", "Open lost reports",
              LostItem.objects.filter(status__in=OPEN_LOST_STATUSES).count(),
              "bi-search", "danger", reverse("lost_item_list")),
        _card("pending_matches", "Pending match suggestions",
              MatchSuggestion.objects.filter(
                  status=MatchSuggestion.Status.PENDING).count(),
              "bi-link-45deg", "secondary", reverse("match_list")),
        _card("return_rate", "Lost-report return rate",
              f"{round(lost_returned * 100 / lost_total)}%" if lost_total else "–",
              "bi-graph-up-arrow", "success", reverse("lost_item_list")),
    ]
    if user.is_staff:
        stats.append(_card(
            "users", "Registered users",
            get_user_model().objects.filter(is_active=True).count(),
            "bi-people", "primary", reverse("admin:index"),
        ))

    return {
        "cards": cards,
        "stats": stats,
        "charts": {
            "activity": activity_chart(),
            "categories": category_chart(),
            "status": _status_chart(Claim.objects, Claim.Status, "Claims by status"),
        },
        "tables": {
            # Oldest first: the queue is worked in submission order.
            "claim_queue": _claims(active_claims.order_by("submitted_at"))[:8],
            "awaiting_handover": _claims(approved.order_by("updated_at"))[:TABLE_ROWS],
            "recent_reports": _report_rows(LostItem.objects, FoundItem.objects),
        },
    }


def member_dashboard(user):
    my_lost = LostItem.objects.filter(reporter=user)
    my_found = FoundItem.objects.filter(reporter=user)
    my_claims = Claim.objects.filter(claimant=user)
    pending_matches = MatchSuggestion.objects.filter(
        lost_item__reporter=user, status=MatchSuggestion.Status.PENDING,
    )

    cards = [
        _card("my_open_lost", "My open lost reports",
              my_lost.filter(status__in=OPEN_LOST_STATUSES).count(),
              "bi-search", "danger", reverse("lost_item_list"),
              "Still being searched for"),
        _card("pending_matches", "Matches to review", pending_matches.count(),
              "bi-link-45deg", "warning", reverse("match_list"),
              "Possible matches for your items"),
        _card("my_active_claims", "My active claims",
              my_claims.filter(
                  status__in=(*ACTIVE_STATUSES, Claim.Status.APPROVED)
              ).count(),
              "bi-clipboard-check", "primary", reverse("claim_list"),
              "Submitted, in review or approved"),
        _card("my_found_custody", "Items I turned in",
              my_found.filter(status__in=CUSTODY_STATUSES).count(),
              "bi-box-seam", "success", reverse("found_item_list"),
              "Waiting for their owners"),
    ]

    stats = [
        _card("my_returned", "My items returned",
              my_lost.filter(status=LostItem.Status.RETURNED).count(),
              "bi-emoji-smile", "success", reverse("lost_item_list")),
        _card("campus_custody", "Found items on campus",
              FoundItem.objects.filter(status__in=CUSTODY_STATUSES).count(),
              "bi-shield-lock", "info", reverse("found_item_list")),
        _card("unread", "Unread notifications",
              user.notifications.filter(is_read=False).count(),
              "bi-bell", "secondary", reverse("notification_list")),
    ]

    return {
        "cards": cards,
        "stats": stats,
        "charts": {
            "activity": activity_chart(),
            "categories": category_chart(),
            "status": _status_chart(my_lost, LostItem.Status, "My lost reports by status"),
        },
        "tables": {
            "my_reports": _report_rows(my_lost, my_found),
            "my_claims": _claims(my_claims)[:TABLE_ROWS],
            "pending_matches": pending_matches.select_related(
                "lost_item", "found_item")[:TABLE_ROWS],
        },
    }


def build_dashboard(user):
    reviewer = is_reviewer(user)
    data = reviewer_dashboard(user) if reviewer else member_dashboard(user)
    data["role"] = "reviewer" if reviewer else "member"
    return data


def serialize_metrics(data):
    """The JSON-safe part of a dashboard: card values and chart series."""
    return {
        "role": data["role"],
        "values": {
            card["key"]: card["value"]
            for card in chain(data["cards"], data["stats"])
        },
        "charts": data["charts"],
        "generated_at": timezone.localtime().strftime("%H:%M:%S"),
    }

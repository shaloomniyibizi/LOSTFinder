from itertools import chain

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, F
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static

from claims.models import Claim, ItemHandover
from accounts.decorators import profile_completed_required
from items.models import FoundItem, ItemCategory, LostItem

from .metrics import build_dashboard, serialize_metrics


FALLBACK_IMAGES = [f"image/item_{n}.jpg" for n in range(1, 7)]

FEED_FILTERS = [
    ("all", "All Reports"),
    ("lost", "Recently Lost"),
    ("found", "Turned In / Found"),
    ("available", "Safe in Custody"),
]

FEED_SIZE = 6


def _feed_entry(item, kind, index):
    """Flatten a lost or found report into what the home page cards need."""
    is_lost = kind == "lost"

    if item.image:
        image_url = item.image.url
    else:
        image_url = static(FALLBACK_IMAGES[index % len(FALLBACK_IMAGES)])

    return {
        "item": item,
        "kind": kind,
        "image_url": image_url,
        "report_date": item.date_lost if is_lost else item.date_found,
        "detail_url_name": (
            "lost_item_detail" if is_lost else "found_item_detail"
        ),
    }


def _recent_reports(feed):
    lost = LostItem.objects.select_related("category")
    found = FoundItem.objects.select_related("category")

    if feed == "lost":
        found = found.none()
    elif feed == "found":
        lost = lost.none()
    elif feed == "available":
        lost = lost.none()
        found = found.filter(status=FoundItem.Status.AVAILABLE)

    reports = sorted(
        chain(
            ((item, "lost") for item in lost[:FEED_SIZE]),
            ((item, "found") for item in found[:FEED_SIZE]),
        ),
        key=lambda pair: pair[0].created_at,
        reverse=True,
    )[:FEED_SIZE]

    return [
        _feed_entry(item, kind, index)
        for index, (item, kind) in enumerate(reports)
    ]


def _campus_stats():
    lost_total = LostItem.objects.count()
    found_total = FoundItem.objects.count()

    lost_returned = LostItem.objects.filter(
        status=LostItem.Status.RETURNED
    ).count()
    found_recovered = FoundItem.objects.filter(
        status__in=[FoundItem.Status.CLAIMED, FoundItem.Status.RETURNED]
    ).count()

    in_custody = FoundItem.objects.filter(
        status=FoundItem.Status.AVAILABLE
    ).count()

    avg_handover = ItemHandover.objects.aggregate(
        avg=Avg(F("handed_over_at") - F("claim__submitted_at"))
    )["avg"]
    avg_claim_hours = (
        round(avg_handover.total_seconds() / 3600, 1)
        if avg_handover else None
    )

    decided_claims = Claim.objects.filter(
        status__in=[
            Claim.Status.APPROVED,
            Claim.Status.REJECTED,
            Claim.Status.COMPLETED,
        ]
    ).count()

    return_rate = (
        round(lost_returned * 100 / lost_total) if lost_total else None
    )

    return {
        "total_reports": lost_total + found_total,
        "recovered": lost_returned + found_recovered,
        "in_custody": in_custody,
        "avg_claim_hours": avg_claim_hours,
        "decided_claims": decided_claims,
        "return_rate": return_rate,
    }


def _campus_zones(limit=3):
    """Busiest report locations across lost and found items."""
    totals = {}

    for model in (LostItem, FoundItem):
        rows = model.objects.values("location").annotate(total=Count("id"))
        for row in rows:
            key = row["location"].strip()
            totals[key] = totals.get(key, 0) + row["total"]

    busiest = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {"name": name, "count": count}
        for name, count in busiest[:limit]
    ]


def home(request):
    # The landing page is for visitors; signed-in users work from the dashboard.
    if request.user.is_authenticated:
        return redirect("dashboard")

    feed = request.GET.get("feed", "all")
    if feed not in dict(FEED_FILTERS):
        feed = "all"

    reports = _recent_reports(feed)

    context = {
        "stats": _campus_stats(),
        "reports": reports,
        "feed": feed,
        "feed_filters": FEED_FILTERS,
        "categories": ItemCategory.objects.filter(is_active=True)[:8],
        "zones": _campus_zones(),
        "active_found": FoundItem.objects.filter(
            status=FoundItem.Status.AVAILABLE
        ).count(),
    }

    return render(request, "home.html", context)


@login_required
@profile_completed_required
def dashboard(request):
    data = build_dashboard(request.user)
    return render(request, "dashboard/index.html", {
        "dash": data,
        "metrics": serialize_metrics(data),
    })


@login_required
@profile_completed_required
def dashboard_metrics(request):
    """Polled by the dashboard so its numbers follow the database."""
    return JsonResponse(serialize_metrics(build_dashboard(request.user)))

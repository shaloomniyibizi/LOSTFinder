from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import (
    is_reviewer,
    profile_completed_required,
    reviewer_required,
)
from items.models import FoundItem

from . import services
from .forms import ClaimForm, HandoverForm, ReviewForm
from .models import Claim


def _error_text(error):
    return " ".join(error.messages)


def _claims_queryset():
    return Claim.objects.select_related(
        "found_item__category", "found_item__reporter", "claimant",
    )


@login_required
@profile_completed_required
def claim_create(request, found_pk):
    found_item = get_object_or_404(FoundItem, pk=found_pk)

    if not services.can_claim(request.user, found_item):
        messages.error(request, "This item cannot be claimed.")
        return redirect("found_item_detail", pk=found_item.pk)

    if request.method == "POST":
        form = ClaimForm(request.POST)

        if form.is_valid():
            try:
                claim = services.submit_claim(
                    found_item,
                    request.user,
                    form.cleaned_data["evidence_description"],
                )
            except ValidationError as error:
                messages.error(request, _error_text(error))
                return redirect("found_item_detail", pk=found_item.pk)

            messages.success(
                request,
                "Your claim was submitted. Campus security will review it "
                "and notify you.",
            )
            return redirect("claim_detail", pk=claim.pk)
    else:
        form = ClaimForm()

    return render(request, "claims/claim_form.html", {
        "form": form,
        "found_item": found_item,
    })


@login_required
@profile_completed_required
def claim_list(request):
    claims = _claims_queryset().filter(claimant=request.user)
    statuses = [claim.status for claim in claims]

    return render(request, "claims/claim_list.html", {
        "claims": claims,
        "claims_on_my_items": _claims_queryset().filter(
            found_item__reporter=request.user
        ),
        "ready_to_collect": [
            claim for claim in claims if claim.status == Claim.Status.APPROVED
        ],
        "summary": [
            ("In progress", "bi-hourglass-split", "warning",
             sum(s in services.ACTIVE_STATUSES for s in statuses)),
            ("Ready to collect", "bi-bag-check", "success",
             statuses.count(Claim.Status.APPROVED)),
            ("Collected", "bi-box-arrow-in-right", "primary",
             statuses.count(Claim.Status.COMPLETED)),
            ("Closed", "bi-x-circle", "secondary",
             statuses.count(Claim.Status.REJECTED) + statuses.count(Claim.Status.CANCELLED)),
        ],
    })


REVIEW_FILTERS = [
    ("active", "Needs review"),
    ("approved", "Awaiting handover"),
    ("closed", "Closed"),
    ("all", "All"),
]


@login_required
@profile_completed_required
@reviewer_required
def review_queue(request):
    status = request.GET.get("status", "active")
    if status not in dict(REVIEW_FILTERS):
        status = "active"

    query = request.GET.get("q", "").strip()
    claims = _claims_queryset()

    if status == "active":
        claims = claims.filter(status__in=services.ACTIVE_STATUSES)
    elif status == "approved":
        claims = claims.filter(status=Claim.Status.APPROVED)
    elif status == "closed":
        claims = claims.filter(status__in=[
            Claim.Status.REJECTED,
            Claim.Status.COMPLETED,
            Claim.Status.CANCELLED,
        ])

    if query:
        claims = claims.filter(
            Q(found_item__title__icontains=query)
            | Q(claimant__email__icontains=query)
        )

    page_obj = Paginator(claims, 20).get_page(request.GET.get("page"))

    return render(request, "claims/review_queue.html", {
        "page_obj": page_obj,
        "claims": page_obj.object_list,
        "selected_status": status,
        "status_filters": REVIEW_FILTERS,
        "query": query,
    })


@login_required
@profile_completed_required
def claim_detail(request, pk):
    claim = get_object_or_404(_claims_queryset(), pk=pk)

    user = request.user
    reviewer = is_reviewer(user)
    is_claimant = claim.claimant_id == user.id
    is_finder = claim.found_item.reporter_id == user.id

    if not (reviewer or is_claimant or is_finder):
        raise Http404

    can_review = (
        reviewer
        and not is_claimant
        and claim.status in services.ACTIVE_STATUSES
    )
    can_handover = (
        reviewer
        and not is_claimant
        and claim.status == Claim.Status.APPROVED
    )

    return render(request, "claims/claim_detail.html", {
        "claim": claim,
        # The finder only sees progress, never the ownership evidence.
        "show_evidence": reviewer or is_claimant,
        "is_claimant": is_claimant,
        "can_cancel": (
            is_claimant and claim.status in services.ACTIVE_STATUSES
        ),
        "can_review": can_review,
        "can_handover": can_handover,
        "review_form": ReviewForm() if can_review else None,
        "handover_form": HandoverForm() if can_handover else None,
        "logs": claim.review_logs.select_related("reviewer"),
        "handover": getattr(claim, "handover", None),
    })


@require_POST
@login_required
@profile_completed_required
def claim_cancel(request, pk):
    claim = get_object_or_404(Claim, pk=pk, claimant=request.user)

    try:
        services.cancel_claim(claim, request.user)
    except ValidationError as error:
        messages.error(request, _error_text(error))
    else:
        messages.success(request, "Your claim was cancelled.")

    return redirect("claim_detail", pk=claim.pk)


@require_POST
@login_required
@profile_completed_required
@reviewer_required
def claim_review(request, pk):
    claim = get_object_or_404(_claims_queryset(), pk=pk)
    form = ReviewForm(request.POST)

    if not form.is_valid():
        messages.error(request, "Please choose a valid review decision.")
        return redirect("claim_detail", pk=claim.pk)

    try:
        services.review_claim(
            claim,
            request.user,
            form.cleaned_data["decision"],
            form.cleaned_data["comments"],
        )
    except ValidationError as error:
        messages.error(request, _error_text(error))
    else:
        messages.success(
            request, f"Claim marked as {claim.get_status_display().lower()}."
        )

    return redirect("claim_detail", pk=claim.pk)


@login_required
@profile_completed_required
@reviewer_required
def claim_handover(request, pk):
    claim = get_object_or_404(_claims_queryset(), pk=pk)

    if claim.claimant_id == request.user.id:
        messages.error(request, "You cannot hand an item over to yourself.")
        return redirect("claim_detail", pk=claim.pk)

    if request.method == "POST":
        form = HandoverForm(request.POST)

        if form.is_valid():
            try:
                services.record_handover(
                    claim,
                    request.user,
                    form.cleaned_data["handover_location"],
                    form.cleaned_data["handed_over_at"],
                    form.cleaned_data["notes"],
                )
            except ValidationError as error:
                messages.error(request, _error_text(error))
            else:
                messages.success(
                    request, "Handover recorded. The item is returned."
                )
            return redirect("claim_detail", pk=claim.pk)
    else:
        form = HandoverForm()

    return render(request, "claims/handover_form.html", {
        "form": form,
        "claim": claim,
    })


# Icon and colour per notification type (matched on the title the
# claim services use), so the inbox can be scanned at a glance.
NOTIFICATION_STYLES = [
    ("approved", "bi-check2-circle", "success"),
    ("rejected", "bi-x-circle", "danger"),
    ("under review", "bi-hourglass-split", "info"),
    ("returned", "bi-bag-check", "primary"),
    ("claimed", "bi-hand-index", "warning"),
    ("new claim", "bi-clipboard-plus", "warning"),
]


def _notification_style(notification):
    title = notification.title.lower()
    for keyword, icon, color in NOTIFICATION_STYLES:
        if keyword in title:
            return icon, color
    return "bi-bell", "secondary"


def _day_label(moment):
    day = timezone.localtime(moment).date()
    today = timezone.localdate()
    if day == today:
        return "Today"
    if day == today - timezone.timedelta(days=1):
        return "Yesterday"
    return day.strftime("%A, %b %d").replace(" 0", " ")


@login_required
def notification_list(request):
    show = request.GET.get("show", "all")
    notifications = request.user.notifications.all()
    unread_total = notifications.filter(is_read=False).count()
    if show == "unread":
        notifications = notifications.filter(is_read=False)
    else:
        show = "all"

    page_obj = Paginator(notifications, 20).get_page(request.GET.get("page"))

    groups = []
    for notification in page_obj.object_list:
        notification.icon, notification.color = _notification_style(notification)
        label = _day_label(notification.created_at)
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(notification)

    return render(request, "claims/notification_list.html", {
        "page_obj": page_obj,
        "notifications": page_obj.object_list,
        "groups": groups,
        "show": show,
        "total_count": request.user.notifications.count(),
        "unread_total": unread_total,
    })


@require_POST
@login_required
def notification_mark_read(request, pk):
    request.user.notifications.filter(pk=pk, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("notification_list")


@require_POST
@login_required
def notifications_mark_read(request):
    request.user.notifications.filter(is_read=False).update(
        is_read=True, read_at=timezone.now()
    )
    return redirect("notification_list")

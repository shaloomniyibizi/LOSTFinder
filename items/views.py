
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models.deletion import ProtectedError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.decorators import profile_completed_required
from claims.models import Claim
from claims.services import can_claim
from .forms import LostItemForm, FoundItemForm
from .matching import (
    match_found_item,
    match_lost_item,
    sync_lost_item_status,
)
from .models import ItemCategory, LostItem, FoundItem, MatchSuggestion


def item_list(request, model, item_type, date_field, create_url_name):
    query = request.GET.get("q", "").strip()
    category_id = request.GET.get("category", "").strip()
    status = request.GET.get("status", "").strip()

    queryset = model.objects.select_related(
        "category", "reporter"
    ).all()

    if query:
        queryset = queryset.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(location__icontains=query)
        )

    if category_id.isdigit():
        queryset = queryset.filter(category_id=int(category_id))

    valid_statuses = {value for value, _ in model.Status.choices}
    if status in valid_statuses:
        queryset = queryset.filter(status=status)
    else:
        status = ""

    paginator = Paginator(queryset, 10)
    page_obj = paginator.get_page(request.GET.get("page"))

    context = {
        "item_type": item_type,
        "items": page_obj.object_list,
        "page_obj": page_obj,
        "query": query,
        "selected_category": category_id,
        "selected_status": status,
        "categories": ItemCategory.objects.filter(is_active=True),
        "status_choices": model.Status.choices,
        "date_field": date_field,
        "create_url_name": create_url_name,
    }

    return render(request, "items/item_list.html", context)


@login_required
@profile_completed_required
def lost_item_list(request):
    return item_list(
        request, LostItem, "Lost", "date_lost",
        "lost_item_create",
    )


@login_required
@profile_completed_required
def found_item_list(request):
    return item_list(
        request, FoundItem, "Found", "date_found",
        "found_item_create",
    )


def visible_suggestions(user, item):
    """Match suggestions for an item, shown only to the item's reporter."""
    if item.reporter_id != user.id:
        return MatchSuggestion.objects.none()

    return item.match_suggestions.exclude(
        status=MatchSuggestion.Status.REJECTED
    ).select_related(
        "lost_item__category", "found_item__category"
    )


@login_required
@profile_completed_required
def lost_item_detail(request, pk):
    item = get_object_or_404(
        LostItem.objects.select_related("category", "reporter"),
        pk=pk,
    )

    return render(request, "items/item_detail.html", {
        "item": item,
        "item_type": "Lost",
        "report_date": item.date_lost,
        "can_manage": item.reporter_id == request.user.id,
        "list_url_name": "lost_item_list",
        "update_url_name": "lost_item_update",
        "delete_url_name": "lost_item_delete",
        "pk": item.pk,
        "suggestions": visible_suggestions(request.user, item),
    })


@login_required
@profile_completed_required
def found_item_detail(request, pk):
    item = get_object_or_404(
        FoundItem.objects.select_related("category", "reporter"),
        pk=pk,
    )
    my_claim = item.claims.filter(claimant=request.user).first()

    return render(request, "items/item_detail.html", {
        "item": item,
        "item_type": "Found",
        "report_date": item.date_found,
        "can_manage": item.reporter_id == request.user.id,
        "list_url_name": "found_item_list",
        "update_url_name": "found_item_update",
        "delete_url_name": "found_item_delete",
        "pk": item.pk,
        "suggestions": visible_suggestions(request.user, item),
        "my_claim": my_claim,
        "can_claim": (
            can_claim(request.user, item)
            and (my_claim is None or my_claim.status == Claim.Status.CANCELLED)
        ),
        "claim_count": (
            item.claims.count() if item.reporter_id == request.user.id else 0
        ),
    })


def save_item_form(request, model, form_class, item_type, pk=None):
    if pk is None:
        item = None
    else:
        # Only the report owner may edit it.
        item = get_object_or_404(
            model,
            pk=pk,
            reporter=request.user,
        )

    if request.method == "POST":
        form = form_class(
            request.POST,
            request.FILES,
            instance=item,
        )

        if form.is_valid():
            saved_item = form.save(commit=False)

            if item is None:
                saved_item.reporter = request.user

            saved_item.save()

            matcher = (
                match_lost_item if model is LostItem else match_found_item
            )
            suggestions = matcher(saved_item)

            messages.success(
                request,
                f"{item_type} item report saved successfully.",
            )
            if suggestions:
                messages.info(
                    request,
                    f"We found {len(suggestions)} possible "
                    f"match{'es' if len(suggestions) != 1 else ''} "
                    "for this report.",
                )

            if model is LostItem:
                return redirect("lost_item_detail", pk=saved_item.pk)

            return redirect("found_item_detail", pk=saved_item.pk)
    else:
        form = form_class(instance=item)

    return render(request, "items/item_form.html", {
        "form": form,
        "item_type": item_type,
        "is_edit": item is not None,
        "list_url_name": (
            "lost_item_list" if model is LostItem
            else "found_item_list"
        ),
    })


@login_required
@profile_completed_required
def lost_item_create(request):
    return save_item_form(
        request, LostItem, LostItemForm, "Lost"
    )


@login_required
@profile_completed_required
def found_item_create(request):
    return save_item_form(
        request, FoundItem, FoundItemForm, "Found"
    )


@login_required
@profile_completed_required
def lost_item_update(request, pk):
    return save_item_form(
        request, LostItem, LostItemForm, "Lost", pk
    )


@login_required
@profile_completed_required
def found_item_update(request, pk):
    return save_item_form(
        request, FoundItem, FoundItemForm, "Found", pk
    )


def delete_item(request, model, item_type, pk, list_url_name):
    item = get_object_or_404(
        model,
        pk=pk,
        reporter=request.user,
    )

    if request.method == "POST":
        # Deleting a found item cascades to its suggestions, so the
        # affected lost items may no longer have a match.
        affected_lost_items = []
        if model is FoundItem:
            affected_lost_items = list(
                LostItem.objects.filter(match_suggestions__found_item=item)
            )

        try:
            item.delete()
        except ProtectedError:
            # For example, a found item may be protected by existing claims.
            messages.error(
                request,
                "This report cannot be deleted because it is linked "
                "to other records. Please contact an administrator.",
            )
        else:
            for lost_item in affected_lost_items:
                sync_lost_item_status(lost_item)

            messages.success(
                request,
                f"{item_type} item report deleted successfully.",
            )
            return redirect(list_url_name)

    return render(request, "items/item_confirm_delete.html", {
        "item": item,
        "item_type": item_type,
        "list_url_name": list_url_name,
    })


@login_required
@profile_completed_required
def lost_item_delete(request, pk):
    return delete_item(
        request, LostItem, "Lost", pk, "lost_item_list"
    )


@login_required
@profile_completed_required
def found_item_delete(request, pk):
    return delete_item(
        request, FoundItem, "Found", pk, "found_item_list"
    )


MATCH_FILTERS = [
    ("active", "Pending & accepted"),
    ("pending", "Pending review"),
    ("accepted", "Accepted"),
    ("rejected", "Rejected"),
    ("all", "All"),
]


@login_required
@profile_completed_required
def match_list(request):
    status = request.GET.get("status", "active")
    if status not in dict(MATCH_FILTERS):
        status = "active"

    suggestions = MatchSuggestion.objects.select_related(
        "lost_item__category", "found_item__category",
    )

    if status == "active":
        suggestions = suggestions.exclude(
            status=MatchSuggestion.Status.REJECTED
        )
    elif status != "all":
        suggestions = suggestions.filter(status=status)

    return render(request, "items/match_list.html", {
        "for_my_lost": suggestions.filter(
            lost_item__reporter=request.user
        ),
        "for_my_found": suggestions.filter(
            found_item__reporter=request.user
        ),
        "selected_status": status,
        "status_filters": MATCH_FILTERS,
    })


@require_POST
@login_required
@profile_completed_required
def match_update(request, pk):
    """Let the owner of the lost item accept or reject a suggestion."""
    suggestion = get_object_or_404(
        MatchSuggestion.objects.select_related("lost_item"),
        pk=pk,
        lost_item__reporter=request.user,
    )

    decisions = {
        "accept": MatchSuggestion.Status.ACCEPTED,
        "reject": MatchSuggestion.Status.REJECTED,
        "reset": MatchSuggestion.Status.PENDING,
    }
    new_status = decisions.get(request.POST.get("action"))

    if new_status is None:
        messages.error(request, "Unknown action.")
    else:
        suggestion.status = new_status
        suggestion.save(update_fields=["status"])
        sync_lost_item_status(suggestion.lost_item)

        if new_status == MatchSuggestion.Status.ACCEPTED:
            messages.success(
                request,
                "Match accepted. Visit the Campus Security Office with "
                "your ID to verify ownership and collect the item.",
            )
        elif new_status == MatchSuggestion.Status.REJECTED:
            messages.success(request, "Match rejected.")
        else:
            messages.success(request, "Match moved back to pending.")

    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        return redirect(next_url)
    return redirect("match_list")

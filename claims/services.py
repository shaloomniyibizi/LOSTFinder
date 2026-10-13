
"""
Claim workflow: submit -> (under review) -> approve/reject -> handover.

Every state change is written to ClaimReviewLog, keeps the found item's
status in step with its claims, and notifies the people involved.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse

from accounts.models import UserProfile
from items.matching import match_found_item
from items.models import FoundItem, LostItem, MatchSuggestion

from .models import Claim, ClaimReviewLog, ItemHandover, Notification


ACTIVE_STATUSES = (Claim.Status.SUBMITTED, Claim.Status.UNDER_REVIEW)
CLAIMABLE_ITEM_STATUSES = (
    FoundItem.Status.AVAILABLE,
    FoundItem.Status.CLAIM_PENDING,
)


def notify(recipients, title, message):
    Notification.objects.bulk_create(
        Notification(recipient=user, title=title, message=message)
        for user in recipients
    )


def reviewers():
    User = get_user_model()
    return User.objects.filter(
        Q(is_staff=True)
        | Q(profile__user_type=UserProfile.UserType.SECURITY),
        is_active=True,
    ).distinct()


def _log(claim, decision, reviewer=None, comments=""):
    ClaimReviewLog.objects.create(
        claim=claim,
        reviewer=reviewer,
        decision=decision,
        comments=comments,
    )


def _sync_found_item_status(found_item):
    """Derive the found item's status from its claims."""
    claims = found_item.claims.all()

    if claims.filter(status=Claim.Status.COMPLETED).exists():
        new_status = FoundItem.Status.RETURNED
    elif claims.filter(status=Claim.Status.APPROVED).exists():
        new_status = FoundItem.Status.CLAIMED
    elif claims.filter(status__in=ACTIVE_STATUSES).exists():
        new_status = FoundItem.Status.CLAIM_PENDING
    elif found_item.status == FoundItem.Status.CLOSED:
        return
    else:
        new_status = FoundItem.Status.AVAILABLE

    if found_item.status != new_status:
        found_item.status = new_status
        found_item.save(update_fields=["status", "updated_at"])
        # Drops pending suggestions once the item is claimed or returned,
        # and regenerates them if it becomes claimable again.
        match_found_item(found_item)


def can_claim(user, found_item):
    return (
        found_item.reporter_id != user.id
        and found_item.status in CLAIMABLE_ITEM_STATUSES
    )


@transaction.atomic
def submit_claim(found_item, claimant, evidence_description):
    found_item = FoundItem.objects.select_for_update().get(pk=found_item.pk)

    if not can_claim(claimant, found_item):
        raise ValidationError("This item cannot be claimed.")

    claim = Claim.objects.filter(
        found_item=found_item, claimant=claimant
    ).first()

    if claim and claim.status != Claim.Status.CANCELLED:
        raise ValidationError("You have already claimed this item.")

    if claim:
        # Re-open a previously cancelled claim (one claim per person per item).
        claim.evidence_description = evidence_description
        claim.status = Claim.Status.SUBMITTED
        claim.save(update_fields=[
            "evidence_description", "status", "updated_at",
        ])
    else:
        claim = Claim(
            found_item=found_item,
            claimant=claimant,
            evidence_description=evidence_description,
        )
        claim.full_clean()
        claim.save()

    _log(claim, ClaimReviewLog.Decision.SUBMITTED, reviewer=claimant)
    _sync_found_item_status(found_item)

    link = reverse("claim_detail", args=[claim.pk])
    notify(
        reviewers(),
        "New claim to review",
        f"A claim was submitted for “{found_item.title}”. Review it at {link}.",
    )
    notify(
        [found_item.reporter],
        "Someone claimed an item you found",
        f"A claim for “{found_item.title}” is awaiting security review.",
    )

    return claim


@transaction.atomic
def cancel_claim(claim, user):
    if claim.claimant_id != user.id:
        raise ValidationError("Only the claimant can cancel this claim.")

    if claim.status not in ACTIVE_STATUSES:
        raise ValidationError("This claim can no longer be cancelled.")

    claim.status = Claim.Status.CANCELLED
    claim.save(update_fields=["status", "updated_at"])
    _log(claim, ClaimReviewLog.Decision.CANCELLED, reviewer=user)
    _sync_found_item_status(claim.found_item)

    return claim


REVIEW_TRANSITIONS = {
    Claim.Status.UNDER_REVIEW: (Claim.Status.SUBMITTED,),
    Claim.Status.APPROVED: ACTIVE_STATUSES,
    Claim.Status.REJECTED: ACTIVE_STATUSES,
}


@transaction.atomic
def review_claim(claim, reviewer, decision, comments=""):
    if claim.claimant_id == reviewer.id:
        raise ValidationError("You cannot review your own claim.")

    allowed_from = REVIEW_TRANSITIONS.get(decision)
    if allowed_from is None:
        raise ValidationError("Unknown review decision.")

    if claim.status not in allowed_from:
        raise ValidationError(
            f"A {claim.get_status_display().lower()} claim cannot be "
            f"moved to {Claim.Status(decision).label.lower()}."
        )

    claim.status = decision
    claim.save(update_fields=["status", "updated_at"])
    _log(claim, decision, reviewer=reviewer, comments=comments)

    title = claim.found_item.title

    if decision == Claim.Status.APPROVED:
        # Only one person can own the item: reject competing claims.
        competing = claim.found_item.claims.filter(
            status__in=ACTIVE_STATUSES
        ).exclude(pk=claim.pk).select_related("claimant")

        for other in competing:
            other.status = Claim.Status.REJECTED
            other.save(update_fields=["status", "updated_at"])
            _log(
                other, ClaimReviewLog.Decision.REJECTED, reviewer=reviewer,
                comments="Another claim for this item was approved.",
            )
            notify(
                [other.claimant],
                "Claim rejected",
                f"Your claim for “{title}” was not approved.",
            )

        notify(
            [claim.claimant],
            "Claim approved",
            f"Your claim for “{title}” was approved. Bring your ID to the "
            "Campus Security Office to collect it.",
        )
    elif decision == Claim.Status.REJECTED:
        notify(
            [claim.claimant],
            "Claim rejected",
            f"Your claim for “{title}” was not approved."
            + (f" Reviewer note: {comments}" if comments else ""),
        )
    else:
        notify(
            [claim.claimant],
            "Claim under review",
            f"Security is now reviewing your claim for “{title}”.",
        )

    _sync_found_item_status(claim.found_item)

    return claim


@transaction.atomic
def record_handover(claim, reviewer, handover_location, handed_over_at, notes=""):
    handover = ItemHandover(
        claim=claim,
        handed_over_by=reviewer,
        received_by=claim.claimant,
        handover_location=handover_location,
        handed_over_at=handed_over_at,
        notes=notes,
    )
    # Enforces: claim must be approved, recipient must be the claimant.
    handover.full_clean()
    handover.save()

    claim.status = Claim.Status.COMPLETED
    claim.save(update_fields=["status", "updated_at"])
    _log(claim, ClaimReviewLog.Decision.COMPLETED, reviewer=reviewer, comments=notes)

    # Close the claimant's lost reports that were matched to this item.
    matched_lost_ids = MatchSuggestion.objects.filter(
        found_item=claim.found_item,
        lost_item__reporter=claim.claimant,
    ).exclude(
        status=MatchSuggestion.Status.REJECTED,
    ).values("lost_item_id")
    LostItem.objects.filter(pk__in=matched_lost_ids).update(
        status=LostItem.Status.RETURNED
    )

    _sync_found_item_status(claim.found_item)

    notify(
        [claim.claimant, claim.found_item.reporter],
        "Item returned",
        f"“{claim.found_item.title}” has been handed over to its owner. "
        "Thank you for using LOSTFinder!",
    )

    return handover

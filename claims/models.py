from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Claim(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    found_item = models.ForeignKey(
        "items.FoundItem",
        on_delete=models.PROTECT,
        related_name="claims",
    )
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="item_claims",
    )
    evidence_description = models.TextField(
        help_text="Describe identifying details that prove ownership."
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["found_item", "claimant"],
                name="unique_claimant_found_item",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "submitted_at"],
                name="claim_status_date_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.found_item_id
            and self.claimant_id
            and self.found_item.reporter_id == self.claimant_id
        ):
            raise ValidationError({
                "claimant": "You cannot claim an item you reported as found."
            })

    def __str__(self):
        return f"Claim #{self.pk} - {self.found_item.title}"


class ClaimReviewLog(models.Model):
    class Decision(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"
        COMPLETED = "completed", "Completed"

    claim = models.ForeignKey(
        Claim,
        on_delete=models.CASCADE,
        related_name="review_logs",
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="claim_reviews",
    )
    decision = models.CharField(
        max_length=20,
        choices=Decision.choices,
    )
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Review for claim #{self.claim_id}: {self.decision}"


class ItemHandover(models.Model):
    claim = models.OneToOneField(
        Claim,
        on_delete=models.PROTECT,
        related_name="handover",
    )
    handed_over_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="handovers_given",
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="handovers_received",
    )
    handover_location = models.CharField(max_length=200)
    notes = models.TextField(blank=True)
    handed_over_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-handed_over_at"]

    def clean(self):
        super().clean()

        if self.claim_id and self.claim.status != Claim.Status.APPROVED:
            raise ValidationError(
                "A handover can only be recorded for an approved claim."
            )

        if (
            self.claim_id
            and self.received_by_id
            and self.claim.claimant_id != self.received_by_id
        ):
            raise ValidationError(
                "The recipient must be the user who submitted the claim."
            )

    def __str__(self):
        return f"Handover for claim #{self.claim_id}"


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["recipient", "is_read", "created_at"],
                name="notification_inbox_idx",
            ),
        ]

    def __str__(self):
        return f"{self.title} - {self.recipient}"

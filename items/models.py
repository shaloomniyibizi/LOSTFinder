from django.db import models
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator


class ItemCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Item Category"
        verbose_name_plural = "Item Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class LostItem(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        MATCHED = "matched", "Possible match found"
        RETURNED = "returned", "Returned to owner"
        CLOSED = "closed", "Closed"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="lost_item_reports",
    )
    category = models.ForeignKey(
        ItemCategory,
        on_delete=models.PROTECT,
        related_name="lost_items",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=200)
    date_lost = models.DateField()
    image = models.ImageField(
        upload_to="lost_items/",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lost Item"
        verbose_name_plural = "Lost Items"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="lost_status_created_idx",
            ),
            models.Index(
                fields=["category", "date_lost"],
                name="lost_category_date_idx",
            ),
        ]

    def __str__(self):
        return f"Lost: {self.title}"


class FoundItem(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "available", "Available"
        CLAIM_PENDING = "claim_pending", "Claim pending"
        CLAIMED = "claimed", "Claim approved"
        RETURNED = "returned", "Returned to owner"
        CLOSED = "closed", "Closed"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="found_item_reports",
    )
    category = models.ForeignKey(
        ItemCategory,
        on_delete=models.PROTECT,
        related_name="found_items",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    location = models.CharField(max_length=200)
    date_found = models.DateField()
    image = models.ImageField(
        upload_to="found_items/",
        blank=True,
        null=True,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Found Item"
        verbose_name_plural = "Found Items"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="found_status_created_idx",
            ),
            models.Index(
                fields=["category", "date_found"],
                name="found_category_date_idx",
            ),
        ]

    def __str__(self):
        return f"Found: {self.title}"


class MatchSuggestion(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    lost_item = models.ForeignKey(
        LostItem,
        on_delete=models.CASCADE,
        related_name="match_suggestions",
    )
    found_item = models.ForeignKey(
        FoundItem,
        on_delete=models.CASCADE,
        related_name="match_suggestions",
    )
    score = models.PositiveSmallIntegerField(
        validators=[
            MinValueValidator(0),
            MaxValueValidator(100),
        ],
        help_text="Match score from 0 to 100.",
    )
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-score", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lost_item", "found_item"],
                name="unique_lost_found_match",
            ),
            models.CheckConstraint(
                condition=models.Q(score__gte=0, score__lte=100),
                name="match_score_0_100",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "score"],
                name="match_status_score_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.lost_item.title} ↔ {self.found_item.title} "
            f"({self.score}%)"
        )

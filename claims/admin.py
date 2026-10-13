
from django.contrib import admin
from .models import (
    Claim,
    ClaimReviewLog,
    ItemHandover,
    Notification,
)


class ClaimReviewLogInline(admin.TabularInline):
    model = ClaimReviewLog
    extra = 0
    readonly_fields = ("created_at",)


class ItemHandoverInline(admin.StackedInline):
    model = ItemHandover
    extra = 0
    max_num = 1


@admin.register(Claim)
class ClaimAdmin(admin.ModelAdmin):
    list_display = (
        "id", "found_item", "claimant",
        "status", "submitted_at",
    )
    list_filter = ("status", "submitted_at")
    search_fields = (
        "found_item__title",
        "claimant__email",
        "evidence_description",
    )
    readonly_fields = ("submitted_at", "updated_at")
    list_select_related = ("found_item", "claimant")
    inlines = [ClaimReviewLogInline, ItemHandoverInline]


@admin.register(ClaimReviewLog)
class ClaimReviewLogAdmin(admin.ModelAdmin):
    list_display = (
        "claim", "reviewer", "decision", "created_at",
    )
    list_filter = ("decision", "created_at")
    search_fields = (
        "claim__found_item__title",
        "reviewer__email",
        "comments",
    )
    readonly_fields = ("created_at",)


@admin.register(ItemHandover)
class ItemHandoverAdmin(admin.ModelAdmin):
    list_display = (
        "claim", "handed_over_by", "received_by",
        "handover_location", "handed_over_at",
    )
    list_filter = ("handed_over_at",)
    search_fields = (
        "claim__found_item__title",
        "handed_over_by__email",
        "received_by__email",
    )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "title", "recipient", "is_read", "created_at",
    )
    list_filter = ("is_read", "created_at")
    search_fields = ("title", "message", "recipient__email")
    readonly_fields = ("created_at",)

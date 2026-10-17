
from django.contrib import admin
from .matching import match_found_item, match_lost_item, sync_lost_item_status
from .models import (
    ItemCategory,
    LostItem,
    FoundItem,
    MatchSuggestion,
)


@admin.register(ItemCategory)
class ItemCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    search_fields = ("name",)
    list_filter = ("is_active",)


@admin.register(LostItem)
class LostItemAdmin(admin.ModelAdmin):
    list_display = (
        "title", "reporter", "category",
        "location", "date_lost", "status", "created_at",
    )
    list_filter = ("status", "category", "date_lost")
    search_fields = (
        "title", "description", "location",
        "reporter__email",
    )
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date_lost"
    list_select_related = ("reporter", "category")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # The app's views match on save; admin edits must do the same.
        match_lost_item(obj)


@admin.register(FoundItem)
class FoundItemAdmin(admin.ModelAdmin):
    list_display = (
        "title", "reporter", "category",
        "location", "date_found", "status", "created_at",
    )
    list_filter = ("status", "category", "date_found")
    search_fields = (
        "title", "description", "location",
        "reporter__email",
    )
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "date_found"
    list_select_related = ("reporter", "category")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        match_found_item(obj)

    # Deleting a found item cascades to its suggestions, so the lost items
    # it matched may no longer have a match (as in items.views.delete_item).
    def delete_model(self, request, obj):
        affected = list(LostItem.objects.filter(match_suggestions__found_item=obj))
        super().delete_model(request, obj)
        for lost_item in affected:
            sync_lost_item_status(lost_item)

    def delete_queryset(self, request, queryset):
        affected = list(
            LostItem.objects.filter(match_suggestions__found_item__in=queryset).distinct()
        )
        super().delete_queryset(request, queryset)
        for lost_item in affected:
            sync_lost_item_status(lost_item)


@admin.register(MatchSuggestion)
class MatchSuggestionAdmin(admin.ModelAdmin):
    list_display = (
        "lost_item", "found_item", "score",
        "status", "created_at",
    )
    list_filter = ("status",)
    search_fields = (
        "lost_item__title",
        "found_item__title",
        "reason",
    )
    readonly_fields = ("created_at",)

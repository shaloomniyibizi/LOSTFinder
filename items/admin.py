
from django.contrib import admin
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

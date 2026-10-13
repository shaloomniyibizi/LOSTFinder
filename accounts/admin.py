
from django.contrib import admin
from .models import UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "phone_number",
        "student_id",
        "faculty",
        "program",
        "onboarding_completed",
    )
    search_fields = (
        "user__email",
        "student_id",
        "faculty",
        "program",
    )
    list_filter = ("onboarding_completed", "faculty", "year_of_study")

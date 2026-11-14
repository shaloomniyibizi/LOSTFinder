
"""API permissions: the same rules as the HTML views' decorators."""

from rest_framework import permissions

from accounts.decorators import is_reviewer
from accounts.models import UserProfile


class IsOnboarded(permissions.BasePermission):
    """Like profile_completed_required: finish onboarding (PATCH /api/v1/me/) first."""

    message = (
        "Complete your profile first: PATCH /api/v1/me/ with the onboarding fields."
    )

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile.onboarding_completed


class IsReviewer(permissions.BasePermission):
    """Staff accounts and security officers."""

    message = "Only campus security and staff can do this."

    def has_permission(self, request, view):
        return is_reviewer(request.user)


class IsReporterOrReadOnly(permissions.BasePermission):
    """Anyone may read a report; only the person who filed it may change it."""

    message = "Only the person who reported this item can change it."

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.reporter_id == request.user.id

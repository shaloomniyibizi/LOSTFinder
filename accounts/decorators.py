
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import UserProfile


def profile_completed_required(view_func):
    """Require users to complete onboarding before using app pages."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        profile, _ = UserProfile.objects.get_or_create(
            user=request.user
        )

        if not profile.onboarding_completed:
            return redirect("onboarding")

        return view_func(request, *args, **kwargs)

    return wrapper


def is_reviewer(user):
    """Staff accounts and security officers review claims."""
    if not user.is_authenticated:
        return False

    if user.is_staff:
        return True

    profile = getattr(user, "profile", None)
    return (
        profile is not None
        and profile.user_type == UserProfile.UserType.SECURITY
    )


def reviewer_required(view_func):
    """Restrict a view to claim reviewers."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not is_reviewer(request.user):
            raise PermissionDenied

        return view_func(request, *args, **kwargs)

    return wrapper

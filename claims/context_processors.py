
from accounts.decorators import is_reviewer
from items.models import MatchSuggestion

from .models import Claim


def claims_nav(request):
    """Counts and roles used by the shared layout's sidebar and header."""
    user = request.user
    if not user.is_authenticated:
        return {}

    reviewer = is_reviewer(user)
    unread = user.notifications.filter(is_read=False)

    return {
        "unread_notifications": unread.count(),
        "recent_notifications": unread[:5],
        "user_is_reviewer": reviewer,
        "pending_match_count": MatchSuggestion.objects.filter(
            lost_item__reporter=user,
            status=MatchSuggestion.Status.PENDING,
        ).count(),
        "review_count": (
            Claim.objects.filter(
                status__in=[Claim.Status.SUBMITTED, Claim.Status.UNDER_REVIEW]
            ).count()
            if reviewer else 0
        ),
    }

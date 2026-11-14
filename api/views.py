
"""
LOSTFinder REST API (version 1).

The views are thin: they authenticate, check permissions, validate input
with the serializers (or the existing Django forms), then call the same
service functions the HTML pages use:

- items.services / items.matching   reports, matching, match decisions
- claims.services                   claim workflow, handovers, notifications
- dashboard.metrics                 dashboard numbers and chart series
"""

from django.contrib.auth import authenticate, logout
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Prefetch, Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.decorators import is_reviewer
from accounts.forms import OnboardingForm, RegistrationForm
from accounts.models import UserProfile
from accounts.views import LOGIN_ERROR
from claims import services as claim_services
from claims.models import Claim, Notification
from claims.views import CLOSED_STATUSES, REVIEW_FILTERS
from dashboard.metrics import build_dashboard, serialize_metrics
from items import services as item_services
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion
from items.views import MATCH_FILTERS

from . import serializers as s
from .permissions import IsOnboarded, IsReporterOrReadOnly, IsReviewer


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This record is linked to other records."
    default_code = "conflict"


def _service(call, *args, **kwargs):
    """Run a service function, turning its ValidationError into a 400."""
    try:
        return call(*args, **kwargs)
    except DjangoValidationError as error:
        raise ValidationError({"detail": " ".join(error.messages)})


def _schema_generation(view):
    """drf-spectacular inspects views with an anonymous user."""
    return getattr(view, "swagger_fake_view", False)


def _form_errors(form):
    return {
        field: [e["message"] for e in errors]
        for field, errors in form.errors.get_json_data().items()
    }


def _token_response(user, request, status_code=status.HTTP_200_OK):
    token, _ = Token.objects.get_or_create(user=user)
    return Response(
        {"token": token.key, "user": s.MeSerializer(user, context={"request": request}).data},
        status=status_code,
    )


# ---------- authentication and profile ----------

class RegisterView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["auth"], request=s.RegisterSerializer,
        responses={201: s.TokenResponseSerializer},
        summary="Create an account and get an API token",
    )
    def post(self, request):
        # The registration page's form, so the rules are identical.
        form = RegistrationForm({
            "email": request.data.get("email", ""),
            "password1": request.data.get("password", ""),
            "password2": request.data.get("password_confirm", ""),
        })
        if not form.is_valid():
            errors = _form_errors(form)
            # Report under the API's own field names.
            for old, new in (("password1", "password"), ("password2", "password_confirm")):
                if old in errors:
                    errors[new] = errors.pop(old)
            return Response(errors, status=status.HTTP_400_BAD_REQUEST)

        user = form.save()
        UserProfile.objects.create(user=user)
        return _token_response(user, request, status.HTTP_201_CREATED)


class TokenLoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["auth"], request=s.LoginSerializer,
        responses={200: s.TokenResponseSerializer},
        summary="Exchange email and password for an API token",
    )
    def post(self, request):
        serializer = s.LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request._request,
            email=serializer.validated_data["email"],
            password=serializer.validated_data["password"],
        )
        if user is None:
            raise ValidationError({"detail": LOGIN_ERROR})
        return _token_response(user, request)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["auth"], request=None, responses={204: None},
                   summary="Revoke the API token (or end the browser session)")
    def post(self, request):
        if isinstance(request.auth, Token):
            request.auth.delete()
        else:
            logout(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """The signed-in user. PATCH completes onboarding or edits the profile."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(tags=["auth"], responses=s.MeSerializer, summary="Current user and profile")
    def get(self, request):
        return Response(s.MeSerializer(request.user, context={"request": request}).data)

    @extend_schema(
        tags=["auth"], request=s.ProfileUpdateSerializer, responses=s.MeSerializer,
        summary="Complete onboarding or update the profile",
    )
    def patch(self, request):
        return self._save(request, partial=True)

    @extend_schema(
        tags=["auth"], request=s.ProfileUpdateSerializer, responses=s.MeSerializer,
        summary="Replace the profile",
    )
    def put(self, request):
        return self._save(request, partial=False)

    def _save(self, request, partial):
        user = request.user
        profile, _ = UserProfile.objects.get_or_create(user=user)

        # Validated by the onboarding page's form. A PATCH keeps the
        # fields it does not mention.
        if partial:
            data = {
                field: "" if getattr(profile, field) is None else getattr(profile, field)
                for field in s.ONBOARDING_FIELDS
            }
        else:
            data = {}
        for field in s.ONBOARDING_FIELDS:
            if field in request.data:
                data[field] = request.data.get(field)

        form = OnboardingForm(data, request.FILES, instance=profile, allow_role=user.is_staff)
        if not form.is_valid():
            return Response(_form_errors(form), status=status.HTTP_400_BAD_REQUEST)

        profile = form.save(commit=False)
        if not profile.onboarding_completed and not user.is_staff:
            profile.user_type = UserProfile.UserType.STUDENT
        profile.onboarding_completed = True
        profile.save()

        return Response(s.MeSerializer(user, context={"request": request}).data)


# ---------- categories and reports ----------

@extend_schema_view(
    list=extend_schema(tags=["items"], summary="Active item categories"),
    retrieve=extend_schema(tags=["items"]),
)
class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ItemCategory.objects.filter(is_active=True)
    serializer_class = s.CategorySerializer
    pagination_class = None


REPORT_FILTERS = [
    OpenApiParameter("q", str, description="Search title, description and location."),
    OpenApiParameter("category", int, description="Category id."),
    OpenApiParameter("status", str, description="Report status."),
    OpenApiParameter("mine", bool, description="Only reports I filed."),
]


class ReportViewSet(viewsets.ModelViewSet):
    """Shared behaviour of /lost-items/ and /found-items/."""

    model = None
    save_serializer_class = None
    permission_classes = [IsAuthenticated, IsOnboarded, IsReporterOrReadOnly]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = self.model.objects.select_related("category", "reporter")
        params = self.request.query_params

        query = params.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(title__icontains=query)
                | Q(description__icontains=query)
                | Q(location__icontains=query)
            )

        category = params.get("category", "").strip()
        if category.isdigit():
            queryset = queryset.filter(category_id=int(category))

        report_status = params.get("status", "").strip()
        if report_status in self.model.Status.values:
            queryset = queryset.filter(status=report_status)

        if params.get("mine", "").lower() in ("1", "true", "yes"):
            queryset = queryset.filter(reporter=self.request.user)

        return queryset

    def _saved_response(self, item, status_code):
        """The saved report plus how many matches the save produced."""
        suggestions = item_services.run_matching(item)
        item.refresh_from_db()  # matching may have changed the status
        item.matches_found = len(suggestions)
        data = self.save_serializer_class(item, context=self.get_serializer_context()).data
        return Response(data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(reporter=request.user)
        return self._saved_response(item, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return self._saved_response(item, status.HTTP_200_OK)

    def perform_destroy(self, instance):
        try:
            item_services.delete_report(instance)
        except ProtectedError:
            raise Conflict(
                "This report cannot be deleted because it is linked to other "
                "records (for example, claims). Please contact an administrator."
            )

    def _matches(self, item):
        """Match suggestions for a report: only its reporter sees them."""
        if item.reporter_id != self.request.user.id:
            return MatchSuggestion.objects.none()
        return item.match_suggestions.exclude(
            status=MatchSuggestion.Status.REJECTED
        ).select_related(
            "lost_item__category", "lost_item__reporter",
            "found_item__category", "found_item__reporter",
        )

    @extend_schema(responses=s.MatchSerializer(many=True),
                   summary="Live match suggestions for this report (reporter only)")
    @action(detail=True, methods=["get"], pagination_class=None)
    def matches(self, request, pk=None):
        item = self.get_object()
        data = s.MatchSerializer(
            self._matches(item), many=True, context=self.get_serializer_context()
        ).data
        return Response(data)


@extend_schema_view(
    list=extend_schema(tags=["items"], parameters=REPORT_FILTERS, summary="Lost reports"),
    create=extend_schema(tags=["items"], responses={201: s.LostItemSaveSerializer},
                         summary="Report a lost item (runs matching)"),
    retrieve=extend_schema(tags=["items"]),
    update=extend_schema(tags=["items"], responses=s.LostItemSaveSerializer),
    partial_update=extend_schema(tags=["items"], responses=s.LostItemSaveSerializer),
    destroy=extend_schema(tags=["items"]),
    matches=extend_schema(tags=["matches"]),
)
class LostItemViewSet(ReportViewSet):
    model = LostItem
    serializer_class = s.LostItemSerializer
    save_serializer_class = s.LostItemSaveSerializer


@extend_schema_view(
    list=extend_schema(tags=["items"], parameters=REPORT_FILTERS, summary="Found reports"),
    create=extend_schema(tags=["items"], responses={201: s.FoundItemSaveSerializer},
                         summary="Turn in a found item (runs matching)"),
    retrieve=extend_schema(tags=["items"]),
    update=extend_schema(tags=["items"], responses=s.FoundItemSaveSerializer),
    partial_update=extend_schema(tags=["items"], responses=s.FoundItemSaveSerializer),
    destroy=extend_schema(tags=["items"]),
    matches=extend_schema(tags=["matches"]),
)
class FoundItemViewSet(ReportViewSet):
    model = FoundItem
    serializer_class = s.FoundItemSerializer
    save_serializer_class = s.FoundItemSaveSerializer

    def get_queryset(self):
        if _schema_generation(self):
            return FoundItem.objects.none()
        mine = Claim.objects.filter(claimant=self.request.user)
        return super().get_queryset().prefetch_related(
            Prefetch("claims", queryset=mine, to_attr="my_claims")
        )


# ---------- matches ----------

@extend_schema_view(
    list=extend_schema(
        tags=["matches"], summary="Match suggestions involving my reports",
        parameters=[
            OpenApiParameter("status", str, enum=[v for v, _ in MATCH_FILTERS],
                             description="Default: active (pending and accepted)."),
            OpenApiParameter("side", str, enum=["lost", "found"],
                             description="lost: matches for my lost reports; "
                                         "found: for items I turned in."),
        ],
    ),
    retrieve=extend_schema(tags=["matches"]),
)
class MatchViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = s.MatchSerializer

    def get_queryset(self):
        if _schema_generation(self):
            return MatchSuggestion.objects.none()
        user = self.request.user
        queryset = MatchSuggestion.objects.filter(
            Q(lost_item__reporter=user) | Q(found_item__reporter=user)
        ).select_related(
            "lost_item__category", "lost_item__reporter",
            "found_item__category", "found_item__reporter",
        )

        if self.action != "list":
            return queryset

        params = self.request.query_params
        match_status = params.get("status", "active")
        if match_status == "active":
            queryset = queryset.exclude(status=MatchSuggestion.Status.REJECTED)
        elif match_status in MatchSuggestion.Status.values:
            queryset = queryset.filter(status=match_status)

        side = params.get("side")
        if side == "lost":
            queryset = queryset.filter(lost_item__reporter=user)
        elif side == "found":
            queryset = queryset.filter(found_item__reporter=user)

        return queryset

    @extend_schema(tags=["matches"], request=s.MatchDecisionSerializer,
                   responses=s.MatchSerializer,
                   summary="Accept, reject or reset a match (owner of the lost item)")
    @action(detail=True, methods=["post"])
    def decision(self, request, pk=None):
        match = self.get_object()
        if match.lost_item.reporter_id != request.user.id:
            raise PermissionDenied("Only the owner of the lost item can decide on a match.")

        serializer = s.MatchDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _service(item_services.decide_match, match, serializer.validated_data["action"])
        return Response(self.get_serializer(match).data)


# ---------- claims ----------

CLAIM_LIST_PARAMS = [
    OpenApiParameter(
        "scope", str, enum=["mine", "found", "review"],
        description="mine: claims I made (default); found: claims on items I "
                    "turned in; review: the security review queue (reviewers only).",
    ),
    OpenApiParameter(
        "status", str,
        description="scope=review: active (default), approved, closed or all. "
                    "Other scopes: a claim status.",
    ),
    OpenApiParameter("q", str, description="scope=review: search item title or claimant email."),
]


@extend_schema_view(
    list=extend_schema(tags=["claims"], parameters=CLAIM_LIST_PARAMS, summary="Claims"),
    retrieve=extend_schema(tags=["claims"], responses=s.ClaimDetailSerializer,
                           summary="A claim with its timeline and handover"),
    create=extend_schema(tags=["claims"], request=s.ClaimCreateSerializer,
                         responses={201: s.ClaimDetailSerializer},
                         summary="Claim a found item"),
)
class ClaimViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                   mixins.CreateModelMixin, viewsets.GenericViewSet):
    serializer_class = s.ClaimSerializer

    def get_serializer_class(self):
        if self.action == "list":
            return s.ClaimSerializer
        return s.ClaimDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["is_reviewer"] = is_reviewer(self.request.user)
        return context

    def get_queryset(self):
        if _schema_generation(self):
            return Claim.objects.none()
        user = self.request.user
        reviewer = is_reviewer(user)
        queryset = Claim.objects.select_related(
            "found_item__category", "found_item__reporter", "claimant",
        )

        if self.action != "list":
            # Like the claim page: the claimant, the finder, and reviewers.
            if reviewer:
                return queryset
            return queryset.filter(Q(claimant=user) | Q(found_item__reporter=user))

        params = self.request.query_params
        scope = params.get("scope", "mine")
        claim_status = params.get("status", "").strip()

        if scope == "review":
            if not reviewer:
                raise PermissionDenied("Only campus security and staff see the review queue.")
            return self._review_queue(queryset, claim_status or "active", params)

        if scope == "found":
            queryset = queryset.filter(found_item__reporter=user)
        else:
            queryset = queryset.filter(claimant=user)

        if claim_status in Claim.Status.values:
            queryset = queryset.filter(status=claim_status)
        return queryset

    def _review_queue(self, queryset, queue, params):
        """The same filters and ordering as the review queue page."""
        if queue not in dict(REVIEW_FILTERS):
            queue = "active"

        query = params.get("q", "").strip()
        if query:
            queryset = queryset.filter(
                Q(found_item__title__icontains=query) | Q(claimant__email__icontains=query)
            )

        # Work queues are handled oldest first; history newest first.
        if queue == "active":
            return queryset.filter(
                status__in=claim_services.ACTIVE_STATUSES
            ).order_by("submitted_at")
        if queue == "approved":
            return queryset.filter(status=Claim.Status.APPROVED).order_by("updated_at")
        if queue == "closed":
            return queryset.filter(status__in=CLOSED_STATUSES).order_by("-updated_at")
        return queryset

    def _detail(self, claim, status_code=status.HTTP_200_OK):
        """The claim as it is now, after a service call changed it."""
        claim = Claim.objects.select_related(
            "found_item__category", "found_item__reporter", "claimant",
        ).get(pk=claim.pk)
        context = self.get_serializer_context()
        return Response(s.ClaimDetailSerializer(claim, context=context).data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = s.ClaimCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        claim = _service(
            claim_services.submit_claim,
            serializer.validated_data["found_item"],
            request.user,
            serializer.validated_data["evidence_description"],
        )
        return self._detail(claim, status.HTTP_201_CREATED)

    @extend_schema(tags=["claims"], request=None, responses=s.ClaimDetailSerializer,
                   summary="Cancel my claim")
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        claim = self.get_object()
        _service(claim_services.cancel_claim, claim, request.user)
        return self._detail(claim)

    @extend_schema(tags=["claims"], request=s.ClaimReviewSerializer,
                   responses=s.ClaimDetailSerializer,
                   summary="Review a claim (security and staff)")
    @action(detail=True, methods=["post"],
            permission_classes=[IsAuthenticated, IsOnboarded, IsReviewer])
    def review(self, request, pk=None):
        claim = self.get_object()
        serializer = s.ClaimReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _service(
            claim_services.review_claim, claim, request.user,
            serializer.validated_data["decision"], serializer.validated_data["comments"],
        )
        return self._detail(claim)

    @extend_schema(tags=["claims"], request=s.ClaimHandoverSerializer,
                   responses=s.ClaimDetailSerializer,
                   summary="Record the handover of an approved claim (security and staff)")
    @action(detail=True, methods=["post"],
            permission_classes=[IsAuthenticated, IsOnboarded, IsReviewer])
    def handover(self, request, pk=None):
        claim = self.get_object()
        serializer = s.ClaimHandoverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _service(
            claim_services.record_handover, claim, request.user,
            data["handover_location"],
            data.get("handed_over_at") or timezone.now(),
            data["notes"],
        )
        return self._detail(claim)


# ---------- notifications and dashboard ----------

@extend_schema_view(
    list=extend_schema(
        tags=["notifications"], summary="My notifications, newest first",
        parameters=[OpenApiParameter("unread", bool, description="Only unread ones.")],
    ),
)
class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    # Like the notifications page, this works before onboarding is complete.
    permission_classes = [IsAuthenticated]
    serializer_class = s.NotificationSerializer

    def get_queryset(self):
        if _schema_generation(self):
            return Notification.objects.none()
        queryset = self.request.user.notifications.all()
        if self.request.query_params.get("unread", "").lower() in ("1", "true", "yes"):
            queryset = queryset.filter(is_read=False)
        return queryset

    @extend_schema(tags=["notifications"], request=None, responses=s.NotificationSerializer,
                   summary="Mark one notification as read")
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at"])
        return Response(self.get_serializer(notification).data)

    @extend_schema(tags=["notifications"], request=None,
                   responses={200: {"type": "object", "properties": {"marked": {"type": "integer"}}}},
                   summary="Mark all notifications as read")
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        marked = request.user.notifications.filter(is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
        return Response({"marked": marked})


class DashboardView(APIView):
    @extend_schema(
        tags=["dashboard"], responses={200: OpenApiTypes.OBJECT},
        summary="Role-based dashboard numbers and chart series",
        description="The same data the dashboard page polls (dashboard.metrics). "
                    "Reviewers get the security desk view; everyone else their own.",
    )
    def get(self, request):
        return Response(serialize_metrics(build_dashboard(request.user)))

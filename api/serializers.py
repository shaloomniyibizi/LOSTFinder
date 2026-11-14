
"""
JSON representations for the REST API.

Validation mirrors the HTML forms (items.forms, claims.forms), and state
changes are made by the service layer (items.services, claims.services),
never by the serializers themselves.
"""

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from accounts.decorators import is_reviewer
from accounts.forms import OnboardingForm
from accounts.models import UserProfile
from claims.forms import ReviewForm
from claims.models import Claim, ClaimReviewLog, ItemHandover, Notification
from claims.services import can_claim
from dashboard.metrics import role_label
from items.cards import report_card
from items.forms import DESCRIPTION_MAX, MAX_IMAGE_BYTES
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion
from items.services import MATCH_DECISIONS
from items.templatetags.lostfinder import match_reasons, match_strength


def _absolute(request, url):
    return request.build_absolute_uri(url) if request and url else url


def _display_name(user):
    return user.get_full_name() or user.username


# ---------- accounts ----------

class UserSummarySerializer(serializers.Serializer):
    """Public view of a person: never their email or contact details."""

    id = serializers.IntegerField()
    name = serializers.SerializerMethodField()

    def get_name(self, user) -> str:
        return _display_name(user)


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserProfile
        fields = [
            "phone_number", "address", "profile_photo", "user_type",
            "student_id", "faculty", "program", "year_of_study", "bio",
            "onboarding_completed",
        ]
        read_only_fields = fields


class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    email = serializers.EmailField()
    username = serializers.CharField()
    name = serializers.SerializerMethodField()
    is_staff = serializers.BooleanField()
    is_reviewer = serializers.SerializerMethodField()
    role = serializers.SerializerMethodField()
    profile = serializers.SerializerMethodField()

    def get_name(self, user) -> str:
        return _display_name(user)

    def get_is_reviewer(self, user) -> bool:
        return is_reviewer(user)

    def get_role(self, user) -> str:
        return role_label(user)

    @extend_schema_field(ProfileSerializer)
    def get_profile(self, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return ProfileSerializer(profile, context=self.context).data


class ProfileUpdateSerializer(serializers.Serializer):
    """
    Documents PATCH /api/v1/me/. The request is validated by
    accounts.forms.OnboardingForm, exactly like the onboarding page.
    """

    phone_number = serializers.CharField(help_text="10 digits; spaces and dashes are removed.")
    address = serializers.CharField()
    profile_photo = serializers.ImageField(required=False)
    student_id = serializers.CharField()
    faculty = serializers.CharField()
    program = serializers.CharField()
    year_of_study = serializers.ChoiceField(choices=UserProfile.YEAR_CHOICES)
    bio = serializers.CharField(max_length=500)
    user_type = serializers.ChoiceField(
        choices=UserProfile.UserType.choices, required=False,
        help_text="Staff accounts only; ignored for everyone else.",
    )


ONBOARDING_FIELDS = [f for f in OnboardingForm.Meta.fields if f != "profile_photo"]


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password_confirm = serializers.CharField(write_only=True, style={"input_type": "password"})


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class TokenResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    user = MeSerializer()


# ---------- items ----------

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemCategory
        fields = ["id", "name", "description"]


class ItemBriefSerializer(serializers.Serializer):
    """A lost or found report inside a match, claim or notification."""

    id = serializers.IntegerField()
    kind = serializers.SerializerMethodField()
    title = serializers.CharField()
    category = serializers.CharField(source="category.name")
    location = serializers.CharField()
    date = serializers.SerializerMethodField()
    status = serializers.CharField()
    status_display = serializers.CharField(source="get_status_display")
    image_url = serializers.SerializerMethodField()

    def _kind(self, item):
        return "lost" if isinstance(item, LostItem) else "found"

    def get_kind(self, item) -> str:
        return self._kind(item)

    @extend_schema_field(OpenApiTypes.DATE)
    def get_date(self, item):
        return item.date_lost if self._kind(item) == "lost" else item.date_found

    def get_image_url(self, item) -> str:
        url = report_card(item, self._kind(item))["image_url"]
        return _absolute(self.context.get("request"), url)


class ReportSerializer(serializers.ModelSerializer):
    """Shared fields and validation for lost and found reports (as items.forms)."""

    date_field = None

    category_name = serializers.CharField(source="category.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    reporter = UserSummarySerializer(read_only=True)
    is_owner = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    description = serializers.CharField(max_length=DESCRIPTION_MAX)

    common_fields = [
        "id", "title", "category", "category_name", "description",
        "location", "image", "image_url", "status", "status_display",
        "reporter", "is_owner", "created_at", "updated_at",
    ]
    common_read_only = ["status", "created_at", "updated_at"]

    def get_is_owner(self, item) -> bool:
        request = self.context.get("request")
        return bool(request and item.reporter_id == request.user.id)

    def get_image_url(self, item) -> str:
        """The photo, or the same placeholder the web pages show."""
        kind = "lost" if isinstance(item, LostItem) else "found"
        url = report_card(item, kind)["image_url"]
        return _absolute(self.context.get("request"), url)

    def validate_category(self, category):
        # Retired categories are hidden, except the one an edited report uses.
        if not category.is_active and (
            self.instance is None or self.instance.category_id != category.pk
        ):
            raise serializers.ValidationError("This category is no longer available.")
        return category

    def validate_image(self, image):
        if image and getattr(image, "size", 0) > MAX_IMAGE_BYTES:
            raise serializers.ValidationError("The image must not exceed 5 MB.")
        return image

    def _not_in_future(self, value, label):
        if value > timezone.localdate():
            raise serializers.ValidationError(f"The date {label} cannot be in the future.")
        return value


class LostItemSerializer(ReportSerializer):
    class Meta:
        model = LostItem
        fields = ReportSerializer.common_fields + ["date_lost"]
        read_only_fields = ReportSerializer.common_read_only

    def validate_date_lost(self, value):
        return self._not_in_future(value, "lost")


class FoundItemSerializer(ReportSerializer):
    can_claim = serializers.SerializerMethodField()
    my_claim = serializers.SerializerMethodField()

    class Meta:
        model = FoundItem
        fields = ReportSerializer.common_fields + ["date_found", "can_claim", "my_claim"]
        read_only_fields = ReportSerializer.common_read_only

    def validate_date_found(self, value):
        return self._not_in_future(value, "found")

    def _my_claim(self, item):
        user = self.context["request"].user
        # Prefetched by the viewset as `my_claims`; fall back to a query.
        claims = getattr(item, "my_claims", None)
        if claims is None:
            return item.claims.filter(claimant=user).first()
        return claims[0] if claims else None

    def get_can_claim(self, item) -> bool:
        user = self.context["request"].user
        mine = self._my_claim(item)
        return can_claim(user, item) and (
            mine is None or mine.status == Claim.Status.CANCELLED
        )

    @extend_schema_field({
        "type": "object", "nullable": True,
        "properties": {"id": {"type": "integer"}, "status": {"type": "string"}},
    })
    def get_my_claim(self, item):
        mine = self._my_claim(item)
        return {"id": mine.pk, "status": mine.status} if mine else None


class ReportSaveResponseMixin(serializers.Serializer):
    matches_found = serializers.IntegerField(
        help_text="Match suggestions found when the report was saved."
    )


class LostItemSaveSerializer(LostItemSerializer, ReportSaveResponseMixin):
    class Meta(LostItemSerializer.Meta):
        fields = LostItemSerializer.Meta.fields + ["matches_found"]


class FoundItemSaveSerializer(FoundItemSerializer, ReportSaveResponseMixin):
    class Meta(FoundItemSerializer.Meta):
        fields = FoundItemSerializer.Meta.fields + ["matches_found"]


# ---------- matches ----------

class MatchReasonSerializer(serializers.Serializer):
    text = serializers.CharField()
    points = serializers.IntegerField(allow_null=True)


class MatchSerializer(serializers.ModelSerializer):
    lost_item = ItemBriefSerializer(read_only=True)
    found_item = ItemBriefSerializer(read_only=True)
    strength = serializers.SerializerMethodField()
    reasons = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    can_decide = serializers.SerializerMethodField()

    class Meta:
        model = MatchSuggestion
        fields = [
            "id", "score", "ml_probability", "strength", "reason", "reasons", "status",
            "status_display", "lost_item", "found_item", "can_decide",
            "created_at",
        ]

    def get_strength(self, match) -> str:
        return match_strength(match.score)

    @extend_schema_field(MatchReasonSerializer(many=True))
    def get_reasons(self, match):
        return match_reasons(match.reason)

    def get_can_decide(self, match) -> bool:
        """Only the owner of the lost item accepts or rejects a match."""
        return match.lost_item.reporter_id == self.context["request"].user.id


class MatchDecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=list(MATCH_DECISIONS))


# ---------- claims ----------

class ClaimReviewLogSerializer(serializers.ModelSerializer):
    reviewer = UserSummarySerializer(read_only=True, allow_null=True)
    decision_display = serializers.CharField(source="get_decision_display")

    class Meta:
        model = ClaimReviewLog
        fields = ["decision", "decision_display", "reviewer", "comments", "created_at"]


class HandoverSerializer(serializers.ModelSerializer):
    handed_over_by = UserSummarySerializer(read_only=True)

    class Meta:
        model = ItemHandover
        fields = ["handover_location", "handed_over_at", "handed_over_by", "notes"]


class ClaimSerializer(serializers.ModelSerializer):
    """
    A claim, as the viewer may see it. The finder sees progress only:
    the evidence and the claimant's email go to the claimant and reviewers.
    """

    found_item = ItemBriefSerializer(read_only=True)
    claimant = serializers.SerializerMethodField()
    evidence_description = serializers.SerializerMethodField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = Claim
        fields = [
            "id", "found_item", "claimant", "evidence_description", "status",
            "status_display", "permissions", "submitted_at", "updated_at",
        ]

    def _viewer(self):
        user = self.context["request"].user
        if "is_reviewer" not in self.context:
            self.context["is_reviewer"] = is_reviewer(user)
        return user, self.context["is_reviewer"]

    def _can_see_private(self, claim):
        user, reviewer = self._viewer()
        return reviewer or claim.claimant_id == user.id

    @extend_schema_field({
        "type": "object",
        "properties": {
            "id": {"type": "integer"}, "name": {"type": "string"},
            "email": {"type": "string", "nullable": True},
        },
    })
    def get_claimant(self, claim):
        data = {"id": claim.claimant_id, "name": _display_name(claim.claimant)}
        data["email"] = claim.claimant.email if self._can_see_private(claim) else None
        return data

    @extend_schema_field(OpenApiTypes.STR)
    def get_evidence_description(self, claim):
        return claim.evidence_description if self._can_see_private(claim) else None

    @extend_schema_field({
        "type": "object",
        "properties": {
            "can_cancel": {"type": "boolean"},
            "can_review": {"type": "boolean"},
            "can_handover": {"type": "boolean"},
        },
    })
    def get_permissions(self, claim):
        from claims.services import ACTIVE_STATUSES

        user, reviewer = self._viewer()
        is_claimant = claim.claimant_id == user.id
        return {
            "can_cancel": is_claimant and claim.status in ACTIVE_STATUSES,
            "can_review": reviewer and not is_claimant and claim.status in ACTIVE_STATUSES,
            "can_handover": (
                reviewer and not is_claimant and claim.status == Claim.Status.APPROVED
            ),
        }


class ClaimDetailSerializer(ClaimSerializer):
    timeline = serializers.SerializerMethodField()
    handover = serializers.SerializerMethodField()

    class Meta(ClaimSerializer.Meta):
        fields = ClaimSerializer.Meta.fields + ["timeline", "handover"]

    @extend_schema_field(ClaimReviewLogSerializer(many=True))
    def get_timeline(self, claim):
        logs = claim.review_logs.select_related("reviewer")
        return ClaimReviewLogSerializer(logs, many=True, context=self.context).data

    @extend_schema_field(HandoverSerializer(allow_null=True))
    def get_handover(self, claim):
        handover = getattr(claim, "handover", None)
        if handover is None:
            return None
        return HandoverSerializer(handover, context=self.context).data


class ClaimCreateSerializer(serializers.Serializer):
    found_item = serializers.PrimaryKeyRelatedField(queryset=FoundItem.objects.all())
    evidence_description = serializers.CharField(
        min_length=20,
        help_text=Claim._meta.get_field("evidence_description").help_text,
    )


REVIEW_DECISIONS = ReviewForm.base_fields["decision"].choices


class ClaimReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=REVIEW_DECISIONS)
    comments = serializers.CharField(required=False, allow_blank=True, default="")


class ClaimHandoverSerializer(serializers.Serializer):
    handover_location = serializers.CharField(max_length=200)
    handed_over_at = serializers.DateTimeField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_handed_over_at(self, value):
        if value > timezone.now():
            raise serializers.ValidationError("The handover time cannot be in the future.")
        return value


# ---------- notifications ----------

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "message", "is_read", "created_at", "read_at"]
        read_only_fields = fields

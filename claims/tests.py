from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from items.matching import match_lost_item
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion

from . import services
from .models import Claim, ClaimReviewLog, ItemHandover, Notification


EVIDENCE = "Serial number C02XK1 and a blue sticker under the lid."


def make_user(name, user_type=UserProfile.UserType.STUDENT, **extra):
    user = get_user_model().objects.create_user(
        name, f"{name}@uni.edu", "pw-12345!", **extra
    )
    UserProfile.objects.create(
        user=user, onboarding_completed=True, user_type=user_type
    )
    return user


class ClaimTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.rival = make_user("rival")
        cls.finder = make_user("finder")
        cls.stranger = make_user("stranger")
        cls.officer = make_user(
            "officer", user_type=UserProfile.UserType.SECURITY
        )
        cls.admin = make_user("admin", is_staff=True)
        cls.category = ItemCategory.objects.create(name="Electronics")

    def setUp(self):
        today = timezone.localdate()
        self.found = FoundItem.objects.create(
            reporter=self.finder, category=self.category,
            title="Grey MacBook laptop",
            description="Grey laptop, blue sticker on lid",
            location="Main Library", date_found=today,
        )
        self.lost = LostItem.objects.create(
            reporter=self.owner, category=self.category,
            title="Grey MacBook Pro laptop",
            description="Grey laptop with blue sticker on the lid",
            location="Main Library", date_lost=today,
        )

    def refresh(self, *objs):
        for obj in objs:
            obj.refresh_from_db()

    def submit(self, user=None):
        return services.submit_claim(self.found, user or self.owner, EVIDENCE)

    def approve(self, claim):
        return services.review_claim(claim, self.officer, Claim.Status.APPROVED)


class ClaimWorkflowTests(ClaimTestCase):
    def test_submit_marks_item_pending_logs_and_notifies(self):
        claim = self.submit()

        self.refresh(self.found)
        self.assertEqual(claim.status, Claim.Status.SUBMITTED)
        self.assertEqual(self.found.status, FoundItem.Status.CLAIM_PENDING)
        self.assertEqual(
            list(claim.review_logs.values_list("decision", flat=True)),
            [ClaimReviewLog.Decision.SUBMITTED],
        )
        notified = set(
            Notification.objects.values_list("recipient__username", flat=True)
        )
        self.assertEqual(notified, {"officer", "admin", "finder"})

    def test_finder_cannot_claim_own_item(self):
        with self.assertRaises(ValidationError):
            self.submit(self.finder)

    def test_duplicate_claim_rejected(self):
        self.submit()
        with self.assertRaises(ValidationError):
            self.submit()

    def test_cancelled_claim_can_be_resubmitted(self):
        claim = self.submit()
        services.cancel_claim(claim, self.owner)
        self.refresh(self.found)
        self.assertEqual(self.found.status, FoundItem.Status.AVAILABLE)

        again = self.submit()

        self.assertEqual(again.pk, claim.pk)
        self.assertEqual(again.status, Claim.Status.SUBMITTED)

    def test_only_claimant_can_cancel(self):
        claim = self.submit()
        with self.assertRaises(ValidationError):
            services.cancel_claim(claim, self.rival)

    def test_approve_rejects_competing_claims(self):
        mine = self.submit()
        theirs = self.submit(self.rival)

        self.approve(mine)

        self.refresh(theirs, self.found)
        self.assertEqual(theirs.status, Claim.Status.REJECTED)
        self.assertEqual(self.found.status, FoundItem.Status.CLAIMED)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.rival, title="Claim rejected"
            ).exists()
        )

    def test_reject_returns_item_to_custody(self):
        claim = self.submit()

        services.review_claim(
            claim, self.officer, Claim.Status.REJECTED, "Serial mismatch"
        )

        self.refresh(self.found)
        self.assertEqual(self.found.status, FoundItem.Status.AVAILABLE)
        self.assertIn(
            "Serial mismatch",
            Notification.objects.get(recipient=self.owner, title="Claim rejected").message,
        )

    def test_invalid_transitions(self):
        claim = self.submit()
        self.approve(claim)

        with self.assertRaises(ValidationError):
            services.review_claim(claim, self.officer, Claim.Status.REJECTED)
        with self.assertRaises(ValidationError):
            services.review_claim(claim, self.officer, Claim.Status.UNDER_REVIEW)
        with self.assertRaises(ValidationError):
            services.cancel_claim(claim, self.owner)

    def test_reviewer_cannot_review_own_claim(self):
        claim = self.submit(self.officer)
        with self.assertRaises(ValidationError):
            self.approve(claim)

    def test_handover_requires_approval(self):
        claim = self.submit()
        with self.assertRaises(ValidationError):
            services.record_handover(
                claim, self.officer, "Security office", timezone.now()
            )
        self.assertFalse(ItemHandover.objects.exists())

    def test_handover_completes_claim_and_returns_items(self):
        match_lost_item(self.lost)
        MatchSuggestion.objects.update(status=MatchSuggestion.Status.ACCEPTED)
        claim = self.submit()
        self.approve(claim)

        services.record_handover(
            claim, self.officer, "Security office",
            timezone.now() - timedelta(minutes=5), "ID checked",
        )

        self.refresh(claim, self.found, self.lost)
        self.assertEqual(claim.status, Claim.Status.COMPLETED)
        self.assertEqual(self.found.status, FoundItem.Status.RETURNED)
        self.assertEqual(self.lost.status, LostItem.Status.RETURNED)
        self.assertEqual(claim.handover.received_by, self.owner)

    def test_pending_claim_keeps_item_matchable(self):
        self.submit(self.rival)

        suggestions = match_lost_item(self.lost)

        self.assertEqual([s.found_item for s in suggestions], [self.found])

    def test_approved_item_drops_other_pending_matches(self):
        match_lost_item(self.lost)
        claim = self.submit(self.rival)

        self.approve(claim)

        self.assertFalse(
            MatchSuggestion.objects.filter(
                status=MatchSuggestion.Status.PENDING
            ).exists()
        )
        self.refresh(self.lost)
        self.assertEqual(self.lost.status, LostItem.Status.OPEN)


class ClaimViewPermissionTests(ClaimTestCase):
    def test_submit_claim_through_view(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("claim_create", args=[self.found.pk]),
            {"evidence_description": EVIDENCE},
        )

        claim = Claim.objects.get()
        self.assertRedirects(response, reverse("claim_detail", args=[claim.pk]))

    def test_short_evidence_is_rejected(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("claim_create", args=[self.found.pk]),
            {"evidence_description": "mine"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Claim.objects.exists())

    def test_finder_gets_no_claim_form(self):
        self.client.force_login(self.finder)

        response = self.client.get(reverse("claim_create", args=[self.found.pk]))

        self.assertRedirects(
            response, reverse("found_item_detail", args=[self.found.pk])
        )

    def test_detail_visibility(self):
        claim = self.submit()
        url = reverse("claim_detail", args=[claim.pk])

        for user in (self.owner, self.officer, self.admin):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertContains(response, EVIDENCE, msg_prefix=user.username)

        # The finder sees progress but not the ownership evidence.
        self.client.force_login(self.finder)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, EVIDENCE)
        self.assertNotContains(response, self.owner.email)

        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_review_queue_is_reviewers_only(self):
        url = reverse("review_queue")

        for user in (self.owner, self.finder):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)

        for user in (self.officer, self.admin):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 200)

    def test_students_cannot_review_or_hand_over(self):
        claim = self.submit()
        self.client.force_login(self.rival)

        review = self.client.post(
            reverse("claim_review", args=[claim.pk]),
            {"decision": Claim.Status.APPROVED},
        )
        handover = self.client.get(reverse("claim_handover", args=[claim.pk]))

        self.assertEqual(review.status_code, 403)
        self.assertEqual(handover.status_code, 403)
        self.refresh(claim)
        self.assertEqual(claim.status, Claim.Status.SUBMITTED)

    def test_officer_review_and_handover_through_views(self):
        claim = self.submit()
        self.client.force_login(self.officer)

        self.client.post(
            reverse("claim_review", args=[claim.pk]),
            {"decision": Claim.Status.APPROVED, "comments": "Serial verified"},
        )
        self.refresh(claim)
        self.assertEqual(claim.status, Claim.Status.APPROVED)

        handed_over_at = timezone.localtime() - timedelta(minutes=10)
        self.client.post(
            reverse("claim_handover", args=[claim.pk]),
            {
                "handover_location": "Security office",
                "handed_over_at": handed_over_at.strftime("%Y-%m-%dT%H:%M"),
                "notes": "ID checked",
            },
        )
        self.refresh(claim)
        self.assertEqual(claim.status, Claim.Status.COMPLETED)

    def test_future_handover_time_rejected(self):
        claim = self.submit()
        self.approve(claim)
        self.client.force_login(self.officer)

        response = self.client.post(
            reverse("claim_handover", args=[claim.pk]),
            {
                "handover_location": "Security office",
                "handed_over_at": (
                    timezone.localtime() + timedelta(days=1)
                ).strftime("%Y-%m-%dT%H:%M"),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ItemHandover.objects.exists())

    def test_only_claimant_can_cancel_via_view(self):
        claim = self.submit()
        self.client.force_login(self.rival)

        response = self.client.post(reverse("claim_cancel", args=[claim.pk]))

        self.assertEqual(response.status_code, 404)

    def test_notifications_page_and_mark_read(self):
        self.submit()
        self.client.force_login(self.finder)

        page = self.client.get(reverse("notification_list"))
        self.assertEqual(page.context["unread_notifications"], 1)

        self.client.post(reverse("notifications_mark_read"))
        self.assertFalse(
            self.finder.notifications.filter(is_read=False).exists()
        )

    def test_found_item_detail_shows_claim_button(self):
        self.client.force_login(self.owner)
        url = reverse("found_item_detail", args=[self.found.pk])

        self.assertContains(self.client.get(url), "Claim this item")

        self.submit()
        response = self.client.get(url)
        self.assertNotContains(response, "Claim this item")
        self.assertContains(response, "My claim: Submitted")

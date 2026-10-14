from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from items.matching import match_lost_item
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion
from items.templatetags.lostfinder import claim_steps, match_reasons

from . import services
from .models import Claim, Notification


EVIDENCE = "Serial number C02XK1 and a blue sticker under the lid."


def make_user(name, user_type=UserProfile.UserType.STUDENT):
    user = get_user_model().objects.create_user(name, f"{name}@uni.edu", "pw-12345!")
    UserProfile.objects.create(user=user, onboarding_completed=True, user_type=user_type)
    return user


class PageTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.finder = make_user("finder")
        cls.officer = make_user("officer", UserProfile.UserType.SECURITY)
        cls.category = ItemCategory.objects.create(name="Electronics")

    def setUp(self):
        today = timezone.localdate()
        self.found = FoundItem.objects.create(
            reporter=self.finder, category=self.category, title="Grey MacBook laptop",
            description="Grey laptop, blue sticker on lid", location="Main Library",
            date_found=today,
        )
        self.lost = LostItem.objects.create(
            reporter=self.owner, category=self.category, title="Grey MacBook Pro laptop",
            description="Grey laptop with blue sticker on the lid", location="Main Library",
            date_lost=today,
        )


class TemplateHelperTests(PageTestCase):
    def test_match_reasons_split_into_points(self):
        parts = match_reasons(
            "Both reports have the same category (+30). Item titles are similar (+21)."
        )

        self.assertEqual(parts, [
            {"text": "Both reports have the same category", "points": 30},
            {"text": "Item titles are similar", "points": 21},
        ])
        self.assertEqual(
            match_reasons("No strong similarities were identified."),
            [{"text": "No strong similarities were identified.", "points": None}],
        )
        self.assertEqual(match_reasons(""), [])

    def states(self, claim):
        return [step["state"] for step in claim_steps(claim)]

    def test_claim_steps_follow_the_workflow(self):
        claim = services.submit_claim(self.found, self.owner, EVIDENCE)
        self.assertEqual(self.states(claim), ["current", "upcoming", "upcoming", "upcoming"])

        services.review_claim(claim, self.officer, Claim.Status.UNDER_REVIEW)
        self.assertEqual(self.states(claim), ["done", "current", "upcoming", "upcoming"])

        services.review_claim(claim, self.officer, Claim.Status.APPROVED)
        self.assertEqual(self.states(claim), ["done", "done", "current", "upcoming"])

        services.record_handover(claim, self.officer, "Security office",
                                 timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.states(claim), ["done", "done", "done", "done"])

    def test_ended_claims_stop_where_they_reached(self):
        cancelled = services.submit_claim(self.found, self.owner, EVIDENCE)
        services.cancel_claim(cancelled, self.owner)
        self.assertEqual(self.states(cancelled), ["ended", "upcoming", "upcoming", "upcoming"])

        other = make_user("other")
        rejected = services.submit_claim(self.found, other, EVIDENCE)
        services.review_claim(rejected, self.officer, Claim.Status.UNDER_REVIEW)
        services.review_claim(rejected, self.officer, Claim.Status.REJECTED)
        self.assertEqual(self.states(rejected), ["done", "ended", "upcoming", "upcoming"])


class MatchPageTests(PageTestCase):
    def test_cards_filters_and_counts(self):
        match_lost_item(self.lost)
        self.client.force_login(self.owner)

        response = self.client.get(reverse("match_list"))

        tabs = {value: count for value, _, count in response.context["filter_tabs"]}
        self.assertEqual(tabs, {"active": 1, "pending": 1, "accepted": 0, "rejected": 0, "all": 1})
        self.assertEqual(response.context["awaiting_decision"], 1)
        for text in ("1 waiting for your decision", "lf-score-ring", "Strong match",
                     "Why it matched", "Both reports have the same category",
                     "+30", "This is my item", 'type="submit"'):
            self.assertContains(response, text)

    def test_finder_sees_match_without_actions(self):
        match_lost_item(self.lost)
        self.client.force_login(self.finder)

        response = self.client.get(reverse("match_list"))

        self.assertContains(response, "The owner of the lost report will review this match.")
        self.assertNotContains(response, "This is my item")
        self.assertNotContains(response, "waiting for your decision")


class ClaimPageTests(PageTestCase):
    def test_summary_tracker_and_ready_callout(self):
        claim = services.submit_claim(self.found, self.owner, EVIDENCE)
        services.review_claim(claim, self.officer, Claim.Status.APPROVED)
        self.client.force_login(self.owner)

        response = self.client.get(reverse("claim_list"))

        summary = {label: count for label, _, _, count in response.context["summary"]}
        self.assertEqual(summary["Ready to collect"], 1)
        self.assertEqual(summary["In progress"], 0)
        self.assertContains(response, "Ready to collect")
        self.assertContains(response, "Campus Security Office")
        self.assertContains(response, 'aria-current="step"')
        self.assertContains(response, "lf-steps-track")

    def test_finder_view_hides_claimant(self):
        services.submit_claim(self.found, self.owner, EVIDENCE)
        self.client.force_login(self.finder)

        response = self.client.get(reverse("claim_list"))

        self.assertContains(response, "Claims on items I found")
        self.assertContains(response, self.found.title)
        self.assertNotContains(response, self.owner.email)
        self.assertNotContains(response, EVIDENCE)


class NotificationPageTests(PageTestCase):
    def notify(self, user, title, days_ago=0, read=False):
        n = Notification.objects.create(recipient=user, title=title, message="Details", is_read=read)
        Notification.objects.filter(pk=n.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )
        return n

    def test_grouped_by_day_with_type_icons(self):
        self.notify(self.owner, "Claim approved")
        self.notify(self.owner, "Claim rejected", days_ago=1)
        self.notify(self.owner, "Item returned", days_ago=5, read=True)
        self.client.force_login(self.owner)

        response = self.client.get(reverse("notification_list"))

        labels = [label for label, _ in response.context["groups"]]
        self.assertEqual(labels[:2], ["Today", "Yesterday"])
        self.assertEqual(len(labels), 3)
        for text in ("bi-check2-circle", "bi-x-circle", "bi-bag-check", "is-unread", ">New<"):
            self.assertContains(response, text)
        self.assertContains(response, "You have <strong>2</strong> unread notifications.")

    def test_unread_filter(self):
        self.notify(self.owner, "Claim approved")
        self.notify(self.owner, "Old news", read=True)
        self.client.force_login(self.owner)

        response = self.client.get(reverse("notification_list"), {"show": "unread"})

        titles = [n.title for _, items in response.context["groups"] for n in items]
        self.assertEqual(titles, ["Claim approved"])

    def test_mark_single_notification_read(self):
        mine = self.notify(self.owner, "Claim approved")
        theirs = self.notify(self.finder, "Someone claimed an item you found")
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("notification_mark_read", args=[mine.pk]),
            {"next": reverse("notification_list") + "?show=unread"},
        )
        self.assertRedirects(response, reverse("notification_list") + "?show=unread")
        mine.refresh_from_db()
        self.assertTrue(mine.is_read)
        self.assertIsNotNone(mine.read_at)

        # Someone else's notification is untouched, and outside redirects are ignored.
        response = self.client.post(
            reverse("notification_mark_read", args=[theirs.pk]),
            {"next": "https://evil.example/"},
        )
        self.assertRedirects(response, reverse("notification_list"))
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_read)

    def test_empty_states(self):
        self.client.force_login(self.owner)

        self.assertContains(self.client.get(reverse("notification_list")), "No notifications yet")
        self.assertContains(
            self.client.get(reverse("notification_list"), {"show": "unread"}),
            "No unread notifications",
        )

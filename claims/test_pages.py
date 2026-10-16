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


class ReviewQueuePageTests(PageTestCase):
    def claim_for(self, name, days_ago=0, title=None):
        """A claim by a new user, submitted `days_ago` days ago."""
        item = self.found
        if title:
            item = FoundItem.objects.create(
                reporter=self.finder, category=self.category, title=title,
                description="Something", location="Gym", date_found=timezone.localdate(),
            )
        claim = services.submit_claim(item, make_user(name), EVIDENCE)
        Claim.objects.filter(pk=claim.pk).update(
            submitted_at=timezone.now() - timedelta(days=days_ago)
        )
        claim.refresh_from_db()
        return claim

    def get(self, **params):
        self.client.force_login(self.officer)
        return self.client.get(reverse("review_queue"), params)

    def test_tabs_counts_and_oldest_first(self):
        newer = self.claim_for("newer", days_ago=0)
        older = self.claim_for("older", days_ago=2)
        approved = self.claim_for("winner", days_ago=1, title="Umbrella")
        services.review_claim(approved, self.officer, Claim.Status.APPROVED)

        response = self.get()

        tabs = {value: count for value, _, count in response.context["filter_tabs"]}
        self.assertEqual(tabs, {"active": 2, "approved": 1, "closed": 0, "all": 3})
        self.assertEqual(list(response.context["claims"]), [older, newer])
        for text in ("Claim review queue", "Review claim", "lf-queue-card",
                     "lf-hero-security", "Open dashboard"):
            self.assertContains(response, text)

    def test_waiting_badges_reflect_age(self):
        self.claim_for("fresh", days_ago=0)
        self.claim_for("day2", days_ago=2, title="Umbrella")
        self.claim_for("day4", days_ago=4, title="Scarf")

        claims = self.get().context["claims"]

        self.assertEqual([c.urgency for c in claims], ["overdue", "due", "ok"])

    def test_claimant_match_score_shown(self):
        match_lost_item(self.lost)            # owner's lost report matches self.found
        services.submit_claim(self.found, self.owner, EVIDENCE)

        response = self.get()

        score = MatchSuggestion.objects.get(lost_item=self.lost, found_item=self.found).score
        self.assertEqual(response.context["claims"][0].match_score, score)
        self.assertContains(response, f"{score}% match with their lost report")

    def test_awaiting_handover_tab(self):
        claim = self.claim_for("winner")
        services.review_claim(claim, self.officer, Claim.Status.APPROVED)

        response = self.get(status="approved")

        for text in ("Awaiting handover", "lf-hero-handover", "Before handing an item over",
                     "Record handover", reverse("claim_handover", args=[claim.pk])):
            self.assertContains(response, text)
        self.assertNotContains(response, "Review claim")

    def test_evidence_preview_for_reviewers(self):
        self.claim_for("someone")

        self.assertContains(self.get(), "Serial number C02XK1")

    def test_search_filters_cards_and_counts(self):
        self.claim_for("alice", title="Umbrella")
        self.claim_for("bob", title="Scarf")

        response = self.get(q="umbr")

        self.assertEqual([c.found_item.title for c in response.context["claims"]], ["Umbrella"])
        self.assertEqual(response.context["counts"]["active"], 1)
        self.assertContains(response, "Clear search")

    def test_empty_states(self):
        self.assertContains(self.get(), "The queue is clear")
        self.assertContains(self.get(status="approved"), "Nothing waiting for handover")
        self.assertContains(self.get(q="zzz"), "No claims match")

    def test_header_stats_cover_whole_queue(self):
        self.claim_for("fresh", days_ago=0)
        self.claim_for("stale", days_ago=4, title="Umbrella")
        done = self.claim_for("winner", days_ago=1, title="Scarf")
        services.review_claim(done, self.officer, Claim.Status.APPROVED)
        handed = self.claim_for("collector", days_ago=1, title="Wallet")
        services.review_claim(handed, self.officer, Claim.Status.APPROVED)
        services.record_handover(handed, self.officer, "Security office",
                                 timezone.now() - timedelta(minutes=5))

        response = self.get(q="nothing-matches-this")   # stats ignore the search

        stats = {s["label"]: s for s in response.context["header_stats"]}
        self.assertEqual(stats["To review"]["value"], 2)
        self.assertEqual(stats["Overdue"]["value"], 1)
        self.assertTrue(stats["Overdue"]["alert"])
        self.assertEqual(stats["To hand over"]["value"], 1)
        self.assertEqual(stats["Handed over today"]["value"], 1)
        self.assertEqual(stats["To hand over"]["url"], reverse("review_queue") + "?status=approved")
        self.assertContains(response, "lf-hero-stat is-alert")

    def test_no_overdue_alert_when_queue_is_fresh(self):
        self.claim_for("fresh", days_ago=0)

        stats = {s["label"]: s for s in self.get().context["header_stats"]}

        self.assertEqual(stats["Overdue"]["value"], 0)
        self.assertFalse(stats["Overdue"]["alert"])

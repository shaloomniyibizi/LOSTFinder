from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from .matching import calculate_match, match_found_item, match_lost_item
from .models import FoundItem, ItemCategory, LostItem, MatchSuggestion


def make_user(name):
    user = get_user_model().objects.create_user(
        name, f"{name}@uni.edu", "pw-12345!"
    )
    UserProfile.objects.create(user=user, onboarding_completed=True)
    return user


class MatchingTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.finder = make_user("finder")
        cls.stranger = make_user("stranger")
        cls.electronics = ItemCategory.objects.create(name="Electronics")
        cls.today = timezone.localdate()

    def lost(self, **kwargs):
        defaults = dict(
            reporter=self.owner, category=self.electronics,
            title="Grey MacBook Pro laptop",
            description="Grey laptop with blue sticker on the lid",
            location="Main Library 2nd floor", date_lost=self.today,
        )
        return LostItem.objects.create(**{**defaults, **kwargs})

    def found(self, **kwargs):
        defaults = dict(
            reporter=self.finder, category=self.electronics,
            title="Grey MacBook laptop",
            description="Grey laptop, blue sticker on lid",
            location="Main Library 2nd floor", date_found=self.today,
        )
        return FoundItem.objects.create(**{**defaults, **kwargs})


class MatchingEngineTests(MatchingTestCase):
    def test_similar_reports_score_high(self):
        score, reason = calculate_match(self.lost(), self.found())

        self.assertGreaterEqual(score, 80)
        self.assertIn("same category", reason)

    def test_match_lost_item_creates_suggestion_and_flags_matched(self):
        lost = self.lost()
        found = self.found()

        suggestions = match_lost_item(lost)

        self.assertEqual([s.found_item for s in suggestions], [found])
        lost.refresh_from_db()
        self.assertEqual(lost.status, LostItem.Status.MATCHED)

    def test_match_found_item_matches_open_lost_reports(self):
        lost = self.lost()
        found = self.found()

        suggestions = match_found_item(found)

        self.assertEqual([s.lost_item for s in suggestions], [lost])
        lost.refresh_from_db()
        self.assertEqual(lost.status, LostItem.Status.MATCHED)

    def test_own_reports_are_not_matched(self):
        lost = self.lost()
        self.found(reporter=self.owner)

        self.assertEqual(match_lost_item(lost), [])

    def test_unrelated_items_are_not_suggested(self):
        lost = self.lost()
        clothing = ItemCategory.objects.create(name="Clothing")
        self.found(
            category=clothing, title="Green rain jacket",
            description="Olive hooded coat", location="Gym lockers",
            date_found=self.today - timezone.timedelta(days=30),
        )

        self.assertEqual(match_lost_item(lost), [])
        lost.refresh_from_db()
        self.assertEqual(lost.status, LostItem.Status.OPEN)

    def test_rejected_suggestion_survives_refresh(self):
        lost = self.lost()
        self.found()
        suggestion = match_lost_item(lost)[0]
        suggestion.status = MatchSuggestion.Status.REJECTED
        suggestion.save()

        match_lost_item(lost)

        suggestion.refresh_from_db()
        self.assertEqual(suggestion.status, MatchSuggestion.Status.REJECTED)

    def test_stale_pending_suggestion_removed_when_score_drops(self):
        lost = self.lost()
        found = self.found()
        match_lost_item(lost)

        found.title = "Green rain jacket"
        found.description = "Olive hooded coat"
        found.location = "Gym lockers"
        found.category = ItemCategory.objects.create(name="Clothing")
        found.save()
        match_found_item(found)

        self.assertFalse(MatchSuggestion.objects.exists())
        lost.refresh_from_db()
        self.assertEqual(lost.status, LostItem.Status.OPEN)


class SaveHookTests(MatchingTestCase):
    def form_data(self, date_field):
        return {
            "title": "Grey MacBook laptop",
            "category": self.electronics.pk,
            "description": "Grey laptop, blue sticker on lid",
            "location": "Main Library 2nd floor",
            date_field: self.today.isoformat(),
        }

    def test_creating_found_item_generates_suggestions(self):
        lost = self.lost()
        self.client.force_login(self.finder)

        response = self.client.post(
            reverse("found_item_create"),
            self.form_data("date_found"),
            follow=True,
        )

        self.assertTrue(
            MatchSuggestion.objects.filter(lost_item=lost).exists()
        )
        self.assertContains(response, "1 possible match")

    def test_creating_lost_item_generates_suggestions(self):
        found = self.found()
        self.client.force_login(self.owner)

        self.client.post(
            reverse("lost_item_create"), self.form_data("date_lost")
        )

        self.assertTrue(
            MatchSuggestion.objects.filter(found_item=found).exists()
        )

    def test_deleting_found_item_reopens_lost_item(self):
        lost = self.lost()
        found = self.found()
        match_lost_item(lost)
        self.client.force_login(self.finder)

        self.client.post(reverse("found_item_delete", args=[found.pk]))

        lost.refresh_from_db()
        self.assertEqual(lost.status, LostItem.Status.OPEN)


class MatchPageTests(MatchingTestCase):
    def setUp(self):
        self.lost_item = self.lost()
        self.found_item = self.found()
        self.suggestion = match_lost_item(self.lost_item)[0]

    def test_match_list_shows_both_sides(self):
        self.client.force_login(self.owner)
        owner_page = self.client.get(reverse("match_list"))
        self.assertEqual(list(owner_page.context["for_my_lost"]), [self.suggestion])
        self.assertEqual(list(owner_page.context["for_my_found"]), [])

        self.client.force_login(self.finder)
        finder_page = self.client.get(reverse("match_list"))
        self.assertEqual(list(finder_page.context["for_my_found"]), [self.suggestion])

    def test_strangers_see_nothing(self):
        self.client.force_login(self.stranger)
        page = self.client.get(reverse("match_list"))

        self.assertFalse(page.context["for_my_lost"])
        self.assertFalse(page.context["for_my_found"])

        detail = self.client.get(
            reverse("lost_item_detail", args=[self.lost_item.pk])
        )
        self.assertFalse(detail.context["suggestions"])

    def test_owner_can_accept_and_reject(self):
        self.client.force_login(self.owner)
        url = reverse("match_update", args=[self.suggestion.pk])

        self.client.post(url, {"action": "accept"})
        self.suggestion.refresh_from_db()
        self.assertEqual(self.suggestion.status, MatchSuggestion.Status.ACCEPTED)

        self.client.post(url, {"action": "reject"})
        self.suggestion.refresh_from_db()
        self.assertEqual(self.suggestion.status, MatchSuggestion.Status.REJECTED)
        self.lost_item.refresh_from_db()
        self.assertEqual(self.lost_item.status, LostItem.Status.OPEN)

    def test_finder_cannot_decide(self):
        self.client.force_login(self.finder)
        response = self.client.post(
            reverse("match_update", args=[self.suggestion.pk]),
            {"action": "accept"},
        )

        self.assertEqual(response.status_code, 404)
        self.suggestion.refresh_from_db()
        self.assertEqual(self.suggestion.status, MatchSuggestion.Status.PENDING)

    def test_external_next_url_is_ignored(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("match_update", args=[self.suggestion.pk]),
            {"action": "accept", "next": "https://evil.example/"},
        )

        self.assertRedirects(response, reverse("match_list"))

    def test_detail_page_lists_matches_for_owner(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("lost_item_detail", args=[self.lost_item.pk])
        )

        self.assertContains(response, "This is my item")
        self.assertContains(response, f"{self.suggestion.score}% match")


class ItemPermissionTests(MatchingTestCase):
    def setUp(self):
        self.lost_item = self.lost()
        self.found_item = self.found()

    def edit_payload(self, date_field):
        return {
            "title": "Hijacked title",
            "category": self.electronics.pk,
            "description": "Changed",
            "location": "Elsewhere",
            date_field: self.today.isoformat(),
        }

    def test_non_owner_cannot_edit_or_delete(self):
        self.client.force_login(self.stranger)

        for url_name, pk, date_field in [
            ("lost_item_update", self.lost_item.pk, "date_lost"),
            ("found_item_update", self.found_item.pk, "date_found"),
        ]:
            with self.subTest(url_name):
                url = reverse(url_name, args=[pk])
                self.assertEqual(self.client.get(url).status_code, 404)
                self.assertEqual(
                    self.client.post(url, self.edit_payload(date_field)).status_code,
                    404,
                )

        for url_name, pk in [
            ("lost_item_delete", self.lost_item.pk),
            ("found_item_delete", self.found_item.pk),
        ]:
            with self.subTest(url_name):
                response = self.client.post(reverse(url_name, args=[pk]))
                self.assertEqual(response.status_code, 404)

        self.assertTrue(LostItem.objects.filter(pk=self.lost_item.pk).exists())
        self.assertTrue(FoundItem.objects.filter(pk=self.found_item.pk).exists())
        self.lost_item.refresh_from_db()
        self.assertNotEqual(self.lost_item.title, "Hijacked title")

    def test_owner_edit_keeps_reporter(self):
        self.client.force_login(self.owner)

        self.client.post(
            reverse("lost_item_update", args=[self.lost_item.pk]),
            self.edit_payload("date_lost"),
        )

        self.lost_item.refresh_from_db()
        self.assertEqual(self.lost_item.title, "Hijacked title")
        self.assertEqual(self.lost_item.reporter, self.owner)

    def test_reporter_cannot_be_spoofed_on_create(self):
        self.client.force_login(self.stranger)

        self.client.post(reverse("lost_item_create"), {
            **self.edit_payload("date_lost"),
            "reporter": self.owner.pk,
        })

        self.assertEqual(
            LostItem.objects.get(title="Hijacked title").reporter, self.stranger
        )

    def test_others_see_details_without_manage_buttons(self):
        self.client.force_login(self.stranger)

        response = self.client.get(
            reverse("lost_item_detail", args=[self.lost_item.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Edit report")
        self.assertNotContains(response, "Possible matches")

    def test_future_dates_rejected(self):
        self.client.force_login(self.owner)
        payload = self.edit_payload("date_lost")
        payload["date_lost"] = (self.today + timezone.timedelta(days=2)).isoformat()

        response = self.client.post(reverse("lost_item_create"), payload)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(LostItem.objects.filter(title="Hijacked title").exists())

    def test_found_item_with_claims_cannot_be_deleted(self):
        from claims.models import Claim

        Claim.objects.create(
            found_item=self.found_item, claimant=self.owner,
            evidence_description="Serial number on the bottom",
        )
        self.client.force_login(self.finder)

        self.client.post(reverse("found_item_delete", args=[self.found_item.pk]))

        self.assertTrue(FoundItem.objects.filter(pk=self.found_item.pk).exists())

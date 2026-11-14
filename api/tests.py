from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import UserProfile
from claims.models import Claim, Notification
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion


PASSWORD = "pw-Api-2026!"
EVIDENCE = "Serial number C02XK1 and a blue sticker under the lid."
PROFILE = {
    "phone_number": "078 812 3456",
    "address": "Hall 3",
    "student_id": "S2024-0001",
    "faculty": "Engineering",
    "program": "Computer Science",
    "year_of_study": 2,
    "bio": "Second-year student.",
}


def make_user(name, user_type=UserProfile.UserType.STUDENT, **extra):
    user = get_user_model().objects.create_user(
        name, f"{name}@uni.edu", PASSWORD, **extra
    )
    UserProfile.objects.create(user=user, onboarding_completed=True, user_type=user_type)
    return user


class ApiTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.finder = make_user("finder")
        cls.stranger = make_user("stranger")
        cls.officer = make_user("officer", user_type=UserProfile.UserType.SECURITY)
        cls.category = ItemCategory.objects.create(name="Electronics")

    def login(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def lost_payload(self, **extra):
        return {
            "title": "Grey MacBook Pro laptop",
            "category": self.category.pk,
            "description": "Grey laptop with blue sticker on the lid",
            "location": "Main Library",
            "date_lost": timezone.localdate().isoformat(),
        } | extra

    def make_found(self, **extra):
        return FoundItem.objects.create(**{
            "reporter": self.finder, "category": self.category,
            "title": "Grey MacBook laptop",
            "description": "Grey laptop, blue sticker on lid",
            "location": "Main Library", "date_found": timezone.localdate(),
        } | extra)


class AuthApiTests(ApiTestCase):
    def test_requires_authentication(self):
        response = self.client.get(reverse("api-lost-item-list"))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_login(self):
        response = self.client.post(reverse("api-token"), {
            "email": "OWNER@uni.edu", "password": PASSWORD,
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["user"]["email"], "owner@uni.edu")
        self.assertEqual(
            response.data["token"], Token.objects.get(user=self.owner).key
        )

    def test_token_login_wrong_password(self):
        response = self.client.post(reverse("api-token"), {
            "email": "owner@uni.edu", "password": "nope",
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_register_then_onboard(self):
        response = self.client.post(reverse("api-register"), {
            "email": "New@Uni.edu", "password": "Long-Pass-2026!",
            "password_confirm": "Long-Pass-2026!",
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["user"]["email"], "new@uni.edu")
        self.assertFalse(response.data["user"]["profile"]["onboarding_completed"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {response.data['token']}")

        # The onboarding gate applies to the API too.
        self.assertEqual(self.client.get(reverse("api-lost-item-list")).status_code, 403)

        response = self.client.patch(reverse("api-me"), PROFILE, format="json")
        self.assertEqual(response.status_code, 200)
        profile = response.data["profile"]
        self.assertTrue(profile["onboarding_completed"])
        self.assertEqual(profile["phone_number"], "0788123456")
        self.assertEqual(profile["user_type"], "student")
        self.assertEqual(self.client.get(reverse("api-lost-item-list")).status_code, 200)

    def test_register_rejects_mismatched_passwords_and_duplicate_email(self):
        response = self.client.post(reverse("api-register"), {
            "email": "owner@uni.edu", "password": "Long-Pass-2026!",
            "password_confirm": "Other-Pass-2026!",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
        self.assertIn("password_confirm", response.data)

    def test_profile_validation(self):
        self.login(self.owner)
        response = self.client.patch(reverse("api-me"), {"phone_number": "12"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("phone_number", response.data)

    def test_non_staff_cannot_change_role(self):
        self.login(self.owner)
        self.client.patch(reverse("api-me"), PROFILE | {"user_type": "security"}, format="json")
        self.owner.profile.refresh_from_db()
        self.assertEqual(self.owner.profile.user_type, "student")

    def test_logout_revokes_token(self):
        self.login(self.owner)
        self.assertEqual(self.client.post(reverse("api-logout")).status_code, 204)
        self.assertFalse(Token.objects.filter(user=self.owner).exists())
        self.assertEqual(self.client.get(reverse("api-me")).status_code, 401)


class ItemApiTests(ApiTestCase):
    def test_create_lost_item_runs_matching(self):
        found = self.make_found()
        self.login(self.owner)

        response = self.client.post(
            reverse("api-lost-item-list"), self.lost_payload(), format="json"
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["matches_found"], 1)
        self.assertEqual(response.data["status"], LostItem.Status.MATCHED)
        self.assertTrue(response.data["is_owner"])
        self.assertTrue(MatchSuggestion.objects.filter(
            lost_item_id=response.data["id"], found_item=found,
        ).exists())

    def test_future_date_and_inactive_category_rejected(self):
        retired = ItemCategory.objects.create(name="Retired", is_active=False)
        self.login(self.owner)
        tomorrow = (timezone.localdate() + timezone.timedelta(days=1)).isoformat()

        response = self.client.post(reverse("api-lost-item-list"), self.lost_payload(
            date_lost=tomorrow, category=retired.pk,
        ), format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("date_lost", response.data)
        self.assertIn("category", response.data)

    def test_only_reporter_can_edit_or_delete(self):
        found = self.make_found()
        self.login(self.stranger)
        url = reverse("api-found-item-detail", args=[found.pk])

        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.patch(url, {"title": "x"}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(url).status_code, 403)

        self.login(self.finder)
        response = self.client.patch(url, {"title": "Silver MacBook"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["title"], "Silver MacBook")
        self.assertIn("matches_found", response.data)
        self.assertEqual(self.client.delete(url).status_code, 204)

    def test_status_is_read_only(self):
        found = self.make_found()
        self.login(self.finder)
        self.client.patch(
            reverse("api-found-item-detail", args=[found.pk]),
            {"status": FoundItem.Status.RETURNED}, format="json",
        )
        found.refresh_from_db()
        self.assertEqual(found.status, FoundItem.Status.AVAILABLE)

    def test_deleting_found_item_with_claims_conflicts(self):
        found = self.make_found()
        Claim.objects.create(found_item=found, claimant=self.owner, evidence_description=EVIDENCE)
        self.login(self.finder)

        response = self.client.delete(reverse("api-found-item-detail", args=[found.pk]))

        self.assertEqual(response.status_code, 409)
        self.assertTrue(FoundItem.objects.filter(pk=found.pk).exists())

    def test_list_filters(self):
        self.make_found()
        self.make_found(title="Blue water bottle", description="Steel bottle")
        self.login(self.owner)

        response = self.client.get(reverse("api-found-item-list"), {"q": "bottle"})

        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["title"], "Blue water bottle")
        self.assertTrue(response.data["results"][0]["can_claim"])
        self.assertTrue(response.data["results"][0]["image_url"].startswith("http"))

    def test_reporter_contact_details_are_not_exposed(self):
        self.make_found()
        self.login(self.owner)
        result = self.client.get(reverse("api-found-item-list")).data["results"][0]
        self.assertEqual(set(result["reporter"]), {"id", "name"})

    def test_categories(self):
        ItemCategory.objects.create(name="Retired", is_active=False)
        self.login(self.owner)
        names = [c["name"] for c in self.client.get(reverse("api-category-list")).data]
        self.assertEqual(names, ["Electronics"])


class MatchApiTests(ApiTestCase):
    def setUp(self):
        self.found = self.make_found()
        self.login(self.owner)
        response = self.client.post(
            reverse("api-lost-item-list"), self.lost_payload(), format="json"
        )
        self.lost = LostItem.objects.get(pk=response.data["id"])
        self.match = MatchSuggestion.objects.get(lost_item=self.lost)

    def test_list_and_report_matches(self):
        data = self.client.get(reverse("api-match-list")).data
        self.assertEqual(data["count"], 1)
        self.assertTrue(data["results"][0]["can_decide"])
        self.assertTrue(data["results"][0]["reasons"])

        report_matches = self.client.get(
            reverse("api-lost-item-matches", args=[self.lost.pk])
        ).data
        self.assertEqual(len(report_matches), 1)

        # Other people never see a report's matches.
        self.login(self.stranger)
        self.assertEqual(self.client.get(
            reverse("api-lost-item-matches", args=[self.lost.pk])
        ).data, [])
        self.assertEqual(self.client.get(reverse("api-match-list")).data["count"], 0)

    def test_owner_decides(self):
        url = reverse("api-match-decision", args=[self.match.pk])

        response = self.client.post(url, {"action": "reject"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "rejected")
        self.lost.refresh_from_db()
        self.assertEqual(self.lost.status, LostItem.Status.OPEN)
        self.assertEqual(self.client.post(url, {"action": "maybe"}, format="json").status_code, 400)

    def test_finder_cannot_decide(self):
        self.login(self.finder)
        response = self.client.post(
            reverse("api-match-decision", args=[self.match.pk]), {"action": "accept"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)


class ClaimApiTests(ApiTestCase):
    def setUp(self):
        self.found = self.make_found()

    def submit(self):
        self.login(self.owner)
        return self.client.post(reverse("api-claim-list"), {
            "found_item": self.found.pk, "evidence_description": EVIDENCE,
        }, format="json")

    def test_full_workflow(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        claim_id = response.data["id"]
        self.assertEqual(response.data["status"], "submitted")
        self.assertEqual(response.data["found_item"]["status"], FoundItem.Status.CLAIM_PENDING)
        self.assertTrue(response.data["permissions"]["can_cancel"])

        # The claimant cannot review; reviewers can.
        review_url = reverse("api-claim-review", args=[claim_id])
        self.assertEqual(
            self.client.post(review_url, {"decision": "approved"}, format="json").status_code,
            403,
        )
        self.login(self.officer)
        queue = self.client.get(reverse("api-claim-list"), {"scope": "review"}).data
        self.assertEqual([c["id"] for c in queue["results"]], [claim_id])
        self.assertEqual(queue["results"][0]["evidence_description"], EVIDENCE)

        response = self.client.post(review_url, {"decision": "approved"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "approved")
        self.assertTrue(response.data["permissions"]["can_handover"])

        response = self.client.post(
            reverse("api-claim-handover", args=[claim_id]),
            {"handover_location": "Campus Security Office", "notes": "ID checked"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["handover"]["handover_location"], "Campus Security Office")
        self.assertEqual(
            [step["decision"] for step in response.data["timeline"]],
            ["completed", "approved", "submitted"],
        )
        self.found.refresh_from_db()
        self.assertEqual(self.found.status, FoundItem.Status.RETURNED)

    def test_invalid_transition_is_400(self):
        claim_id = self.submit().data["id"]
        self.login(self.officer)
        response = self.client.post(
            reverse("api-claim-handover", args=[claim_id]),
            {"handover_location": "Office"}, format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("approved claim", response.data["detail"])

    def test_cannot_claim_own_item_or_twice(self):
        self.login(self.finder)
        response = self.client.post(reverse("api-claim-list"), {
            "found_item": self.found.pk, "evidence_description": EVIDENCE,
        }, format="json")
        self.assertEqual(response.status_code, 400)

        self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(self.submit().status_code, 400)

    def test_short_evidence_rejected(self):
        self.login(self.owner)
        response = self.client.post(reverse("api-claim-list"), {
            "found_item": self.found.pk, "evidence_description": "mine",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("evidence_description", response.data)

    def test_visibility(self):
        claim_id = self.submit().data["id"]
        url = reverse("api-claim-detail", args=[claim_id])

        # The finder follows progress but never sees evidence or email.
        self.login(self.finder)
        data = self.client.get(url).data
        self.assertIsNone(data["evidence_description"])
        self.assertIsNone(data["claimant"]["email"])
        self.assertEqual(
            self.client.get(reverse("api-claim-list"), {"scope": "found"}).data["count"], 1
        )

        self.login(self.stranger)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("api-claim-list"), {"scope": "review"}).status_code, 403
        )

    def test_cancel(self):
        claim_id = self.submit().data["id"]
        response = self.client.post(reverse("api-claim-cancel", args=[claim_id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "cancelled")
        self.found.refresh_from_db()
        self.assertEqual(self.found.status, FoundItem.Status.AVAILABLE)


class NotificationAndDashboardApiTests(ApiTestCase):
    def test_notifications(self):
        Notification.objects.create(recipient=self.owner, title="A", message="a")
        Notification.objects.create(recipient=self.owner, title="B", message="b")
        Notification.objects.create(recipient=self.finder, title="C", message="c")
        self.login(self.owner)

        data = self.client.get(reverse("api-notification-list"), {"unread": "true"}).data
        self.assertEqual(data["count"], 2)

        first = data["results"][0]["id"]
        response = self.client.post(reverse("api-notification-read", args=[first]))
        self.assertTrue(response.data["is_read"])

        response = self.client.post(reverse("api-notification-read-all"))
        self.assertEqual(response.data["marked"], 1)
        self.assertFalse(self.owner.notifications.filter(is_read=False).exists())

    def test_cannot_read_someone_elses_notification(self):
        other = Notification.objects.create(recipient=self.finder, title="C", message="c")
        self.login(self.owner)
        response = self.client.post(reverse("api-notification-read", args=[other.pk]))
        self.assertEqual(response.status_code, 404)

    def test_dashboard_by_role(self):
        self.login(self.owner)
        self.assertEqual(self.client.get(reverse("api-dashboard")).data["role"], "member")
        self.login(self.officer)
        data = self.client.get(reverse("api-dashboard")).data
        self.assertEqual(data["role"], "reviewer")
        self.assertIn("claims_to_review", data["values"])


class SchemaTests(APITestCase):
    def test_schema_and_docs(self):
        response = self.client.get(reverse("api-schema"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"/api/v1/claims/", response.content)
        self.assertEqual(self.client.get(reverse("api-docs")).status_code, 200)

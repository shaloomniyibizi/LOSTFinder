from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from items.models import FoundItem, ItemCategory, LostItem

from .decorators import is_reviewer
from .models import UserProfile


PASSWORD = "Campus-Pass-2026!"

ONBOARDING_DATA = {
    "phone_number": "0788123456",
    "address": "Campus residence",
    "student_id": "S12345",
    "faculty": "Engineering",
    "program": "Computer Science",
    "year_of_study": 2,
    "bio": "Second-year student.",
    "user_type": UserProfile.UserType.STUDENT,
}


def make_user(name, onboarded=True, **extra):
    user = get_user_model().objects.create_user(
        name, f"{name}@uni.edu", PASSWORD, **extra
    )
    UserProfile.objects.create(user=user, onboarding_completed=onboarded)
    return user


class OnboardingGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.new_user = make_user("newbie", onboarded=False)
        cls.finder = make_user("finder")
        category = ItemCategory.objects.create(name="Keys")
        today = timezone.localdate()
        cls.lost = LostItem.objects.create(
            reporter=cls.finder, category=category, title="Keys",
            description="Red lanyard", location="Gym", date_lost=today,
        )
        cls.found = FoundItem.objects.create(
            reporter=cls.finder, category=category, title="Keys",
            description="Red lanyard", location="Gym", date_found=today,
        )

    def gated_urls(self):
        return [
            reverse("dashboard"),
            reverse("lost_item_list"),
            reverse("found_item_list"),
            reverse("lost_item_create"),
            reverse("found_item_create"),
            reverse("lost_item_detail", args=[self.lost.pk]),
            reverse("found_item_detail", args=[self.found.pk]),
            reverse("match_list"),
            reverse("claim_list"),
            reverse("claim_create", args=[self.found.pk]),
            reverse("review_queue"),
        ]

    def test_incomplete_profile_is_sent_to_onboarding(self):
        self.client.force_login(self.new_user)

        for url in self.gated_urls():
            with self.subTest(url=url):
                self.assertRedirects(
                    self.client.get(url), reverse("onboarding"),
                    fetch_redirect_response=False,
                )

    def test_anonymous_users_are_sent_to_login(self):
        for url in self.gated_urls():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(
                    response["Location"].startswith(reverse("login"))
                )

    def test_missing_profile_is_created_and_gated(self):
        user = get_user_model().objects.create_user(
            "noprofile", "noprofile@uni.edu", PASSWORD
        )
        self.client.force_login(user)

        response = self.client.get(reverse("lost_item_list"))

        self.assertRedirects(response, reverse("onboarding"))
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_completed_profile_passes_the_gate(self):
        self.client.force_login(self.finder)

        self.assertEqual(self.client.get(reverse("lost_item_list")).status_code, 200)

    def test_home_page_is_for_visitors_only(self):
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

        # Signed-in users go to the dashboard, which still applies the
        # onboarding gate for incomplete profiles.
        self.client.force_login(self.new_user)
        self.assertRedirects(
            self.client.get(reverse("home")), reverse("dashboard"),
            target_status_code=302,
        )

        self.client.force_login(self.finder)
        self.assertRedirects(self.client.get(reverse("home")), reverse("dashboard"))

    def test_completing_onboarding_opens_the_app(self):
        self.client.force_login(self.new_user)

        response = self.client.post(reverse("onboarding"), ONBOARDING_DATA)

        self.assertRedirects(response, reverse("dashboard"))
        self.new_user.profile.refresh_from_db()
        self.assertTrue(self.new_user.profile.onboarding_completed)
        self.assertEqual(self.client.get(reverse("lost_item_list")).status_code, 200)

    def test_onboarding_requires_fields(self):
        self.client.force_login(self.new_user)

        response = self.client.post(reverse("onboarding"), {})

        self.assertEqual(response.status_code, 200)
        self.new_user.profile.refresh_from_db()
        self.assertFalse(self.new_user.profile.onboarding_completed)


class RoleTests(TestCase):
    def test_students_cannot_self_promote_during_onboarding(self):
        user = make_user("sneaky", onboarded=False)
        self.client.force_login(user)

        self.client.post(reverse("onboarding"), {
            **ONBOARDING_DATA,
            "user_type": UserProfile.UserType.SECURITY,
        })

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.user_type, UserProfile.UserType.STUDENT)
        self.assertFalse(is_reviewer(user))

    def test_reviewer_roles(self):
        student = make_user("student")
        staff = make_user("staffer", is_staff=True)
        officer = make_user("officer")
        officer.profile.user_type = UserProfile.UserType.SECURITY
        officer.profile.save()

        self.assertFalse(is_reviewer(student))
        self.assertTrue(is_reviewer(staff))
        self.assertTrue(is_reviewer(officer))


class AuthFlowTests(TestCase):
    def test_register_logs_in_and_starts_onboarding(self):
        response = self.client.post(reverse("register"), {
            "email": "Fresh@Uni.edu",
            "password1": PASSWORD,
            "password2": PASSWORD,
        })

        self.assertRedirects(response, reverse("onboarding"))
        user = get_user_model().objects.get(email="fresh@uni.edu")
        self.assertFalse(user.profile.onboarding_completed)

    def test_duplicate_email_rejected(self):
        make_user("taken")

        response = self.client.post(reverse("register"), {
            "email": "TAKEN@uni.edu",
            "password1": PASSWORD,
            "password2": PASSWORD,
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_login_by_email_routes_by_onboarding_state(self):
        make_user("pending", onboarded=False)
        make_user("ready")

        pending = self.client.post(
            reverse("login"),
            {"email": "PENDING@uni.edu", "password": PASSWORD},
        )
        self.assertRedirects(pending, reverse("onboarding"))

        self.client.logout()
        ready = self.client.post(
            reverse("login"), {"email": "ready@uni.edu", "password": PASSWORD}
        )
        self.assertRedirects(ready, reverse("dashboard"))

    def test_wrong_password_rejected(self):
        make_user("someone")

        response = self.client.post(
            reverse("login"), {"email": "someone@uni.edu", "password": "nope"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

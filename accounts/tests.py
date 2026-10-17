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
        self.assertContains(response, "Invalid email address or password.")

    def test_login_honours_safe_next_only(self):
        make_user("ready")
        target = reverse("lost_item_create")

        response = self.client.post(reverse("login"), {
            "email": "ready@uni.edu", "password": PASSWORD, "next": target,
        })
        self.assertRedirects(response, target)

        self.client.logout()
        response = self.client.post(reverse("login"), {
            "email": "ready@uni.edu", "password": PASSWORD,
            "next": "https://evil.example/steal",
        })
        self.assertRedirects(response, reverse("dashboard"))

    def test_onboarding_wins_over_next(self):
        make_user("pending", onboarded=False)

        response = self.client.post(reverse("login"), {
            "email": "pending@uni.edu", "password": PASSWORD,
            "next": reverse("lost_item_list"),
        })

        self.assertRedirects(response, reverse("onboarding"))

    def test_login_page_keeps_next_from_redirect(self):
        protected = reverse("lost_item_create")
        response = self.client.get(protected, follow=True)

        self.assertContains(response, f'name="next" value="{protected}"')


AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class AuthModalTests(TestCase):
    """The sign-in/register modals submit in the background and get JSON."""

    def test_modals_on_public_pages_for_visitors(self):
        for name in ("home", "login", "register"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'id="loginModal"')
                self.assertContains(response, 'id="registerModal"')
                self.assertContains(response, "/static/js/auth-modals.js")
                self.assertContains(response, 'data-bs-target="#loginModal"')

    def test_no_modals_once_signed_in(self):
        self.client.force_login(make_user("pending", onboarded=False))

        response = self.client.get(reverse("onboarding"))

        self.assertNotContains(response, 'id="loginModal"')
        self.assertNotContains(response, "auth-modals.js")

    def test_home_protected_links_open_the_modal(self):
        html = self.client.get(reverse("home")).content.decode()

        self.assertIn(f'data-auth-required class="btn btn-warning" href="{reverse("lost_item_create")}"', html)
        self.assertIn('role="search" data-auth-required', html)

    def test_modal_login_success_returns_redirect(self):
        make_user("ready")

        response = self.client.post(reverse("login"), {
            "email": "ready@uni.edu", "password": PASSWORD,
            "next": reverse("match_list"),
        }, **AJAX)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"redirect": reverse("match_list")})
        self.assertIn("_auth_user_id", self.client.session)

    def test_modal_login_failure_returns_form_with_error(self):
        make_user("ready")

        response = self.client.post(reverse("login"), {
            "email": "ready@uni.edu", "password": "wrong", "next": "/items/lost/",
        }, **AJAX)

        self.assertEqual(response.status_code, 400)
        html = response.json()["html"]
        self.assertIn("Invalid email address or password.", html)
        self.assertIn('value="ready@uni.edu"', html)       # email kept
        self.assertIn('value="/items/lost/"', html)         # next kept
        self.assertIn("data-auth-form", html)               # still a modal form
        self.assertIn('id="modal-login-email"', html)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_modal_register_success_goes_to_onboarding(self):
        response = self.client.post(reverse("register"), {
            "email": "new@uni.edu", "password1": PASSWORD, "password2": PASSWORD,
        }, **AJAX)

        self.assertEqual(response.json(), {"redirect": reverse("onboarding")})
        self.assertTrue(get_user_model().objects.filter(email="new@uni.edu").exists())

    def test_modal_register_errors_render_in_place(self):
        make_user("taken")

        response = self.client.post(reverse("register"), {
            "email": "taken@uni.edu", "password1": PASSWORD, "password2": "different",
        }, **AJAX)

        self.assertEqual(response.status_code, 400)
        html = response.json()["html"]
        self.assertIn("An account with that email already exists.", html)
        self.assertIn("is-invalid", html)
        self.assertIn('id="modal-register-email"', html)
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_weak_password_error_shown(self):
        response = self.client.post(reverse("register"), {
            "email": "weak@uni.edu", "password1": "password", "password2": "password",
        }, **AJAX)

        self.assertEqual(response.status_code, 400)
        self.assertIn("too common", response.json()["html"])


class OnboardingFormTests(TestCase):
    def test_page_renders_sections_with_icons(self):
        self.client.force_login(make_user("newbie", onboarded=False))

        response = self.client.get(reverse("onboarding"))

        for text in ("Contact details", "Academic details", "About you",
                     "bi-telephone", "bi-person-vcard", "bi-mortarboard",
                     'aria-current="step"', "Upload photo", "profile-form.js"):
            self.assertContains(response, text)

    def test_role_field_only_for_staff(self):
        self.client.force_login(make_user("student", onboarded=False))
        self.assertNotContains(self.client.get(reverse("onboarding")), 'name="user_type"')

        self.client.force_login(make_user("boss", onboarded=False, is_staff=True))
        self.assertContains(self.client.get(reverse("onboarding")), 'name="user_type"')

    def test_staff_can_set_their_role(self):
        staff = make_user("boss", onboarded=False, is_staff=True)
        self.client.force_login(staff)

        self.client.post(reverse("onboarding"), {
            **ONBOARDING_DATA, "user_type": UserProfile.UserType.SECURITY,
        })

        staff.profile.refresh_from_db()
        self.assertEqual(staff.profile.user_type, UserProfile.UserType.SECURITY)

    def test_phone_number_is_normalised_and_validated(self):
        user = make_user("newbie", onboarded=False)
        self.client.force_login(user)

        bad = self.client.post(reverse("onboarding"), {
            **ONBOARDING_DATA, "phone_number": "+250 788",
        })
        self.assertContains(bad, "Enter a 10-digit phone number")
        self.assertContains(bad, "lf-field-invalid")

        self.client.post(reverse("onboarding"), {
            **ONBOARDING_DATA, "phone_number": "078 812 3456",
        })
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.phone_number, "0788123456")
        self.assertTrue(user.profile.onboarding_completed)

    def test_required_errors_shown_per_field(self):
        self.client.force_login(make_user("newbie", onboarded=False))

        response = self.client.post(reverse("onboarding"), {})

        self.assertContains(response, "This field is required.", count=7)

    def test_profile_page_uses_same_layout(self):
        self.client.force_login(make_user("ready"))

        response = self.client.get(reverse("profile"))

        self.assertContains(response, "Academic details")
        self.assertContains(response, "bi-telephone")
        self.assertNotContains(response, 'name="user_type"')

    def test_profile_edits_are_saved_and_keep_the_role(self):
        officer = make_user("officer")
        officer.profile.user_type = UserProfile.UserType.SECURITY
        officer.profile.save()
        self.client.force_login(officer)

        # ONBOARDING_DATA posts user_type=student; non-staff cannot change it.
        response = self.client.post(reverse("profile"), {
            **ONBOARDING_DATA, "phone_number": "0799000111", "faculty": "Business",
        })

        self.assertRedirects(response, reverse("profile"))
        officer.profile.refresh_from_db()
        self.assertEqual(officer.profile.phone_number, "0799000111")
        self.assertEqual(officer.profile.faculty, "Business")
        self.assertEqual(officer.profile.user_type, UserProfile.UserType.SECURITY)

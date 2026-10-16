from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from claims.models import Claim, Notification
from items.models import FoundItem, ItemCategory, LostItem


class AdminLteSkinTests(TestCase):
    """The Django admin renders inside the app's AdminLTE layout."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_user = User.objects.create_superuser("boss", "boss@uni.edu", "pw-12345!")
        UserProfile.objects.create(user=cls.admin_user, onboarding_completed=True)
        student = User.objects.create_user("student", "student@uni.edu", "pw-12345!")
        category = ItemCategory.objects.create(name="Electronics")
        today = timezone.localdate()
        cls.found = FoundItem.objects.create(
            reporter=student, category=category, title="Laptop",
            description="Grey", location="Library", date_found=today,
        )
        LostItem.objects.create(
            reporter=student, category=category, title="Phone",
            description="Black", location="Gym", date_lost=today,
        )
        Claim.objects.create(found_item=cls.found, claimant=cls.admin_user,
                             evidence_description="Serial number on base")
        Notification.objects.create(recipient=cls.admin_user, title="Hi", message="Hello")

    def setUp(self):
        self.client.force_login(self.admin_user)

    def test_index_uses_adminlte_shell(self):
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        for text in ("vendor/adminlte/css/adminlte.min.css", "css/admin.css",
                     'class="app-wrapper"', 'class="app-header', 'class="app-sidebar',
                     "LOSTFinder administration", "Back to LOSTFinder",
                     'data-bs-theme-value="dark"',
                     "bi-clipboard-check", "Lost Items"):
            self.assertContains(response, text)
        # Django's own sidebar and theme toggle are replaced by the app's.
        self.assertNotContains(response, "admin/js/theme.js")
        self.assertNotContains(response, 'id="nav-sidebar"')
        self.assertNotContains(response, 'class="theme-toggle"')

    def test_every_model_page_renders_in_shell(self):
        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            urls = [
                reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist"),
                reverse(f"admin:{opts.app_label}_{opts.model_name}_add"),
            ]
            obj = model.objects.first()
            if obj is not None:
                for view in ("change", "delete", "history"):
                    urls.append(reverse(
                        f"admin:{opts.app_label}_{opts.model_name}_{view}", args=[obj.pk]
                    ))
            for url in urls:
                with self.subTest(url=url):
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'class="app-sidebar')
                    self.assertContains(response, 'id="content"')

    def test_sidebar_marks_current_model(self):
        response = self.client.get(reverse("admin:claims_claim_changelist"))

        html = response.content.decode()
        claims_link = html.index(reverse("admin:claims_claim_changelist") + '"')
        self.assertIn("active", html[claims_link:claims_link + 120])
        self.assertContains(response, 'aria-current="page"')
        # Django's breadcrumbs sit in the AdminLTE content header.
        self.assertContains(response, 'class="lf-admin-crumbs"')
        self.assertContains(response, '<ol class="breadcrumbs">')

    def test_messages_render_as_bootstrap_alerts(self):
        response = self.client.post(
            reverse("admin:items_itemcategory_add"), {"name": "Keys", "is_active": "on"},
            follow=True,
        )

        self.assertContains(response, "alert alert-success")
        self.assertNotContains(response, 'class="messagelist"')

    def test_popup_has_no_shell(self):
        response = self.client.get(reverse("admin:items_itemcategory_add") + "?_popup=1")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "lf-admin-popup")
        self.assertNotContains(response, 'class="app-sidebar')
        self.assertNotContains(response, 'class="app-header')

    def test_login_page_uses_slim_layout(self):
        self.client.logout()

        response = self.client.get(reverse("admin:login"))

        self.assertEqual(response.status_code, 200)
        for text in ("lf-admin-guest", 'class="app-header', "vendor/adminlte/css/adminlte.min.css",
                     'data-bs-theme-value="light"', 'name="username"', "Admin sign in"):
            self.assertContains(response, text)
        self.assertNotContains(response, 'class="app-sidebar')

    def test_admin_login_still_works(self):
        self.client.logout()

        response = self.client.post(
            reverse("admin:login"), {"username": "boss", "password": "pw-12345!",
                                     "next": reverse("admin:index")},
        )

        self.assertRedirects(response, reverse("admin:index"))

    def test_non_staff_are_sent_to_admin_login(self):
        self.client.logout()
        self.client.force_login(get_user_model().objects.get(username="student"))

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

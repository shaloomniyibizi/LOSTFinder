from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from .cards import report_card
from .models import FoundItem, ItemCategory, LostItem


def make_user(name):
    user = get_user_model().objects.create_user(name, f"{name}@uni.edu", "pw-12345!")
    UserProfile.objects.create(user=user, onboarding_completed=True)
    return user


class ItemListPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.me = make_user("me")
        cls.other = make_user("other")
        cls.keys = ItemCategory.objects.create(name="Keys")
        cls.tech = ItemCategory.objects.create(name="Electronics")
        today = timezone.localdate()

        def found(title, category, status=FoundItem.Status.AVAILABLE, reporter=None):
            return FoundItem.objects.create(
                reporter=reporter or cls.other, category=category, title=title,
                description=f"{title} description", location="Library",
                date_found=today, status=status,
            )

        cls.umbrella = found("Umbrella", cls.keys)
        cls.laptop = found("Laptop", cls.tech)
        cls.phone = found("Phone", cls.tech, status=FoundItem.Status.RETURNED)
        cls.mine = found("Water bottle", cls.keys, reporter=cls.me)

    def setUp(self):
        self.client.force_login(self.me)

    def get(self, **params):
        return self.client.get(reverse("found_item_list"), params)

    def test_uses_shared_report_card(self):
        response = self.get()

        self.assertTemplateUsed(response, "items/_report_card.html")
        self.assertContains(response, "lf-report-card", count=4)
        self.assertContains(response, "lf-form-hero-found")
        self.assertContains(response, "Turn in found item")

    def test_card_buttons_depend_on_viewer_and_status(self):
        html = self.get().content.decode()

        self.assertIn("Your report &middot; manage", html)          # my item
        self.assertEqual(html.count("Initiate Claim Verification"), 2)  # 2 available, not mine
        self.assertIn("View details", html)                         # returned phone
        self.assertNotIn("data-auth-required", html)

    def test_status_tabs_show_counts_within_filters(self):
        response = self.get(category=self.tech.pk)

        tabs = {label: count for _, label, count in response.context["status_tabs"]}
        self.assertEqual(tabs["All"], 2)
        self.assertEqual(tabs["Available"], 1)
        self.assertEqual(tabs["Returned to owner"], 1)

    def test_filter_chips_and_clear_links_keep_other_filters(self):
        html = self.get(q="lap", category=self.tech.pk, status="available").content.decode()

        self.assertIn("“lap”", html)
        self.assertIn("Electronics", html)
        # Removing the search keeps the category and status.
        self.assertIn(f'href="?category={self.tech.pk}&amp;status=available"', html)
        self.assertIn("Clear all", html)

    def test_tabs_keep_search_and_drop_page(self):
        html = self.get(q="a", page=1).content.decode()

        self.assertIn('href="?q=a&amp;status=returned"', html)

    def test_pagination_keeps_filters(self):
        for n in range(13):
            FoundItem.objects.create(
                reporter=self.other, category=self.keys, title=f"Key {n}",
                description="Brass key", location="Gym",
                date_found=timezone.localdate(),
            )

        response = self.get(category=self.keys.pk)

        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        self.assertContains(response, f'href="?category={self.keys.pk}&amp;page=2"')
        self.assertContains(response, "Showing <strong>1&ndash;12</strong>")

    def test_empty_states(self):
        self.assertContains(self.get(q="zzz-nothing"), "No found items match your filters")

        LostItem.objects.all().delete()
        response = self.client.get(reverse("lost_item_list"))
        self.assertContains(response, "No lost items yet")
        self.assertContains(response, "lf-form-hero-lost")

    def test_placeholder_image_is_stable_per_item(self):
        first = report_card(self.umbrella, "found")["image_url"]
        again = report_card(FoundItem.objects.get(pk=self.umbrella.pk), "found")["image_url"]

        self.assertEqual(first, again)
        self.assertIn("/static/image/item_", first)

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserProfile
from claims import services as claim_services
from claims.models import Claim, ItemHandover
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion


class HomePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.owner = User.objects.create_user("owner", "owner@uni.edu", "pw")
        cls.finder = User.objects.create_user("finder", "finder@uni.edu", "pw")
        cls.category = ItemCategory.objects.create(name="Electronics")
        today = timezone.localdate()

        LostItem.objects.create(
            reporter=cls.owner, category=cls.category, title="Grey MacBook",
            description="Sticker on lid", location="Main Library",
            date_lost=today, status=LostItem.Status.RETURNED,
        )
        LostItem.objects.create(
            reporter=cls.owner, category=cls.category, title="AirPods case",
            description="Blue silicone", location="Main Library",
            date_lost=today,
        )
        cls.found = FoundItem.objects.create(
            reporter=cls.finder, category=cls.category, title="Laptop",
            description="Grey laptop", location="Cafeteria",
            date_found=today,
        )

        claim = Claim.objects.create(
            found_item=cls.found, claimant=cls.owner,
            evidence_description="Serial number", status=Claim.Status.APPROVED,
        )
        ItemHandover.objects.create(
            claim=claim, handed_over_by=cls.finder, received_by=cls.owner,
            handover_location="Security office",
            handed_over_at=claim.submitted_at + timedelta(hours=3),
        )

    def test_home_is_public_and_shows_reports(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["reports"]), 3)
        self.assertContains(response, "Grey MacBook")

    def test_stats(self):
        stats = self.client.get(reverse("home")).context["stats"]

        self.assertEqual(stats["total_reports"], 3)
        self.assertEqual(stats["recovered"], 1)
        self.assertEqual(stats["in_custody"], 1)
        self.assertEqual(stats["return_rate"], 50)
        self.assertAlmostEqual(stats["avg_claim_hours"], 3.0, places=1)

    def test_zones_rank_busiest_location_first(self):
        zones = self.client.get(reverse("home")).context["zones"]

        self.assertEqual(zones[0], {"name": "Main Library", "count": 2})

    def test_feed_filters(self):
        lost = self.client.get(reverse("home"), {"feed": "lost"})
        self.assertTrue(all(r["kind"] == "lost" for r in lost.context["reports"]))

        available = self.client.get(reverse("home"), {"feed": "available"})
        self.assertEqual(len(available.context["reports"]), 1)

        bogus = self.client.get(reverse("home"), {"feed": "nope"})
        self.assertEqual(bogus.context["feed"], "all")

    def test_items_without_image_use_static_fallback(self):
        reports = self.client.get(reverse("home")).context["reports"]

        self.assertTrue(
            all("/static/image/item_" in r["image_url"] for r in reports)
        )


VENDOR_ASSETS = [
    "vendor/adminlte/css/adminlte.min.css",
    "vendor/adminlte/js/adminlte.min.js",
    "vendor/bootstrap/js/bootstrap.bundle.min.js",
    "vendor/bootstrap-icons/bootstrap-icons.min.css",
    "vendor/bootstrap-icons/fonts/bootstrap-icons.woff2",
    "vendor/chartjs/chart.umd.min.js",
    "css/app.css",
    "js/dashboard.js",
]


def make_member(name, user_type=UserProfile.UserType.STUDENT, **extra):
    user = get_user_model().objects.create_user(
        name, f"{name}@uni.edu", "pw-12345!", **extra
    )
    UserProfile.objects.create(
        user=user, onboarding_completed=True, user_type=user_type
    )
    return user


class DashboardTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = make_member("student")
        cls.finder = make_member("finder")
        cls.officer = make_member(
            "officer", user_type=UserProfile.UserType.SECURITY
        )
        cls.admin = make_member("admin", is_staff=True)
        cls.category = ItemCategory.objects.create(name="Electronics")

    def metrics(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse("dashboard_metrics"))
        self.assertEqual(response.status_code, 200)
        return response.json()

    def lost_item(self, **kwargs):
        return LostItem.objects.create(**{
            "reporter": self.student, "category": self.category,
            "title": "Grey MacBook laptop", "description": "Blue sticker on lid",
            "location": "Main Library", "date_lost": timezone.localdate(),
            **kwargs,
        })

    def found_item(self, **kwargs):
        return FoundItem.objects.create(**{
            "reporter": self.finder, "category": self.category,
            "title": "Grey MacBook laptop", "description": "Blue sticker on lid",
            "location": "Main Library", "date_found": timezone.localdate(),
            **kwargs,
        })


class StaticAssetTests(DashboardTestCase):
    def test_vendor_assets_exist_and_are_referenced(self):
        for asset in VENDOR_ASSETS:
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset), asset)

        self.client.force_login(self.student)
        html = self.client.get(reverse("dashboard")).content.decode()
        for asset in VENDOR_ASSETS:
            if asset.endswith((".css", ".js")):
                self.assertIn(f"/static/{asset}", html)

    def test_public_pages_use_adminlte_shell(self):
        for name in ("home", "login", "register"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, "/static/vendor/adminlte/css/adminlte.min.css")
                self.assertContains(response, 'class="app-wrapper"')
                self.assertContains(response, 'class="app-header')
                # Visitors get the top-nav shell, not the signed-in sidebar.
                self.assertNotContains(response, 'class="app-sidebar')
                self.assertNotContains(response, "cdn.jsdelivr.net")

    def test_theme_toggle_on_every_layout(self):
        pages = [("home", None), ("login", None), ("dashboard", self.student),
                 ("lost_item_list", self.student)]

        for name, user in pages:
            with self.subTest(page=name):
                if user:
                    self.client.force_login(user)
                else:
                    self.client.logout()
                html = self.client.get(reverse(name)).content.decode()

                for mode in ("light", "dark", "auto"):
                    self.assertIn(f'data-bs-theme-value="{mode}"', html)
                    self.assertIn(f'data-lte-theme-icon="{mode}"', html)
                # The saved theme is applied in <head>, before first paint.
                head = html.split("</head>")[0]
                self.assertIn('localStorage.getItem("lte-theme")', head)
                # Template comments must never leak into the page.
                self.assertNotIn("{#", html)
                self.assertNotIn("#}", html)

    def test_signed_in_users_are_sent_from_home_to_dashboard(self):
        self.client.force_login(self.student)

        response = self.client.get(reverse("home"), {"feed": "lost"})

        self.assertRedirects(response, reverse("dashboard"))

    def test_no_cdn_dependencies_on_app_pages(self):
        self.client.force_login(self.student)
        for name in ("dashboard", "lost_item_list", "match_list", "claim_list"):
            html = self.client.get(reverse(name)).content.decode()
            self.assertNotIn("cdn.jsdelivr.net", html, name)

    def test_shared_layout_on_app_pages(self):
        self.client.force_login(self.student)
        for name in ("dashboard", "lost_item_list", "found_item_list",
                     "match_list", "claim_list", "notification_list", "profile"):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, 'class="app-sidebar')
                self.assertContains(response, 'class="app-header')


class RoleDashboardTests(DashboardTestCase):
    def test_gating(self):
        response = self.client.get(reverse("dashboard"))
        self.assertTrue(response["Location"].startswith(reverse("login")))

        pending = get_user_model().objects.create_user("new", "new@uni.edu", "pw")
        UserProfile.objects.create(user=pending)
        self.client.force_login(pending)
        self.assertRedirects(
            self.client.get(reverse("dashboard_metrics")), reverse("onboarding")
        )

    def test_member_dashboard(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["dash"]["role"], "member")
        self.assertContains(response, "My Dashboard")
        self.assertContains(response, "Matches awaiting your decision")
        self.assertNotContains(response, "Claim queue")
        self.assertNotContains(response, "SECURITY DESK")
        self.assertNotContains(response, "ADMINISTRATION")

    def test_security_officer_dashboard(self):
        self.client.force_login(self.officer)
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.context["dash"]["role"], "reviewer")
        self.assertContains(response, "Security Desk Dashboard")
        self.assertContains(response, "Claim queue")
        self.assertContains(response, "SECURITY DESK")
        self.assertNotContains(response, "ADMINISTRATION")
        self.assertNotIn("users", self.metrics(self.officer)["values"])

    def test_admin_dashboard_adds_user_stats(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "ADMINISTRATION")
        self.assertEqual(self.metrics(self.admin)["values"]["users"], 4)

    def test_claim_queue_lists_oldest_first(self):
        first = self.found_item(title="Umbrella")
        second = self.found_item(title="Wallet")
        older = claim_services.submit_claim(first, self.student, "Black, wooden handle")
        claim_services.submit_claim(second, self.student, "Brown leather, 3 cards")

        self.client.force_login(self.officer)
        queue = self.client.get(reverse("dashboard")).context["dash"]["tables"]["claim_queue"]

        self.assertEqual(queue[0], older)


class LiveMetricsTests(DashboardTestCase):
    """Checkpoint: dashboard numbers follow the database."""

    def test_member_metrics_follow_records(self):
        before = self.metrics(self.student)["values"]
        self.assertEqual(before["my_open_lost"], 0)
        self.assertEqual(before["pending_matches"], 0)

        lost = self.lost_item()
        found = self.found_item()
        MatchSuggestion.objects.create(lost_item=lost, found_item=found, score=80)

        after = self.metrics(self.student)["values"]
        self.assertEqual(after["my_open_lost"], 1)
        self.assertEqual(after["pending_matches"], 1)
        self.assertEqual(after["campus_custody"], 1)

        claim_services.submit_claim(found, self.student, "Serial number C02XK1 on base")
        self.assertEqual(self.metrics(self.student)["values"]["my_active_claims"], 1)

    def test_reviewer_metrics_follow_claim_workflow(self):
        found = self.found_item()
        self.assertEqual(self.metrics(self.officer)["values"]["claims_to_review"], 0)

        claim = claim_services.submit_claim(found, self.student, "Serial number C02XK1 on base")
        values = self.metrics(self.officer)["values"]
        self.assertEqual(values["claims_to_review"], 1)
        self.assertEqual(values["in_custody"], 1)

        claim_services.review_claim(claim, self.officer, Claim.Status.APPROVED)
        values = self.metrics(self.officer)["values"]
        self.assertEqual(values["claims_to_review"], 0)
        self.assertEqual(values["awaiting_handover"], 1)

        claim_services.record_handover(
            claim, self.officer, "Security office",
            timezone.now() - timedelta(minutes=1),
        )
        values = self.metrics(self.officer)["values"]
        self.assertEqual(values["awaiting_handover"], 0)
        self.assertEqual(values["returned_30d"], 1)
        self.assertEqual(values["in_custody"], 0)

    def test_charts_follow_records(self):
        charts = self.metrics(self.officer)["charts"]
        self.assertEqual(sum(charts["activity"]["lost"]), 0)
        self.assertEqual(charts["categories"]["labels"], [])

        self.lost_item()
        self.lost_item()
        self.found_item()

        charts = self.metrics(self.officer)["charts"]
        self.assertEqual(charts["activity"]["lost"][-1], 2)   # today
        self.assertEqual(charts["activity"]["found"][-1], 1)
        self.assertEqual(len(charts["activity"]["labels"]), 14)
        self.assertEqual(
            charts["categories"], {"labels": ["Electronics"], "values": [3]}
        )

    def test_rendered_page_matches_json(self):
        self.lost_item()
        self.client.force_login(self.student)

        page = self.client.get(reverse("dashboard"))
        values = self.metrics(self.student)["values"]

        self.assertContains(
            page,
            f'<div class="lf-kpi-value" data-metric="my_open_lost">{values["my_open_lost"]}</div>',
            html=True,
        )
        self.assertContains(page, 'id="dashboard-metrics"')

    def test_week_trend_follows_records(self):
        values = self.metrics(self.student)["values"]
        self.assertEqual(values["reports_7d"], 0)
        self.assertEqual(values["reports_7d_trend"], "Same as previous 7 days")

        self.lost_item()
        self.found_item()
        # One report 10 days ago falls in the previous week.
        old = self.lost_item(title="Old umbrella")
        LostItem.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )

        values = self.metrics(self.student)["values"]
        self.assertEqual(values["reports_7d"], 2)
        self.assertEqual(values["reports_7d_trend"], "+1 vs previous 7 days")


class DashboardLayoutTests(DashboardTestCase):
    def test_member_layout(self):
        self.student.first_name = "Amina"
        self.student.save()
        self.client.force_login(self.student)

        response = self.client.get(reverse("dashboard"))

        self.assertRegex(response.content.decode(), r"Good (morning|afternoon|evening), Amina")
        for text in ("Report lost item", "Turn in found item", "At a glance",
                     "Matches awaiting your decision", "My recent reports",
                     "Your recent notifications", 'data-bs-toggle="tab"',
                     'data-metric="reports_7d"'):
            self.assertContains(response, text)
        self.assertNotContains(response, "Review queue</a>")

    def test_reviewer_layout(self):
        self.client.force_login(self.officer)

        response = self.client.get(reverse("dashboard"))

        for text in ("Security Officer", "Recent claim decisions", "Claim queue",
                     "Awaiting handover", "Recent reports", "Open the full review queue"):
            self.assertContains(response, text)
        self.assertRegex(response.content.decode(), r"Good \w+, officer")

    def test_activity_feed_shows_claim_decisions_for_reviewers(self):
        claim = claim_services.submit_claim(
            self.found_item(), self.student, "Serial number C02XK1 on base"
        )
        claim_services.review_claim(claim, self.officer, Claim.Status.APPROVED)
        self.client.force_login(self.officer)

        feed = self.client.get(reverse("dashboard")).context["dash"]["activity_feed"]

        self.assertEqual(feed[0]["title"], f"Claim #{claim.pk} approved")
        self.assertEqual(feed[1]["title"], f"Claim #{claim.pk} submitted")
        self.assertEqual(feed[0]["url"], reverse("claim_detail", args=[claim.pk]))

    def test_activity_feed_shows_member_notifications(self):
        claim_services.submit_claim(
            self.found_item(), self.student, "Serial number C02XK1 on base"
        )
        self.client.force_login(self.finder)

        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "Someone claimed an item you found")
        self.assertContains(response, "timeline-item")

    def test_empty_activity_feed(self):
        self.client.force_login(self.student)

        self.assertContains(self.client.get(reverse("dashboard")), "Nothing yet. Activity will appear here.")

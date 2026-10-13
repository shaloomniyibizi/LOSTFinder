import shutil
import tempfile
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from claims.models import Claim, ItemHandover
from .models import FoundItem, ItemCategory, LostItem, MatchSuggestion


DEMO = "lostfinder.test"


class SeedDemoTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls.media_override = override_settings(MEDIA_ROOT=cls.media, DEBUG=True)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def seed(self, *args):
        out = StringIO()
        call_command("seed_demo", *args, stdout=out)
        return out.getvalue()

    def demo_items(self, model):
        return model.objects.filter(reporter__email__endswith=DEMO)

    def test_seeds_at_least_six_of_each_with_photos(self):
        output = self.seed()

        found = self.demo_items(FoundItem)
        self.assertGreaterEqual(found.count(), 6)
        self.assertGreaterEqual(self.demo_items(LostItem).count(), 6)
        self.assertTrue(all(item.image for item in found))
        self.assertEqual(ItemCategory.objects.count(), 8)
        self.assertIn("officer@lostfinder.test", output)

    def test_workflow_states_cover_the_dashboard(self):
        self.seed()

        claims = dict(
            Claim.objects.filter(claimant__email__endswith=DEMO)
            .values_list("found_item__title", "status")
        )
        self.assertEqual(claims["Student ID card"], Claim.Status.COMPLETED)
        self.assertEqual(claims["Space Grey MacBook Pro laptop"], Claim.Status.APPROVED)
        self.assertEqual(claims["Set of 3 keys on red lanyard"], Claim.Status.SUBMITTED)
        self.assertEqual(ItemHandover.objects.count(), 1)

        # The handover happens after the claim, never before it.
        handover = ItemHandover.objects.select_related("claim").get()
        self.assertGreater(handover.handed_over_at, handover.claim.submitted_at)

        self.assertEqual(
            LostItem.objects.get(title="Lost student ID card").status,
            LostItem.Status.RETURNED,
        )
        self.assertTrue(
            MatchSuggestion.objects.filter(
                lost_item__title="Blue AirPods Pro case",
                status=MatchSuggestion.Status.PENDING,
            ).exists()
        )

    def test_demo_accounts_can_sign_in(self):
        self.seed()

        for name in ("amina", "daniel", "grace", "officer"):
            with self.subTest(user=name):
                self.assertTrue(self.client.login(
                    email=f"{name}@{DEMO}", password="Demo-Pass-2026!",
                ))
                self.client.logout()

        officer = get_user_model().objects.get(email=f"officer@{DEMO}")
        self.assertEqual(officer.profile.user_type, "security")
        self.assertFalse(officer.is_staff)

    def test_rerun_is_a_no_op(self):
        self.seed()
        output = self.seed()

        self.assertIn("already exists", output)
        self.assertEqual(self.demo_items(FoundItem).count(), 6)

    def test_reset_recreates_and_no_create_removes(self):
        self.seed()
        self.seed("--reset")
        self.assertEqual(self.demo_items(FoundItem).count(), 6)

        self.seed("--reset", "--no-create")
        self.assertFalse(get_user_model().objects.filter(email__endswith=DEMO).exists())
        self.assertFalse(self.demo_items(FoundItem).exists())
        self.assertFalse(Claim.objects.exists())
        self.assertEqual(ItemCategory.objects.count(), 8)   # categories kept

    def test_custom_password(self):
        self.seed("--password", "Another-Secret-9")

        self.assertTrue(self.client.login(
            email=f"amina@{DEMO}", password="Another-Secret-9",
        ))

    @override_settings(DEBUG=False)
    def test_refuses_without_debug(self):
        with self.assertRaises(CommandError):
            self.seed()
        self.assertFalse(self.demo_items(FoundItem).exists())

        self.seed("--force")
        self.assertEqual(self.demo_items(FoundItem).count(), 6)

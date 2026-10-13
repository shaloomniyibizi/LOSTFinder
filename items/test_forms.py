import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import UserProfile
from .models import FoundItem, ItemCategory, LostItem


def make_image(name="photo.jpg", size=(40, 30)):
    buffer = BytesIO()
    Image.new("RGB", size, "navy").save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


class ItemFormPageTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media = tempfile.mkdtemp()
        cls.override = override_settings(MEDIA_ROOT=cls.media)
        cls.override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.override.disable()
        shutil.rmtree(cls.media, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            "reporter", "reporter@uni.edu", "pw-12345!"
        )
        UserProfile.objects.create(user=self.user, onboarding_completed=True)
        self.category = ItemCategory.objects.create(name="Electronics")
        self.client.force_login(self.user)

    def payload(self, date_field, **extra):
        return {
            "title": "Blue umbrella",
            "category": self.category.pk,
            "description": "Navy blue folding umbrella with a wooden handle.",
            "location": "Main Library entrance",
            date_field: timezone.localdate().isoformat(),
            **extra,
        }

    def test_lost_form_layout(self):
        response = self.client.get(reverse("lost_item_create"))

        for text in ("Report a lost item", "lf-form-hero-lost", "What did you lose?",
                     "bi-geo-alt", "bi-calendar-event", "bi-card-text",
                     "Keep one secret detail", "data-dropzone", "Submit lost report",
                     "Choose a category", "item-form.js"):
            self.assertContains(response, text)
        self.assertContains(response, f'max="{timezone.localdate().isoformat()}"')

    def test_found_form_layout(self):
        response = self.client.get(reverse("found_item_create"))

        for text in ("Turn in a found item", "lf-form-hero-found", "What did you find?",
                     "take them to the Campus Security Office", "Submit found item"):
            self.assertContains(response, text)
        self.assertNotContains(response, "Keep one secret detail")

    def test_errors_render_per_field(self):
        response = self.client.post(reverse("lost_item_create"), {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "lf-field-invalid")
        self.assertContains(response, "This field is required.", count=5)
        self.assertFalse(LostItem.objects.exists())

    def test_create_with_photo_from_dropzone_input(self):
        self.client.post(
            reverse("found_item_create"),
            self.payload("date_found", image=make_image()),
        )

        item = FoundItem.objects.get()
        self.assertTrue(item.image.name.startswith("found_items/"))

    def test_edit_shows_current_photo_and_can_remove_it(self):
        self.client.post(
            reverse("lost_item_create"),
            self.payload("date_lost", image=make_image()),
        )
        item = LostItem.objects.get()
        url = reverse("lost_item_update", args=[item.pk])

        page = self.client.get(url)
        self.assertContains(page, "Remove current photo")
        self.assertContains(page, item.image.url)
        self.assertContains(page, "Edit your lost report")

        self.client.post(url, self.payload("date_lost", **{"image-clear": "on"}))
        item.refresh_from_db()
        self.assertFalse(item.image)

    def test_edit_without_new_photo_keeps_existing(self):
        self.client.post(
            reverse("lost_item_create"),
            self.payload("date_lost", image=make_image()),
        )
        item = LostItem.objects.get()
        original = item.image.name

        self.client.post(
            reverse("lost_item_update", args=[item.pk]),
            self.payload("date_lost", title="Navy umbrella"),
        )

        item.refresh_from_db()
        self.assertEqual(item.title, "Navy umbrella")
        self.assertEqual(item.image.name, original)

    def test_oversized_photo_rejected(self):
        # A valid JPEG followed by padding: Pillow accepts it, but it is 6 MB.
        jpeg = make_image().read()
        big = SimpleUploadedFile(
            "big.jpg", jpeg + b"\0" * (6 * 1024 * 1024), content_type="image/jpeg"
        )

        response = self.client.post(
            reverse("lost_item_create"), self.payload("date_lost", image=big),
        )

        self.assertContains(response, "The image must not exceed 5 MB.")
        self.assertFalse(LostItem.objects.exists())

    def test_future_date_rejected_with_message(self):
        tomorrow = (timezone.localdate() + timezone.timedelta(days=1)).isoformat()

        response = self.client.post(
            reverse("found_item_create"),
            self.payload("date_found", date_found=tomorrow),
        )

        self.assertContains(response, "The date found cannot be in the future.")

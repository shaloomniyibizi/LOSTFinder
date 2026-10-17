
from django import forms
from django.db.models import Q
from django.utils import timezone

from .models import LostItem, FoundItem


MAX_IMAGE_BYTES = 5 * 1024 * 1024
DESCRIPTION_MAX = 1000


def _widgets(title_hint, location_hint, date_field):
    return {
        "title": forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": title_hint,
            "maxlength": 200,
        }),
        "category": forms.Select(attrs={
            "class": "form-select",
        }),
        "description": forms.Textarea(attrs={
            "class": "form-control",
            "rows": 4,
            "maxlength": DESCRIPTION_MAX,
            "placeholder": (
                "Colour, brand, size, stickers, scratches, what was inside... "
                "the more specific, the better the match."
            ),
        }),
        "location": forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": location_hint,
        }),
        date_field: forms.DateInput(
            attrs={"class": "form-control", "type": "date"},
            format="%Y-%m-%d",
        ),
        "image": forms.ClearableFileInput(attrs={
            "class": "visually-hidden",
            "accept": "image/*",
        }),
    }


class ItemFormMixin:
    """Shared validation for lost/found item forms."""

    date_field = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The browser's date picker can't go past today either.
        self.fields[self.date_field].widget.attrs["max"] = (
            timezone.localdate().isoformat()
        )
        category = self.fields["category"]
        category.empty_label = "Choose a category"
        # Hide retired categories, but keep the one an edited report uses.
        category.queryset = category.queryset.filter(
            Q(is_active=True) | Q(pk=self.instance.category_id)
        )

    def clean_image(self):
        image = self.cleaned_data.get("image")
        uploaded_image = self.files.get(self.add_prefix("image"))

        if uploaded_image and uploaded_image.size > MAX_IMAGE_BYTES:
            raise forms.ValidationError(
                "The image must not exceed 5 MB."
            )

        return image


class LostItemForm(ItemFormMixin, forms.ModelForm):
    date_field = "date_lost"

    class Meta:
        model = LostItem
        fields = [
            "title",
            "category",
            "description",
            "location",
            "date_lost",
            "image",
        ]
        labels = {
            "title": "What did you lose?",
            "description": "Identifying details",
            "location": "Where did you lose it?",
            "date_lost": "When did you lose it?",
            "image": "Photo",
        }
        help_texts = {
            "location": "Building, room or area. Your best guess is fine.",
        }
        widgets = _widgets(
            "e.g. Black laptop bag",
            "e.g. Main Library 2nd floor",
            "date_lost",
        )

    def clean_date_lost(self):
        date_lost = self.cleaned_data["date_lost"]

        if date_lost > timezone.localdate():
            raise forms.ValidationError(
                "The date lost cannot be in the future."
            )

        return date_lost


class FoundItemForm(ItemFormMixin, forms.ModelForm):
    date_field = "date_found"

    class Meta:
        model = FoundItem
        fields = [
            "title",
            "category",
            "description",
            "location",
            "date_found",
            "image",
        ]
        labels = {
            "title": "What did you find?",
            "description": "Identifying details",
            "location": "Where did you find it?",
            "date_found": "When did you find it?",
            "image": "Photo",
        }
        help_texts = {
            "location": "Be as precise as you can, e.g. the table or room number.",
        }
        widgets = _widgets(
            "e.g. Student identity card",
            "e.g. Cafeteria table 14",
            "date_found",
        )

    def clean_date_found(self):
        date_found = self.cleaned_data["date_found"]

        if date_found > timezone.localdate():
            raise forms.ValidationError(
                "The date found cannot be in the future."
            )

        return date_found

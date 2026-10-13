
from django import forms
from django.utils import timezone

from .models import LostItem, FoundItem


class ItemFormMixin:
    """Shared validation and widgets for lost/found item forms."""

    def clean_image(self):
        image = self.cleaned_data.get("image")
        uploaded_image = self.files.get(self.add_prefix("image"))

        if uploaded_image and uploaded_image.size > 5 * 1024 * 1024:
            raise forms.ValidationError(
                "The image must not exceed 5 MB."
            )

        return image


class LostItemForm(ItemFormMixin, forms.ModelForm):
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
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Black laptop bag",
            }),
            "category": forms.Select(attrs={
                "class": "form-select",
                "placeholder": "Select a category",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Describe the item and identifying details",
            }),
            "location": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Where did you lose it?",
            }),
            "date_lost": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "image": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),
        }

    def clean_date_lost(self):
        date_lost = self.cleaned_data["date_lost"]

        if date_lost > timezone.localdate():
            raise forms.ValidationError(
                "The date lost cannot be in the future."
            )

        return date_lost


class FoundItemForm(ItemFormMixin, forms.ModelForm):
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
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Student identity card",
            }),
            "category": forms.Select(attrs={
                "class": "form-select",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Describe the item and identifying details",
            }),
            "location": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Where did you find it?",
            }),
            "date_found": forms.DateInput(attrs={
                "class": "form-control",
                "type": "date",
            }),
            "image": forms.ClearableFileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),
        }

    def clean_date_found(self):
        date_found = self.cleaned_data["date_found"]

        if date_found > timezone.localdate():
            raise forms.ValidationError(
                "The date found cannot be in the future."
            )

        return date_found


from django import forms
from django.utils import timezone

from .models import Claim, ItemHandover


class ClaimForm(forms.Form):
    evidence_description = forms.CharField(
        min_length=20,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 5,
            "placeholder": (
                "Describe details only the owner would know: serial number, "
                "lock-screen photo, contents, scratches, stickers..."
            ),
        }),
        help_text=Claim._meta.get_field("evidence_description").help_text,
    )


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=[
            (Claim.Status.UNDER_REVIEW, "Mark as under review"),
            (Claim.Status.APPROVED, "Approve claim"),
            (Claim.Status.REJECTED, "Reject claim"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    comments = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "class": "form-control",
            "rows": 3,
            "placeholder": "Notes for the audit log (shared with the claimant on rejection)",
        }),
    )


class HandoverForm(forms.ModelForm):
    class Meta:
        model = ItemHandover
        fields = ["handover_location", "handed_over_at", "notes"]
        widgets = {
            "handover_location": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Campus Security Office",
            }),
            "handed_over_at": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "notes": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "ID checked, condition of item, etc.",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["handed_over_at"].input_formats = ["%Y-%m-%dT%H:%M"]
        if not self.is_bound:
            self.initial.setdefault(
                "handed_over_at",
                timezone.localtime().replace(second=0, microsecond=0),
            )

    def clean_handed_over_at(self):
        value = self.cleaned_data["handed_over_at"]
        if value > timezone.now():
            raise forms.ValidationError("The handover time cannot be in the future.")
        return value

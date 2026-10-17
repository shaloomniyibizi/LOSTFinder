from django import forms
from django.core.validators import MaxLengthValidator
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.utils.text import slugify
from .models import UserProfile

User = get_user_model()


def create_unique_username(email):
    base = slugify(email.split("@")[0]) or "user"
    username = base
    counter = 1

    while User.objects.filter(username=username).exists():
        username = f"{base}{counter}"
        counter += 1

    return username


class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ["email"]

    email = forms.EmailField(required=True, widget=forms.EmailInput(attrs={
        "class": "form-control",
        "placeholder": "Enter your university email",
        "autocomplete": "email", }))

    password1 = forms.CharField(required=True, widget=forms.PasswordInput(attrs={
        "class": "form-control",
        "placeholder": "Enter your password",
        "autocomplete": "new-password",
    }),
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Confirm your password",
            "autocomplete": "new-password",
        }),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "An account with that email already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 and password2 and password1 != password2:
            self.add_error("password2", "The passwords do not match.")

        if password1:
            validate_password(password1)

        return cleaned_data

    def save(self, commit=True):
        email = self.cleaned_data["email"].strip().lower()
        username = create_unique_username(email)

        return User.objects.create_user(
            username=username,
            email=email,
            password=self.cleaned_data["password1"],
        )


class OnboardingForm(forms.ModelForm):
    """
    Profile details collected at onboarding (and on the profile page).

    The role field is only offered to staff: everyone else is a student,
    and security officers are appointed in the admin.
    """

    class Meta:
        model = UserProfile
        fields = [
            'phone_number', 'address', 'profile_photo', 'user_type',
            'student_id', 'faculty', 'program',
            'year_of_study', 'bio'
        ]
        labels = {
            "phone_number": "Phone number",
            "student_id": "Student / staff ID",
            "user_type": "Role",
            "year_of_study": "Year of study",
            "bio": "About you",
        }
        widgets = {
            "phone_number": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "07XXXXXXXX",
                "inputmode": "tel",
                "autocomplete": "tel",
            }),
            "address": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Hostel, street or neighbourhood",
                "autocomplete": "street-address",
            }),
            "profile_photo": forms.FileInput(attrs={
                "class": "visually-hidden",
                "accept": "image/*",
            }),
            "user_type": forms.Select(attrs={
                "class": "form-select",
            }),
            "student_id": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. S2024-0142",
            }),
            "faculty": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Engineering",
            }),
            "program": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. Computer Science",
            }),
            "year_of_study": forms.Select(attrs={
                "class": "form-select",
            }),
            "bio": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "maxlength": 500,
                "placeholder": "A sentence or two, e.g. what you study or where you usually are on campus.",
            }),
        }
        help_texts = {
            "phone_number": "10 digits. Only shared with campus security when you claim an item.",
            "profile_photo": "Optional. A clear photo helps security confirm it's you at handover.",
        }

    def __init__(self, *args, allow_role=False, **kwargs):
        super().__init__(*args, **kwargs)

        if not allow_role:
            self.fields.pop("user_type")

        # Accept "078 812 3456" / "078-812-3456": the model's 10-character
        # limit is enforced by clean_phone_number after separators are removed.
        phone = self.fields["phone_number"]
        phone.max_length = 16
        phone.validators = [
            v for v in phone.validators if not isinstance(v, MaxLengthValidator)
        ]
        phone.widget.attrs["maxlength"] = 16

        for field_name in [
            "phone_number",
            "address",
            "student_id",
            "faculty",
            "program",
            "year_of_study",
            "bio"
        ]:
            self.fields[field_name].required = True

    def clean_phone_number(self):
        phone = "".join(self.cleaned_data["phone_number"].replace("-", " ").split())
        if not phone.isdigit() or len(phone) != 10:
            raise forms.ValidationError("Enter a 10-digit phone number, e.g. 0788123456.")
        return phone

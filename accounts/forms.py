from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
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
        "placeholder": "Enter Your Password",
        "autocomplete": "new-password",
    }),
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Comfirm Your Password",
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


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your email",
            "autocomplete": "email",
            "autofocus": True,
        }),
    )

    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your password",
            "autocomplete": "current-password",
        }),
    )


class OnboardingForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = [
            'phone_number', 'address', 'profile_photo', 'user_type',
            'student_id', 'faculty', 'program',
            'year_of_study', 'bio'
        ]
        widgets = {
            "phone_number": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "e.g. +250 7XX XXX XXX",
            }),
            "address": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Your current address",
            }),
            "profile_photo": forms.FileInput(attrs={
                "class": "form-control",
                "accept": "image/*",
            }),
            "student_id": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "University student ID",
            }),
            "faculty": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Faculty or school",
            }),
            "program": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Degree or academic program",
            }),
            "year_of_study": forms.Select(attrs={
                "class": "form-control",
            }),
            "bio": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Tell us a bit about yourself",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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

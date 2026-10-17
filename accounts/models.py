from django.db import models
from django.conf import settings


class UserProfile(models.Model):
    class UserType(models.TextChoices):
        STUDENT = 'student', 'Student'
        STAFF = 'staff', 'University Staff'
        SECURITY = 'security', 'Security Officer'

    YEAR_CHOICES = [(1, 'Year 1'), (2, 'Year 2'), (3, 'Year 3'), (4, 'Year 4')]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')

    phone_number = models.CharField(max_length=10)
    address = models.CharField(max_length=255)
    profile_photo = models.ImageField(
        upload_to='profile_photos/', blank=True, null=True)

    user_type = models.CharField(
        max_length=20, choices=UserType.choices, default=UserType.STUDENT)

    student_id = models.CharField(max_length=50, blank=True, null=True)

    faculty = models.CharField(max_length=120, blank=True, null=True)
    program = models.CharField(max_length=120, blank=True, null=True)
    year_of_study = models.PositiveSmallIntegerField(
        choices=YEAR_CHOICES, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    onboarding_completed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"profile of {self.user.email}"

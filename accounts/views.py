from django.shortcuts import redirect, render
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .forms import RegistrationForm, OnboardingForm, EmailAuthenticationForm

from .models import UserProfile

user = get_user_model()


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == 'POST':
        form = RegistrationForm(request.POST)

        if form.is_valid():
            user = form.save()
            UserProfile.objects.create(user=user)

            login(request, user, backend='accounts.backends.EmailBackend')

            messages.success(request, "Registration successful.")
            return redirect('onboarding')
    else:
        form = RegistrationForm()
    return render(request, 'accounts/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == 'POST':
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, email=email, password=password)

        if user is not None:
            # login(request, user, backend='accounts.backends.EmailBackend')
            login(request, user)

            profile, _ = UserProfile.objects.get_or_create(user=user)

            if not profile.onboarding_completed:
                return redirect('onboarding')

            return redirect('dashboard')
        else:
            messages.error(request, "Invalid email address or password.")

    return render(request, 'accounts/login.html')


@login_required
def onboarding(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = OnboardingForm(request.POST, request.FILES, instance=profile)

        if form.is_valid():
            profile = form.save(commit=False)

            if not request.user.is_staff:
                profile.user_type = UserProfile.UserType.STUDENT

            profile.onboarding_completed = True
            profile.save()

            messages.success(
                request, "Your profile has been completed successfully.")
            return redirect('dashboard')
    else:
        form = OnboardingForm(instance=profile)

    return render(request, 'accounts/onboarding.html', {'form': form})


@login_required
def profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = OnboardingForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save(commit=False)

            messages.success(
                request, "Your profile has been updated successfully.")
            return redirect('profile')
    else:
        form = OnboardingForm(instance=profile)

    return render(request, 'accounts/profile.html', {'form': form, 'profile': profile})


@login_required
def logout_view(request):

    if request.method == 'POST':
        logout(request)
        messages.success(request, "You have been logged out successfully.")
        return redirect('login')
    return redirect('dashboard')

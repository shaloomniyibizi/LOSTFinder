from django.shortcuts import redirect, render, resolve_url
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme
from .forms import RegistrationForm, OnboardingForm

from .models import UserProfile

LOGIN_ERROR = "Invalid email address or password."


def _is_modal_request(request):
    """Requests sent by the sign-in/register modals (static/js/auth-modals.js)."""
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _safe_next(request):
    """The ?next= target, only if it stays on this site."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return ""


def _success(request, to):
    url = resolve_url(to)
    if _is_modal_request(request):
        return JsonResponse({"redirect": url})
    return redirect(url)


def _modal_form_errors(request, template, context):
    """Re-render a form partial so the modal can show its errors in place."""
    html = render_to_string(
        template, {**context, "modal": True, "prefix": "modal-"}, request=request
    )
    return JsonResponse({"html": html}, status=400)


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
            return _success(request, "onboarding")

        if _is_modal_request(request):
            return _modal_form_errors(
                request, "accounts/_register_form.html", {"form": form}
            )
    else:
        form = RegistrationForm()
    return render(request, 'accounts/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    context = {"next": _safe_next(request)}

    if request.method == 'POST':
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(request, email=email, password=password)

        if user is not None:
            login(request, user)

            profile, _ = UserProfile.objects.get_or_create(user=user)

            # Onboarding comes first; afterwards honour ?next=.
            if not profile.onboarding_completed:
                return _success(request, "onboarding")

            return _success(request, context["next"] or "dashboard")

        context.update(login_error=LOGIN_ERROR, email=email)
        if _is_modal_request(request):
            return _modal_form_errors(
                request, "accounts/_login_form.html", context
            )

    return render(request, 'accounts/login.html', context)


@login_required
def onboarding(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = OnboardingForm(
            request.POST, request.FILES, instance=profile,
            allow_role=request.user.is_staff,
        )

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
        form = OnboardingForm(instance=profile, allow_role=request.user.is_staff)

    return render(request, 'accounts/onboarding.html', {'form': form})


@login_required
def profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = OnboardingForm(
            request.POST, request.FILES, instance=profile,
            allow_role=request.user.is_staff,
        )
        if form.is_valid():
            form.save()

            messages.success(
                request, "Your profile has been updated successfully.")
            return redirect('profile')
    else:
        form = OnboardingForm(instance=profile, allow_role=request.user.is_staff)

    return render(request, 'accounts/profile.html', {'form': form, 'profile': profile})


@login_required
def logout_view(request):

    if request.method == 'POST':
        logout(request)
        messages.success(request, "You have been logged out successfully.")
        return redirect('login')
    return redirect('dashboard')


from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/metrics/", views.dashboard_metrics, name="dashboard_metrics"),
]

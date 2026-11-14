from django.urls import path

from . import views

urlpatterns = [
    path("", views.model_report, name="ml_model_report"),
    path("retrain/", views.retrain, name="ml_retrain"),
    path("suggest-category/", views.suggest_category, name="ml_suggest_category"),
]

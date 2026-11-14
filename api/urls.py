
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from . import ml_views, views


router = DefaultRouter()
router.register("categories", views.CategoryViewSet, basename="api-category")
router.register("lost-items", views.LostItemViewSet, basename="api-lost-item")
router.register("found-items", views.FoundItemViewSet, basename="api-found-item")
router.register("matches", views.MatchViewSet, basename="api-match")
router.register("claims", views.ClaimViewSet, basename="api-claim")
router.register("notifications", views.NotificationViewSet, basename="api-notification")

v1 = [
    path("auth/register/", views.RegisterView.as_view(), name="api-register"),
    path("auth/token/", views.TokenLoginView.as_view(), name="api-token"),
    path("auth/logout/", views.LogoutView.as_view(), name="api-logout"),
    path("me/", views.MeView.as_view(), name="api-me"),
    path("dashboard/", views.DashboardView.as_view(), name="api-dashboard"),
    path("ml/training-data/", ml_views.TrainingDataView.as_view(), name="api-ml-training-data"),
    path("ml/models/", ml_views.ModelInfoView.as_view(), name="api-ml-models"),
    path("ml/predict-match/", ml_views.PredictMatchView.as_view(), name="api-ml-predict-match"),
    path("ml/predict-category/", ml_views.PredictCategoryView.as_view(), name="api-ml-predict-category"),
    path("", include(router.urls)),
]

urlpatterns = [
    path("v1/", include(v1)),
    path("schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api-schema"), name="api-docs"),
]

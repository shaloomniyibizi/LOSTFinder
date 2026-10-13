
from django.urls import path

from . import views

urlpatterns = [
    path("", views.claim_list, name="claim_list"),
    path("review/", views.review_queue, name="review_queue"),
    path("new/<int:found_pk>/", views.claim_create, name="claim_create"),
    path("<int:pk>/", views.claim_detail, name="claim_detail"),
    path("<int:pk>/cancel/", views.claim_cancel, name="claim_cancel"),
    path("<int:pk>/review/", views.claim_review, name="claim_review"),
    path("<int:pk>/handover/", views.claim_handover, name="claim_handover"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/read/", views.notifications_mark_read,
         name="notifications_mark_read"),
]

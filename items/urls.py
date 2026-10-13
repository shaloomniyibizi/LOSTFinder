
from django.urls import path
from . import views

urlpatterns = [
    path("lost/", views.lost_item_list, name="lost_item_list"),
    path("found/", views.found_item_list, name="found_item_list"),

    path("lost/create/", views.lost_item_create, name="lost_item_create"),
    path("found/create/", views.found_item_create, name="found_item_create"),

    path("lost/<int:pk>/", views.lost_item_detail, name="lost_item_detail"),
    path("found/<int:pk>/", views.found_item_detail, name="found_item_detail"),

    path("lost/<int:pk>/edit/", views.lost_item_update, name="lost_item_update"),
    path("found/<int:pk>/edit/", views.found_item_update, name="found_item_update"),

    path("lost/<int:pk>/delete/", views.lost_item_delete, name="lost_item_delete"),
    path("found/<int:pk>/delete/", views.found_item_delete,
         name="found_item_delete"),

    path("matches/", views.match_list, name="match_list"),
    path("matches/<int:pk>/update/", views.match_update, name="match_update"),
]

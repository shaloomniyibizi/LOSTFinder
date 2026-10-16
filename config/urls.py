
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

# Admin branding (shown in the AdminLTE layout, templates/admin/).
admin.site.site_header = "LOSTFinder administration"
admin.site.site_title = "LOSTFinder admin"
admin.site.index_title = "Site administration"
# The admin's own sidebar is replaced by the AdminLTE one.
admin.site.enable_nav_sidebar = False

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("items/", include("items.urls")),
    path("claims/", include("claims.urls")),
    path("", include("dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )

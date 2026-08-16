"""
Root URL configuration.

Route prefixes are fixed by the hand-drawn spec and must not move:

    /api/health/          liveness probe
    /api/v1/auth/         staff_auth
    /api/v1/inventory/    inventory (warehouse, catalog, stock, vendor)

``/api/schema/`` and ``/api/docs/`` are added by Sprint 0 so the frontend has a
real contract to build against (finding ``L-6``).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("api/v1/auth/", include("staff_auth.urls")),
    path("api/v1/inventory/", include("inventory.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]

if settings.DEBUG:
    # H-3: dev-only media serving so contract/cover uploads are retrievable.
    # Production serves MEDIA_ROOT from the web server, not from Django.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

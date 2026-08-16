from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"warehouses", views.WarehouseViewSet, basename="warehouse")
router.register(r"sections", views.SectionViewSet, basename="section")
router.register(r"racks", views.RackViewSet, basename="rack")

urlpatterns = [
    path("health/", views.health),
    path("", include(router.urls)),
]
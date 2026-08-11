"""URL routing for the Inventory Module."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BookViewSet,
    RackViewSet,
    SectionViewSet,
    VendorViewSet,
    WarehouseViewSet,
)

app_name = "inventory"

router = DefaultRouter()
router.register("warehouses", WarehouseViewSet, basename="warehouse")
router.register("sections", SectionViewSet, basename="section")
router.register("racks", RackViewSet, basename="rack")
router.register("vendors", VendorViewSet, basename="vendor")
router.register("books", BookViewSet, basename="book")

urlpatterns = [
    path("", include(router.urls)),
]

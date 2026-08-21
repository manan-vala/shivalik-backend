"""URL routing for the Inventory Module."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BookViewSet,
    RackViewSet,
    SectionViewSet,
    StockViewSet,
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
# Q14: the ledger's read surface lives at the top level, not nested under
# `inventory/` — which would give the doubled path `/inventory/inventory/`.
router.register("stock", StockViewSet, basename="stock")

urlpatterns = [
    path("", include(router.urls)),
]

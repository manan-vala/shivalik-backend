"""
The package split must be invisible to importers.

`models.py` / `serializers.py` / `views.py` / `admin.py` each became a package
during Sprint 0. The point of the `__init__` re-exports is that no other module
had to change; these tests fail if someone drops a name from an `__init__`
while moving code between team files.
"""

from django.apps import apps
from django.test import SimpleTestCase


class ModelImportSurfaceTests(SimpleTestCase):
    def test_flat_imports_still_work(self):
        from inventory.models import (  # noqa: F401
            Book,
            BookInventory,
            PurchaseOrder,
            PurchaseOrderLine,
            Rack,
            Section,
            StockMovement,
            TimeStampedModel,
            Vendor,
            Warehouse,
        )

    def test_every_model_is_registered_under_the_inventory_app(self):
        """
        Splitting modules must not split the app label — that would mean a
        new migration graph and a table rename.
        """
        registered = {model.__name__ for model in apps.get_app_config("inventory").get_models()}
        self.assertEqual(
            registered,
            {
                "Warehouse",
                "Section",
                "Rack",
                "Vendor",
                "PurchaseOrder",
                "PurchaseOrderLine",
                "Book",
                "BookInventory",
                "StockMovement",
            },
        )

    def test_models_are_declared_in_their_owning_team_module(self):
        """Ownership is the whole reason for the split; assert it holds."""
        from inventory.models import Book, Rack, StockMovement, Vendor

        self.assertEqual(Rack.__module__, "inventory.models.location")
        self.assertEqual(Book.__module__, "inventory.models.catalog")
        self.assertEqual(StockMovement.__module__, "inventory.models.stock")
        self.assertEqual(Vendor.__module__, "inventory.models.vendor")


class SerializerAndViewImportSurfaceTests(SimpleTestCase):
    def test_serializer_imports(self):
        from inventory.serializers import (  # noqa: F401
            BookInventorySerializer,
            BookSerializer,
            BookStockLevelSerializer,
            RackSerializer,
            SectionSerializer,
            StockMovementRequestSerializer,
            StockMovementSerializer,
            VendorSerializer,
            WarehouseSerializer,
        )

    def test_view_imports(self):
        from inventory.views import (  # noqa: F401
            BookViewSet,
            RackViewSet,
            SectionViewSet,
            StockViewSet,
            VendorViewSet,
            WarehouseViewSet,
        )

    def test_movement_serializers_are_two_distinct_classes(self):
        """
        `StockMovementRequestSerializer` (validates a stock-in/out request
        body) and `StockMovementSerializer` (reads the ledger, added for
        Task 6) share a domain but must never collapse into one class — the
        two used to share a single name, which was the original trap this
        split fixed, and reusing the name for the read side would reopen it.
        """
        from inventory import serializers
        from inventory.models import StockMovement

        self.assertTrue(hasattr(serializers, "StockMovementSerializer"))
        self.assertTrue(hasattr(serializers, "StockMovementRequestSerializer"))
        self.assertIsNot(
            serializers.StockMovementSerializer,
            serializers.StockMovementRequestSerializer,
        )
        # The request validator is a plain Serializer, not bound to a model —
        # only the ledger's own read serializer is.
        self.assertFalse(hasattr(serializers.StockMovementRequestSerializer, "Meta"))
        self.assertIs(serializers.StockMovementSerializer.Meta.model, StockMovement)

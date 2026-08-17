"""
DRF serializers for the Inventory Module, split by owning team.

Two conventions worth calling out:

* Persisted fields are exposed through plain `ModelSerializer`s.
* Derived fields (deficit, needs_reorder, rack_location, ...) live in
  `SerializerMethodField`s so the DB stays the single source of truth and
  business rules can be tweaked without a migration.

  *Exception:* a derived value that must be **filtered or sorted in the
  database** needs a queryset `annotate()` instead — a method field cannot be
  reached by SQL.
"""

from .location import RackSerializer, SectionSerializer, WarehouseSerializer
from .vendor import VendorSerializer
from .catalog import BookSerializer
from .stock import (
    BookInventorySerializer,
    BookStockLevelSerializer,
    StockMovementRequestSerializer,
    StockMovementSerializer,
)

__all__ = [
    "WarehouseSerializer",
    "SectionSerializer",
    "RackSerializer",
    "VendorSerializer",
    "BookSerializer",
    "BookInventorySerializer",
    "BookStockLevelSerializer",
    "StockMovementRequestSerializer",
    "StockMovementSerializer",
]

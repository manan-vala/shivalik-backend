"""
Inventory domain models.

Split into one module per team so four teams can work without colliding in a
single file (see `TEAM-EXECUTION-PLAN.md` §2):

    base.py      shared abstract models
    location.py  Warehouse -> Section -> Rack             (Team A)
    catalog.py   Book                                     (Team B)
    stock.py     BookInventory, StockMovement, the engine (Team B)
    vendor.py    Vendor, PurchaseOrder, PurchaseOrderLine (Team C)

Everything is re-exported here, so `from inventory.models import Book` keeps
working and Django's migration state is untouched — it keys on `app_label`,
not on which module a model is declared in.

Import order below is dependency order; do not alphabetise it.
"""

from .base import TimeStampedModel
from .location import Rack, Section, SectionQuerySet, Warehouse
from .vendor import PurchaseOrder, PurchaseOrderLine, Vendor
from .catalog import Book
from .stock import (
    INBOUND_TYPES,
    OUTBOUND_TYPES,
    REASON_REQUIRED_TYPES,
    BookInventory,
    InsufficientStockError,
    MovementType,
    StockMovement,
    apply_stock_movement,
    signed_delta,
)

__all__ = [
    "TimeStampedModel",
    # location
    "Warehouse",
    "Section",
    "SectionQuerySet",
    "Rack",
    # vendor
    "Vendor",
    "PurchaseOrder",
    "PurchaseOrderLine",
    # catalog
    "Book",
    # stock
    "BookInventory",
    "StockMovement",
    "MovementType",
    "INBOUND_TYPES",
    "OUTBOUND_TYPES",
    "REASON_REQUIRED_TYPES",
    "signed_delta",
    "InsufficientStockError",
    "apply_stock_movement",
]

"""
DRF viewsets for the Inventory Module, split by owning team.

    location.py  Warehouse / Section / Rack        (Team A)
    catalog.py   Book CRUD                         (Team B)
    stock.py     ledger reads + stock mutations    (Team B)
    vendor.py    Vendor / Purchase Orders          (Team C)

Every viewset declares `permission_classes` explicitly. The project default is
already `IsAuthenticated`, but stating it at the view is what makes an
accidental public endpoint visible in review.
"""

from .location import RackViewSet, SectionViewSet, WarehouseViewSet
from .vendor import VendorViewSet
from .catalog import BookViewSet
from .stock import BookStockActionsMixin, StockViewSet

__all__ = [
    "WarehouseViewSet",
    "SectionViewSet",
    "RackViewSet",
    "VendorViewSet",
    "BookViewSet",
    "BookStockActionsMixin",
    "StockViewSet",
]

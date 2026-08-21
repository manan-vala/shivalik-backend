"""
DRF viewsets for the Inventory Module.

The `Book` viewset is the interesting one — it exposes:

    * Standard CRUD on the catalog          (`/books/`)
    * An explicit registration alias        (`/books/register/`)
    * An inventory report (join with racks) (`/books/inventory/`)
    * Atomic stock mutations                (`/books/{id}/stock-in`,
                                             `/books/{id}/stock-out`)

Other viewsets are intentionally minimal — they exist so foreign keys resolve
during development and so future PRs can layer domain logic on top.
"""

from django.db import transaction
from django.db.models import F
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Book, BookInventory, Rack, Section, Vendor, Warehouse
from .serializers import (
    BookInventorySerializer,
    BookSerializer,
    RackInfoSerializer,
    RackSerializer,
    SectionSerializer,
    StockMovementSerializer,
    VendorSerializer,
    WarehouseSerializer,
)


# ---------------------------------------------------------------------------
# Location & supplier viewsets (bare CRUD — extended later)
# ---------------------------------------------------------------------------


class InventoryPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = InventoryPagination


class SectionViewSet(viewsets.ModelViewSet):
    queryset = Section.objects.with_rack_totals().select_related("warehouse")
    serializer_class = SectionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = InventoryPagination


class RackViewSet(viewsets.ModelViewSet):
    queryset = Rack.objects.select_related("section__warehouse", "updated_by").prefetch_related("inventory_records")
    serializer_class = RackSerializer
    permission_classes = [IsAuthenticated]

    pagination_class = InventoryPagination

    @action(detail=True, methods=["get"], url_path="info")
    def info(self, request, pk=None):
        rack = self.get_object()
        return Response(RackInfoSerializer(rack).data)

    @action(detail=False, methods=["get"], url_path="empty")
    def empty(self, request):
        queryset = self.filter_queryset(self.get_queryset().filter(current_stock=0))
        page = self.paginate_queryset(queryset)
        serializer = RackInfoSerializer(page or queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class VendorViewSet(viewsets.ModelViewSet):
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = InventoryPagination


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------


class BookViewSet(viewsets.ModelViewSet):
    """
    Manages the book catalog plus its stock lifecycle.

    Stock mutations always run inside a transaction and use
    ``F()`` expressions to avoid read-modify-write races when multiple
    warehouse staff act concurrently.
    """

    queryset = Book.objects.all()
    serializer_class = BookSerializer
    permission_classes = [IsAuthenticated]

    # -- Section 4.B.2 : POST /books/register/ ----------------------------
    @action(detail=False, methods=["post"], url_path="register")
    def register(self, request):
        """Explicit alias for POST /books/ — kept because the spec lists it."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    # -- Section 4.B.1 : GET /books/inventory/ ----------------------------
    @action(detail=False, methods=["get"], url_path="inventory")
    def inventory(self, request):
        """
        Returns every ``BookInventory`` row joined with book / rack / vendor,
        including the derived ``deficit`` and ``rack_location`` fields. This
        is what the frontend inventory table consumes.
        """
        queryset = (
            BookInventory.objects
            .select_related("book", "vendor", "rack__section__warehouse")
            .all()
        )
        serializer = BookInventorySerializer(queryset, many=True)
        return Response(serializer.data)

    # -- Section 3.A : stock in -------------------------------------------
    @action(detail=True, methods=["post"], url_path="stock-in")
    def stock_in(self, request, pk=None):
        book = self.get_object()
        payload = StockMovementSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        record = self._apply_movement(
            book, payload.validated_data, delta=+1, actor=request.user
        )
        return Response(BookInventorySerializer(record).data, status=status.HTTP_200_OK)

    # -- Section 3.A : stock out ------------------------------------------
    @action(detail=True, methods=["post"], url_path="stock-out")
    def stock_out(self, request, pk=None):
        book = self.get_object()
        payload = StockMovementSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        record = self._apply_movement(
            book, payload.validated_data, delta=-1, actor=request.user
        )
        return Response(BookInventorySerializer(record).data, status=status.HTTP_200_OK)

    # -- internal ---------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def _apply_movement(book: Book, data: dict, *, delta: int, actor=None) -> BookInventory:
        """
        Apply a stock movement atomically.

        ``delta`` is +1 for stock-in, -1 for stock-out. Uses ``F()`` so the
        update is a single UPDATE statement and safe under concurrency.
        """
        qty = data["quantity"]
        rack = data["rack"]
        vendor = data["vendor"]

        record, _created = BookInventory.objects.select_for_update().get_or_create(
            book=book,
            rack=rack,
            defaults={"vendor": vendor},
        )

        rack.adjust_stock(delta=delta * qty, actor=actor)

        if delta > 0:
            BookInventory.objects.filter(pk=record.pk).update(
                in_entry=F("in_entry") + qty,
                curr_stock=F("curr_stock") + qty,
                vendor=vendor,
            )
        else:
            BookInventory.objects.filter(pk=record.pk).update(
                out_entry=F("out_entry") + qty,
                curr_stock=F("curr_stock") - qty,
            )

        record.refresh_from_db()
        return record

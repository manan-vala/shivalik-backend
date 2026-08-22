"""
Ledger reads and stock mutations. **Owner: Team B.**

Stock mutations run through `apply_stock_movement` — the single write path
documented in `inventory/models/stock.py`. Nothing here does its own
`BookInventory.objects.update()`.

`H-1` is fixed by construction, not by patching the old check: the
sufficiency check that used to run here, before this view opened a
transaction, now runs *inside* the engine's `select_for_update()` lock. Two
concurrent stock-outs can no longer both pass a check that is stale by the
time either of them writes.

Q14 answered: the read surface lives under the top-level `stock/` resource
(`StockViewSet`, below) — `books/inventory/` stays only as a deprecated
alias. `books/{id}/history|in-entries|out-entries/` stay on `BookViewSet`
since they are naturally detail routes on a book.
"""

from django.db.models import F, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from staff_auth.permissions import IsApprovedStaff

from ..models import (
    INBOUND_TYPES,
    OUTBOUND_TYPES,
    Book,
    BookInventory,
    InsufficientStockError,
    MovementType,
    StockMovement,
    apply_stock_movement,
)
from ..serializers import (
    BookInventorySerializer,
    BookSerializer,
    BookStockLevelSerializer,
    StockMovementRequestSerializer,
    StockMovementSerializer,
)


def _books_with_stock_totals():
    """
    Every `Book`, annotated with `curr_stock` — `Sum(curr_stock)` across
    every rack it sits on. Backs `StockViewSet.low_stock` / `in_stock`.

    A correlated subquery, not a joined `Sum`, so the number cannot be
    multiplied by another join a caller adds later — the same reasoning as
    `Section.objects.with_rack_totals()` and `BookInventory.objects.
    with_book_totals()`.
    """
    per_book = (
        BookInventory.objects
        .filter(book=OuterRef("pk"))
        .order_by()
        .values("book")
        .annotate(total=Sum("curr_stock"))
        .values("total")
    )
    return Book.objects.annotate(
        curr_stock=Coalesce(Subquery(per_book[:1], output_field=IntegerField()), 0),
    )


class BookStockActionsMixin:
    """
    The stock lifecycle half of `BookViewSet`.

    Split out from the catalog CRUD so that Team B's engine work and Team B's
    book-schema work do not sit in the same file.
    """

    # -- Section 4.B.1 : GET /books/inventory/ ----------------------------
    @action(detail=False, methods=["get"], url_path="inventory")
    def inventory(self, request):
        """
        Returns every ``BookInventory`` row joined with book / rack / vendor,
        including the derived ``deficit`` and ``rack_location`` fields. This
        is what the frontend inventory table consumes.

        Q14 answered: this route stays as a deprecated alias. The ledger's real
        home is the top-level ``stock/`` resource built in Task 6.
        """
        queryset = (
            BookInventory.objects
            .with_book_totals()
            .select_related("book", "vendor", "rack__section__warehouse")
            .all()
        )
        serializer = BookInventorySerializer(queryset, many=True)
        return Response(serializer.data)

    # -- Section 3.A : stock in -------------------------------------------
    @action(detail=True, methods=["post"], url_path="stock-in")
    def stock_in(self, request, pk=None):
        book = self.get_object()
        payload = StockMovementRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        record = apply_stock_movement(
            book=book,
            rack=payload.validated_data["rack"],
            quantity=payload.validated_data["quantity"],
            movement_type=MovementType.IN,
            actor=request.user,
            vendor=payload.validated_data["vendor"],
        )
        return Response(BookInventorySerializer(record).data, status=status.HTTP_200_OK)

    # -- Section 3.A : stock out ------------------------------------------
    @action(detail=True, methods=["post"], url_path="stock-out")
    def stock_out(self, request, pk=None):
        book = self.get_object()
        payload = StockMovementRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        # The serializer still requires a vendor on every request (unchanged
        # API contract), and a blocked one is still rejected right there. It
        # is not forwarded to the engine here: an outbound movement has no
        # vendor of its own (`StockMovement.vendor` is "set on incoming stock
        # only"), so there is nothing genuine to record on the ledger row.
        try:
            record = apply_stock_movement(
                book=book,
                rack=payload.validated_data["rack"],
                quantity=payload.validated_data["quantity"],
                movement_type=MovementType.OUT,
                actor=request.user,
            )
        except InsufficientStockError:
            return Response(
                {"detail": "Insufficient stock on the specified rack."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(BookInventorySerializer(record).data, status=status.HTTP_200_OK)

    # -- Section 4.B.3 : the movement log, filtered three ways ------------

    @extend_schema(responses=StockMovementSerializer)
    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        """Every `StockMovement` row for this book, newest first."""
        return self._movements(self.get_object())

    @extend_schema(responses=StockMovementSerializer)
    @action(detail=True, methods=["get"], url_path="in-entries")
    def in_entries(self, request, pk=None):
        return self._movements(self.get_object(), movement_type__in=INBOUND_TYPES)

    @extend_schema(responses=StockMovementSerializer)
    @action(detail=True, methods=["get"], url_path="out-entries")
    def out_entries(self, request, pk=None):
        return self._movements(self.get_object(), movement_type__in=OUTBOUND_TYPES)

    def _movements(self, book: Book, **filters) -> Response:
        queryset = (
            StockMovement.objects
            .filter(book=book, **filters)
            .select_related("rack__section__warehouse", "vendor", "actor")
        )
        page = self.paginate_queryset(queryset)
        serializer = StockMovementSerializer(
            page, many=True, context=self.get_serializer_context(),
        )
        return self.get_paginated_response(serializer.data)


class StockViewSet(viewsets.GenericViewSet):
    """
    The top-level ledger read surface (Q14) — everything that used to be
    imagined as ``inventory/…`` lives at ``stock/…`` instead, avoiding the
    doubled path ``/api/v1/inventory/inventory/``.

    Action-only: there is no single "stock" resource with a detail route, so
    this declares no ``list``/``retrieve`` of its own.
    """

    permission_classes = [IsAuthenticated, IsApprovedStaff]
    queryset = Book.objects.none()  # unused; default for schema generation only
    serializer_class = BookStockLevelSerializer  # ditto — each action overrides below

    @extend_schema(responses=BookStockLevelSerializer)
    @action(detail=False, methods=["get"], url_path="low-stock")
    def low_stock(self, request):
        """
        Books where total stock — summed across every rack — is below
        ``min_stock``. **Not** `curr_stock < min_stock` per `(book, rack)`
        row: see `BookInventoryQuerySet.with_book_totals` for why that
        comparison is wrong, and `04-api-surface.md` §4.7.
        """
        queryset = (
            _books_with_stock_totals()
            .filter(curr_stock__lt=F("min_stock"))
            .prefetch_related("inventory_records__rack__section__warehouse")
        )
        return self._books(queryset)

    @extend_schema(responses=BookStockLevelSerializer)
    @action(detail=False, methods=["get"], url_path="in-stock")
    def in_stock(self, request):
        """Books currently holding stock anywhere."""
        queryset = (
            _books_with_stock_totals()
            .filter(curr_stock__gt=0)
            .prefetch_related("inventory_records__rack__section__warehouse")
        )
        return self._books(queryset)

    @extend_schema(responses=BookSerializer)
    @action(detail=False, methods=["get"], url_path="low-selling")
    def low_selling(self, request):
        """Books flagged by the sales-analytics job (`Book.low_selling`)."""
        queryset = Book.objects.filter(low_selling=True)
        page = self.paginate_queryset(queryset)
        serializer = BookSerializer(page, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(serializer.data)

    def _books(self, queryset) -> Response:
        page = self.paginate_queryset(queryset)
        serializer = BookStockLevelSerializer(
            page, many=True, context=self.get_serializer_context(),
        )
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=["post"], url_path="reorder")
    def reorder_low_stock(self, request):
        """Generates a DRAFT PurchaseOrder for books with low stock."""
        queryset = _books_with_stock_totals().filter(curr_stock__lt=F("min_stock"))
        
        vendor_id = request.data.get("vendor_id")
        if not vendor_id:
            return Response({"detail": "vendor_id is required to create a purchase order."}, status=status.HTTP_400_BAD_REQUEST)
            
        from ..models import PurchaseOrder, PurchaseOrderLine, Vendor
        try:
            vendor = Vendor.objects.get(pk=vendor_id)
        except Vendor.DoesNotExist:
            return Response({"detail": "Vendor not found."}, status=status.HTTP_400_BAD_REQUEST)

        books_to_order = list(queryset)
        if not books_to_order:
            return Response({"detail": "No books require reordering."}, status=status.HTTP_200_OK)

        po = PurchaseOrder.objects.create(
            vendor=vendor,
            status=PurchaseOrder.Status.DRAFT,
            created_by=request.user,
            notes="Auto-generated from low stock reorder."
        )
        
        lines_created = 0
        for book in books_to_order:
            deficit = max(book.min_stock - book.curr_stock, 1)
            PurchaseOrderLine.objects.create(
                purchase_order=po,
                book=book,
                quantity_ordered=deficit,
                unit_price=book.mrp if book.mrp else 0.0
            )
            lines_created += 1
            
        return Response(
            {"detail": f"Created Purchase Order {po.pk} for {lines_created} titles."},
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["get"], url_path="dead-stock")
    def dead_stock(self, request):
        """Returns inventory that hasn't moved in a specified number of days."""
        from django.utils import timezone
        from django.conf import settings
        
        queryset = BookInventory.objects.select_related('book', 'rack__section__warehouse').all()
        
        dead_stock_list = []
        now = timezone.now()
        
        for inv in queryset:
            threshold = inv.book.dead_stock_threshold_days or getattr(settings, 'DEAD_STOCK_DEFAULT_DAYS', 90)
            last_activity = inv.last_out_at or inv.created_at
            days_inactive = (now - last_activity).days
            
            if days_inactive > threshold and inv.curr_stock > 0:
                dead_stock_list.append(inv)
                
        page = self.paginate_queryset(dead_stock_list)
        from ..serializers import BookInventorySerializer
        if page is not None:
            serializer = BookInventorySerializer(page, many=True, context=self.get_serializer_context())
            return self.get_paginated_response(serializer.data)
            
        serializer = BookInventorySerializer(dead_stock_list, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

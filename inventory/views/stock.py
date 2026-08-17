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
"""

from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import (
    BookInventory,
    InsufficientStockError,
    MovementType,
    apply_stock_movement,
)
from ..serializers import BookInventorySerializer, StockMovementRequestSerializer


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
        home is the top-level ``stock/`` resource Team B builds in Task 6.
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

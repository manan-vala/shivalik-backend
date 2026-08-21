"""
Ledger reads and stock mutations. **Owner: Team B.**

Everything here is scheduled to be rewritten by Team B's Tasks 2–4: the
mutations move behind `apply_stock_movement`, and `_apply_movement` below is
deleted. It is kept intact for now so the existing API keeps working while the
engine is built — but it is the code that carries finding `H-1`, so nothing new
should be layered on top of it.
"""

from django.db import transaction
from django.db.models import F
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response

from ..models import Book, BookInventory
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
        record = self._apply_movement(book, payload.validated_data, delta=+1)
        return Response(BookInventorySerializer(record).data, status=status.HTTP_200_OK)

    # -- Section 3.A : stock out ------------------------------------------
    @action(detail=True, methods=["post"], url_path="stock-out")
    def stock_out(self, request, pk=None):
        book = self.get_object()
        payload = StockMovementRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        # H-1: this check runs OUTSIDE the transaction below, so two concurrent
        # callers can both pass it and oversell. Team B's Task 3 deletes it and
        # re-checks inside the engine's lock. Do not build on this.
        record = BookInventory.objects.filter(
            book=book,
            rack=payload.validated_data["rack"],
        ).first()
        if record is None or record.curr_stock < payload.validated_data["quantity"]:
            return Response(
                {"detail": "Insufficient stock on the specified rack."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record = self._apply_movement(book, payload.validated_data, delta=-1)
        return Response(BookInventorySerializer(record).data, status=status.HTTP_200_OK)

    # -- internal ---------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def _apply_movement(book: Book, data: dict, *, delta: int) -> BookInventory:
        """
        Apply a stock movement atomically.

        DEPRECATED — superseded by `inventory.models.stock.apply_stock_movement`
        as soon as Team B's Task 2 lands. Team B's Task 4 deletes this method
        and rewires both actions above to the engine.
        """
        qty = data["quantity"]
        rack = data["rack"]
        vendor = data["vendor"]

        record, _created = BookInventory.objects.select_for_update().get_or_create(
            book=book,
            rack=rack,
            defaults={"vendor": vendor},
        )

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

        # This used to roll `Section.last_change_date` forward. Q3 moved that
        # field to Rack, and Q3's owner (Team A) writes it from
        # `rack.adjust_stock()` — which this method does not call. So between
        # now and Team B's Task 2 nothing stamps a timestamp, exactly as
        # nothing has ever stamped `Rack.last_used` (finding `M-1`). Do not
        # patch it here: a second writer of rack state is the drift the engine
        # exists to prevent.

        record.refresh_from_db()
        return record

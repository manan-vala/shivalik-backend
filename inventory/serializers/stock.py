"""Serializers for the stock ledger. **Owner: Team B.**"""

from django.db.models import Sum
from rest_framework import serializers

from ..models import Book, BookInventory, Rack, StockMovement, Vendor


class BookInventorySerializer(serializers.ModelSerializer):
    """
    Rich per-rack inventory row used by the frontend inventory table.

    Adds derived fields:
        * ``deficit``       — how many units below ``min_stock`` we are.
        * ``needs_reorder`` — convenience boolean for UI badges.
        * ``rack_location`` — human-friendly "Warehouse / Section / Rack".

    ``deficit`` and ``needs_reorder`` compare against the book's stock
    *everywhere*, not just this row — see `_book_total_stock`. Getting this
    wrong feeds `reorder/` a per-rack number, ordering stock nobody needs.
    """

    book_title = serializers.CharField(source="book.title", read_only=True)
    isbn = serializers.CharField(source="book.isbn", read_only=True)
    vendor_name = serializers.CharField(
        source="vendor.company_name", read_only=True, default=None,
    )

    deficit = serializers.SerializerMethodField()
    needs_reorder = serializers.SerializerMethodField()
    rack_location = serializers.SerializerMethodField()

    class Meta:
        model = BookInventory
        fields = [
            "id",
            "book",
            "book_title",
            "isbn",
            "rack",
            "rack_location",
            "vendor",
            "vendor_name",
            "in_entry",
            "out_entry",
            "curr_stock",
            "deficit",
            "needs_reorder",
        ]
        read_only_fields = ["in_entry", "out_entry", "curr_stock"]

    # -- derived fields ----------------------------------------------------

    @staticmethod
    def _book_total_stock(obj: BookInventory) -> int:
        """
        Prefer ``BookInventory.objects.with_book_totals()``'s annotation;
        fall back to one aggregate query for a bare instance — e.g. the
        single row `apply_stock_movement()` returns after a stock-in/out,
        which was never fetched through that queryset.
        """
        annotated = getattr(obj, "book_total_stock", None)
        if annotated is not None:
            return annotated
        return obj.book.inventory_records.aggregate(total=Sum("curr_stock"))["total"] or 0

    def get_deficit(self, obj: BookInventory) -> int:
        """Positive => below threshold; zero or negative => healthy."""
        return max(obj.book.min_stock - self._book_total_stock(obj), 0)

    def get_needs_reorder(self, obj: BookInventory) -> bool:
        return self._book_total_stock(obj) < obj.book.min_stock

    def get_rack_location(self, obj: BookInventory) -> str:
        rack = obj.rack
        section = rack.section
        return f"{section.warehouse.name} / {section.name} / {rack.name}"


class BookStockLevelSerializer(serializers.ModelSerializer):
    """
    A book with its stock aggregated across every rack it sits on. Backs
    `stock/low-stock/` and `stock/in-stock/` — both list *books*, not
    per-rack ledger rows, and both need `racks` broken out as location
    detail once the top-line number is aggregated away (`04` §4.7).

    `curr_stock` is a `SerializerMethodField` with a fallback, not a bare
    `IntegerField(read_only=True)` reading the queryset annotation. A
    read-only field whose attribute is missing does not fail — DRF *omits the
    key* (`05` §5.3), and `get_deficit` would then raise `AttributeError` and
    surface as a 500. Any future caller that serializes a `Book` without
    going through `_books_with_stock_totals()` — `reorder/` is the obvious
    candidate — gets a correct number instead of a server error. Same shape
    as `SectionSerializer`'s totals, which exist for the same reason.
    """

    curr_stock = serializers.SerializerMethodField()
    deficit = serializers.SerializerMethodField()
    racks = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = ["id", "title", "isbn", "min_stock", "curr_stock", "deficit", "racks"]

    @staticmethod
    def _curr_stock(book: Book) -> int:
        """Prefer the annotation; fall back to one aggregate for a bare row."""
        annotated = getattr(book, "curr_stock", None)
        if annotated is not None:
            return annotated
        return book.inventory_records.aggregate(total=Sum("curr_stock"))["total"] or 0

    def get_curr_stock(self, book: Book) -> int:
        return self._curr_stock(book)

    def get_deficit(self, book: Book) -> int:
        return max(book.min_stock - self._curr_stock(book), 0)

    def get_racks(self, book: Book) -> list[dict]:
        """
        Requires ``inventory_records__rack__section__warehouse`` prefetched
        on the queryset — this runs once per row otherwise.
        """
        return [
            {
                "rack": row.rack_id,
                "rack_location": (
                    f"{row.rack.section.warehouse.name} / "
                    f"{row.rack.section.name} / {row.rack.name}"
                ),
                "curr_stock": row.curr_stock,
            }
            for row in book.inventory_records.all()
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    """
    Read-only view of the append-only ledger. Backs `books/{id}/history/`,
    `in-entries/` and `out-entries/`.

    No write path here on purpose — the model has none either (§`StockMovement`
    docstring). A wrong movement is corrected with a compensating adjustment
    through `apply_stock_movement`, not an edit to this row.
    """

    book_title = serializers.CharField(source="book.title", read_only=True)
    rack_location = serializers.SerializerMethodField()
    vendor_name = serializers.CharField(
        source="vendor.company_name", read_only=True, default=None,
    )
    actor_name = serializers.CharField(source="actor.name", read_only=True, default=None)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "book",
            "book_title",
            "rack",
            "rack_location",
            "movement_type",
            "quantity",
            "balance_after",
            "vendor",
            "vendor_name",
            "purchase_order",
            "actor",
            "actor_name",
            "reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_rack_location(self, obj: StockMovement) -> str:
        rack = obj.rack
        section = rack.section
        return f"{section.warehouse.name} / {section.name} / {rack.name}"


class StockMovementRequestSerializer(serializers.Serializer):
    """
    Input payload for the ``stock-in`` / ``stock-out`` actions on Book.

    Named ``…RequestSerializer`` because it validates a request body and is not
    tied to a model — the movement *log* has its own model serializer
    (`StockMovementSerializer`, above). The two used to share the name
    ``StockMovementSerializer``, which was a trap.
    """

    rack = serializers.PrimaryKeyRelatedField(queryset=Rack.objects.all())
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all())
    quantity = serializers.IntegerField(min_value=1)

    def validate_vendor(self, vendor: Vendor) -> Vendor:
        if vendor.is_blocked:
            raise serializers.ValidationError("Vendor is blocked.")
        return vendor

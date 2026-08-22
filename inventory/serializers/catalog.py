"""Serializers for the book catalog. **Owner: Team B.**"""

from typing import Optional

from rest_framework import serializers

from ..models import Book


class BookSerializer(serializers.ModelSerializer):
    """
    Catalog-level serializer — no stock information (that lives in
    `BookInventorySerializer`, `serializers/stock.py`).

    `mrp` is nullable at the database level — existing rows may predate
    pricing — but a *new* book must be priced: enforced here via
    `extra_kwargs`, not a fake `0.00` default that would silently misprice a
    book nobody actually priced. Every other new field is optional at the API
    level exactly where the model already says so (`blank=True` / `null=True`).

    `default_*_name` mirror the `warehouse_name` / `section_name` convention
    from `serializers/location.py`, so the frontend does not need a second
    round trip to show where a book's default storage is.

    They are `SerializerMethodField`s, not `CharField(source="<fk>.name")`,
    because these FKs are nullable and that combination drops the key from
    the response instead of returning `null` — the trap
    `05-implementation-playbook.md` §5.3 documents. `default=None` is *not*
    a sufficient fix: DRF's `get_default()` raises `SkipField` whenever
    `partial=True`, so the fields survive GET and POST but silently vanish
    from every **PATCH** response, leaving the same endpoint answering with
    two different shapes. That is the same bug already on record in
    `DECISIONS.md` for `POST /sections/`. A method field has no default
    machinery and always emits a value.
    """

    default_warehouse_name = serializers.SerializerMethodField()
    default_section_name = serializers.SerializerMethodField()
    default_rack_name = serializers.SerializerMethodField()

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "isbn",
            "author",
            "publisher",
            "edition",
            "language",
            "description",
            "cover_image",
            "class_level",
            "board",
            "subject",
            "mrp",
            "tax_percent",
            "default_discount_percent",
            "default_warehouse",
            "default_warehouse_name",
            "default_section",
            "default_section_name",
            "default_rack",
            "default_rack_name",
            "min_stock",
            "dead_stock_threshold_days",
            "low_selling",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["low_selling", "created_at", "updated_at"]
        extra_kwargs = {
            # Nullable in the database on purpose — rows may predate pricing —
            # but a new book must be priced. A fake 0.00 default would
            # silently misprice a book nobody actually priced. `partial=True`
            # (PATCH) still exempts it, so editing a legacy book is unaffected.
            "mrp": {"required": True, "allow_null": False},
        }

    # -- derived fields ----------------------------------------------------

    @staticmethod
    def _related_name(related) -> Optional[str]:
        return related.name if related is not None else None

    def get_default_warehouse_name(self, book: Book) -> Optional[str]:
        return self._related_name(book.default_warehouse)

    def get_default_section_name(self, book: Book) -> Optional[str]:
        return self._related_name(book.default_section)

    def get_default_rack_name(self, book: Book) -> Optional[str]:
        return self._related_name(book.default_rack)

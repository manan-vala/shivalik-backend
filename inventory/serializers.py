"""
DRF serializers for the Inventory Module.

Two conventions worth calling out:

* Persisted fields are exposed through plain `ModelSerializer`s.
* Derived fields (deficit, needs_reorder, rack_location, ...) live in
  `SerializerMethodField`s so the DB stays the single source of truth and
  business rules can be tweaked without a migration.
"""

from django.utils import timezone
from rest_framework import serializers

from .models import Book, BookInventory, Rack, Section, Vendor, Warehouse


# ---------------------------------------------------------------------------
# Location hierarchy (flat, minimal — expanded in a later PR)
# ---------------------------------------------------------------------------


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["id", "name", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class SectionSerializer(serializers.ModelSerializer):
    max_capacity = serializers.IntegerField(read_only=True)
    current_stock = serializers.IntegerField(read_only=True)

    class Meta:
        model = Section
        fields = [
            "id",
            "warehouse",
            "name",
            "max_capacity",
            "current_stock",
        ]


class RackSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        max_capacity = attrs.get(
            "max_capacity",
            self.instance.max_capacity if self.instance else 0,
        )
        current_stock = self.instance.current_stock if self.instance else 0
        if max_capacity and current_stock > max_capacity:
            raise serializers.ValidationError({
                "max_capacity": "Maximum capacity cannot be below current stock.",
            })
        return attrs

    class Meta:
        model = Rack
        fields = [
            "id", "section", "name", "max_capacity", "current_stock",
            "last_change_date", "last_used", "updated_by",
        ]
        read_only_fields = [
            "current_stock", "last_change_date", "last_used", "updated_by",
        ]


class RackInfoSerializer(RackSerializer):
    available = serializers.SerializerMethodField()
    is_empty = serializers.SerializerMethodField()
    empty_for_days = serializers.SerializerMethodField()
    books_stored = serializers.SerializerMethodField()

    class Meta(RackSerializer.Meta):
        fields = RackSerializer.Meta.fields + [
            "available", "is_empty", "empty_for_days", "books_stored",
        ]

    def get_available(self, obj: Rack) -> int:
        return obj.max_capacity - obj.current_stock

    def get_is_empty(self, obj: Rack) -> bool:
        return obj.current_stock == 0

    def get_empty_for_days(self, obj: Rack):
        if obj.current_stock != 0 or obj.last_used is None:
            return None
        return (timezone.now() - obj.last_used).days

    def get_books_stored(self, obj: Rack) -> int:
        return obj.inventory_records.count()


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = [
            "id",
            "company_name",
            "vendor_name",
            "gst_number",
            "is_blocked",
        ]


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------


class BookSerializer(serializers.ModelSerializer):
    """Catalog-level serializer — no stock information."""

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "isbn",
            "min_stock",
            "low_selling",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["low_selling", "created_at", "updated_at"]


class BookInventorySerializer(serializers.ModelSerializer):
    """
    Rich per-rack inventory row used by the frontend inventory table.

    Adds derived fields:
        * ``deficit``       — how many units below ``min_stock`` we are.
        * ``needs_reorder`` — convenience boolean for UI badges.
        * ``rack_location`` — human-friendly "Warehouse / Section / Rack".
    """

    book_title = serializers.CharField(source="book.title", read_only=True)
    isbn = serializers.CharField(source="book.isbn", read_only=True)
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True)

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

    def get_deficit(self, obj: BookInventory) -> int:
        """Positive => below threshold; zero or negative => healthy."""
        return max(obj.book.min_stock - obj.curr_stock, 0)

    def get_needs_reorder(self, obj: BookInventory) -> bool:
        return obj.curr_stock < obj.book.min_stock

    def get_rack_location(self, obj: BookInventory) -> str:
        rack = obj.rack
        section = rack.section
        return f"{section.warehouse.name} / {section.name} / {rack.name}"


# ---------------------------------------------------------------------------
# Action payload validators (thin, non-model)
# ---------------------------------------------------------------------------


class StockMovementSerializer(serializers.Serializer):
    """Input payload for the ``stock-in`` / ``stock-out`` actions on Book."""

    rack = serializers.PrimaryKeyRelatedField(queryset=Rack.objects.all())
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all())
    quantity = serializers.IntegerField(min_value=1)

    def validate_vendor(self, vendor: Vendor) -> Vendor:
        if vendor.is_blocked:
            raise serializers.ValidationError("Vendor is blocked.")
        return vendor

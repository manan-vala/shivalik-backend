"""Serializers for the stock ledger. **Owner: Team B.**"""

from rest_framework import serializers

from ..models import BookInventory, Rack, Vendor


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


class StockMovementRequestSerializer(serializers.Serializer):
    """
    Input payload for the ``stock-in`` / ``stock-out`` actions on Book.

    Named ``…RequestSerializer`` because it validates a request body and is not
    tied to a model — the movement *log* has its own model serializer. The two
    used to share the name ``StockMovementSerializer``, which was a trap.
    """

    rack = serializers.PrimaryKeyRelatedField(queryset=Rack.objects.all())
    vendor = serializers.PrimaryKeyRelatedField(queryset=Vendor.objects.all())
    quantity = serializers.IntegerField(min_value=1)

    def validate_vendor(self, vendor: Vendor) -> Vendor:
        if vendor.is_blocked:
            raise serializers.ValidationError("Vendor is blocked.")
        return vendor

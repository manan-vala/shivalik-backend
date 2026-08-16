"""Serializers for the storage hierarchy. **Owner: Team A.**"""

from django.db.models import Sum
from rest_framework import serializers

from ..models import Rack, Section, Warehouse


class WarehouseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = ["id", "name", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class SectionSerializer(serializers.ModelSerializer):
    """
    Q3: capacity moved to Rack, so a section's totals are annotations rather
    than columns. The response keeps the same two keys it always had — the
    numbers are now derived and cannot drift from the racks they describe.

    List and detail routes supply them via `Section.objects.with_rack_totals()`.
    A just-created instance has never been through that queryset, and a plain
    `IntegerField(read_only=True)` would silently *omit* the key rather than
    fail — so `POST` and `GET` would answer with different shapes and nobody
    would notice. Hence the fallback below.
    """

    max_capacity = serializers.SerializerMethodField()
    current_stock = serializers.SerializerMethodField()

    class Meta:
        model = Section
        fields = [
            "id",
            "warehouse",
            "name",
            "max_capacity",
            "current_stock",
        ]

    # -- derived fields ----------------------------------------------------

    @staticmethod
    def _total(section: Section, field: str) -> int:
        """Prefer the annotation; fall back to one aggregate for single rows."""
        annotated = getattr(section, field, None)
        if annotated is not None:
            return annotated
        return section.racks.aggregate(total=Sum(field))["total"] or 0

    def get_max_capacity(self, section: Section) -> int:
        return self._total(section, "max_capacity")

    def get_current_stock(self, section: Section) -> int:
        return self._total(section, "current_stock")


class RackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rack
        fields = [
            "id",
            "section",
            "name",
            "max_capacity",
            "current_stock",
            "last_change_date",
            "last_used",
            "updated_by",
        ]
        # Everything except max_capacity is written by `adjust_stock()`, never
        # by an API caller — the stock ledger is not editable over HTTP.
        read_only_fields = [
            "current_stock",
            "last_change_date",
            "last_used",
            "updated_by",
        ]

    def validate_max_capacity(self, value: int) -> int:
        """
        Refuse to shrink a rack below what is already on it.

        Without this the `rack_stock_within_capacity` constraint catches it —
        as an `IntegrityError`, which DRF turns into a 500. The same class of
        trap as `PositiveIntegerField` underflow: guard in Python, so the
        caller gets a 400 that says what went wrong.
        """
        if self.instance is None or value == 0:
            # 0 means "unmeasured" and is always allowed; see Rack.Meta.
            return value
        if value < self.instance.current_stock:
            raise serializers.ValidationError(
                f"Rack already holds {self.instance.current_stock} books; "
                f"capacity cannot be set below that. Move stock off it first."
            )
        return value

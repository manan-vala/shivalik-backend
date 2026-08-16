"""Serializers for the storage hierarchy. **Owner: Team A.**"""

from django.db.models import Sum
from rest_framework import serializers

from ..models import Rack, Section, Warehouse


class WarehouseSerializer(serializers.ModelSerializer):
    """
    `sections_count` is annotated by the viewset's queryset. It uses the same
    fallback shape as `SectionSerializer` below and for the same reason: a
    just-created warehouse has never been through the annotating queryset, and
    a bare `IntegerField(read_only=True)` would drop the key from the POST
    response while keeping it on GET.
    """

    sections_count = serializers.SerializerMethodField()

    class Meta:
        model = Warehouse
        fields = [
            "id",
            "name",
            "code",
            "location",
            "description",
            "is_active",
            "sections_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_sections_count(self, warehouse: Warehouse) -> int:
        annotated = getattr(warehouse, "sections_count", None)
        if annotated is not None:
            return annotated
        return warehouse.sections.count()


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
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    racks_count = serializers.SerializerMethodField()

    class Meta:
        model = Section
        fields = [
            "id",
            "warehouse",
            "warehouse_name",
            "name",
            "code",
            "is_active",
            "max_capacity",
            "current_stock",
            "racks_count",
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

    def get_racks_count(self, section: Section) -> int:
        annotated = getattr(section, "racks_count", None)
        if annotated is not None:
            return annotated
        return section.racks.count()


class RackSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(
        source="section.warehouse.name", read_only=True
    )
    section_name = serializers.CharField(source="section.name", read_only=True)

    class Meta:
        model = Rack
        fields = [
            "id",
            "section",
            "section_name",
            "warehouse_name",
            "name",
            "code",
            "is_active",
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

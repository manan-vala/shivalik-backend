from rest_framework import serializers

from .models import Rack, Section, Warehouse


class WarehouseSerializer(serializers.ModelSerializer):
    sections_count = serializers.IntegerField(read_only=True)

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


class SectionSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="warehouse.name", read_only=True)
    racks_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Section
        fields = [
            "id",
            "warehouse",
            "warehouse_name",
            "name",
            "code",
            "capacity",
            "current_stock",
            "is_active",
            "racks_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        capacity = attrs.get("capacity", getattr(self.instance, "capacity", 0))
        current_stock = attrs.get("current_stock", getattr(self.instance, "current_stock", 0))
        if current_stock > capacity:
            raise serializers.ValidationError({"current_stock": "Current stock cannot exceed section capacity."})
        return attrs


class RackSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="section.warehouse.name", read_only=True)
    section_name = serializers.CharField(source="section.name", read_only=True)

    class Meta:
        model = Rack
        fields = [
            "id",
            "section",
            "warehouse_name",
            "section_name",
            "name",
            "code",
            "capacity",
            "current_stock",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def validate(self, attrs):
        capacity = attrs.get("capacity", getattr(self.instance, "capacity", 0))
        current_stock = attrs.get("current_stock", getattr(self.instance, "current_stock", 0))
        if current_stock > capacity:
            raise serializers.ValidationError({"current_stock": "Current stock cannot exceed rack capacity."})
        return attrs
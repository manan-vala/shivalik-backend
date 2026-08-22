"""Serializers for suppliers and purchase orders. **Owner: Team C.**"""

from rest_framework import serializers

from ..models import Vendor, PurchaseOrder, PurchaseOrderLine


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = [
            "id",
            "company_name",
            "vendor_name",
            "gst_number",
            "contact_person",
            "phone",
            "email",
            "address",
            "categories_supplied",
            "expected_delivery_days",
            "payment_terms",
            "notes",
            "is_blocked",
            "blocked_at",
            "unblocked_at",
        ]
        read_only_fields = ["is_blocked", "blocked_at", "unblocked_at"]


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    book_title = serializers.CharField(source="book.title", read_only=True)
    isbn = serializers.CharField(source="book.isbn", read_only=True)

    class Meta:
        model = PurchaseOrderLine
        fields = [
            "id",
            "book",
            "book_title",
            "isbn",
            "quantity_ordered",
            "quantity_received",
            "unit_price",
        ]
        read_only_fields = ["quantity_received"]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.company_name", read_only=True)
    created_by_name = serializers.CharField(source="created_by.name", read_only=True, default=None)
    lines = PurchaseOrderLineSerializer(many=True, required=False)

    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "vendor",
            "vendor_name",
            "status",
            "order_date",
            "expected_delivery_date",
            "dispatched_at",
            "received_at",
            "created_by",
            "created_by_name",
            "notes",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["status", "dispatched_at", "received_at", "created_by", "created_at", "updated_at"]

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        validated_data["created_by"] = self.context["request"].user
        po = PurchaseOrder.objects.create(**validated_data)
        for line_data in lines_data:
            PurchaseOrderLine.objects.create(purchase_order=po, **line_data)
        return po

    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                PurchaseOrderLine.objects.create(purchase_order=instance, **line_data)
        return instance

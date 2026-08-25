"""Serializers for suppliers and purchase orders. **Owner: Team C.**"""

import re
from rest_framework import serializers

from ..models import Vendor, PurchaseOrder, PurchaseOrderLine


class VendorSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=False, allow_blank=True)
    purchase_orders_count = serializers.IntegerField(read_only=True)
    last_delivery_date = serializers.DateTimeField(read_only=True)

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
            "purchase_orders_count",
            "last_delivery_date",
        ]
        read_only_fields = ["is_blocked", "blocked_at", "unblocked_at", "purchase_orders_count", "last_delivery_date"]

    def validate_phone(self, value: str) -> str:
        if value and not re.match(r'^\+?1?\d{9,15}$', value):
            raise serializers.ValidationError("Enter a valid phone number.")
        return value

    def validate_gst_number(self, value: str) -> str:
        if value and not re.match(r'^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$', value):
            raise serializers.ValidationError("Enter a valid GSTIN.")
        return value


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
        read_only_fields = ["dispatched_at", "received_at", "created_by", "created_at", "updated_at"]

    def validate(self, attrs):
        if not self.instance:
            if 'status' in attrs and attrs['status'] not in [PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.PLACED]:
                raise serializers.ValidationError({"status": "New purchase orders must be created as DRAFT or PLACED."})

        if self.instance:
            old_status = self.instance.status
            
            if 'status' in attrs:
                new_status = attrs['status']
                if new_status != old_status:
                    if new_status in [PurchaseOrder.Status.DISPATCHED, PurchaseOrder.Status.RECEIVED]:
                        raise serializers.ValidationError({"status": f"Cannot manually transition to {new_status}. Use dedicated endpoints."})
                    
                    valid_transitions = {
                        PurchaseOrder.Status.DRAFT: [PurchaseOrder.Status.PLACED, PurchaseOrder.Status.CANCELLED],
                        PurchaseOrder.Status.PLACED: [PurchaseOrder.Status.CANCELLED],
                        PurchaseOrder.Status.DISPATCHED: [PurchaseOrder.Status.CANCELLED],
                        PurchaseOrder.Status.RECEIVED: [],
                        PurchaseOrder.Status.CANCELLED: [],
                    }
                    if new_status not in valid_transitions.get(old_status, []):
                        raise serializers.ValidationError({"status": f"Cannot transition status from {old_status} to {new_status}."})
            
            if 'lines' in attrs:
                if old_status not in [PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.PLACED]:
                    raise serializers.ValidationError({"lines": "Cannot modify line items unless order is in DRAFT or PLACED state."})
                    
        return attrs

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

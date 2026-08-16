"""Serializers for suppliers and purchase orders. **Owner: Team C.**"""

from rest_framework import serializers

from ..models import Vendor


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

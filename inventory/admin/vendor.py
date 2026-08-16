"""Admin for suppliers and purchase orders. **Owner: Team C.**"""

from django.contrib import admin

from ..models import PurchaseOrder, PurchaseOrderLine, Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "company_name",
        "vendor_name",
        "gst_number",
        "contact_person",
        "phone",
        "is_blocked",
    )
    list_filter = ("is_blocked",)
    search_fields = ("company_name", "vendor_name", "gst_number", "contact_person")


class PurchaseOrderLineInline(admin.TabularInline):
    model = PurchaseOrderLine
    extra = 0
    autocomplete_fields = ("book",)


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "vendor",
        "status",
        "order_date",
        "expected_delivery_date",
        "received_at",
        "created_by",
    )
    list_filter = ("status", "vendor")
    search_fields = ("vendor__company_name", "notes")
    autocomplete_fields = ("vendor",)
    inlines = [PurchaseOrderLineInline]
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("vendor", "created_by")

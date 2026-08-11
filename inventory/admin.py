"""Django admin registrations for the Inventory Module.

Keeps the columns dense enough to seed and audit test data quickly without
having to reach for the shell or Postman.
"""

from django.contrib import admin

from .models import Book, BookInventory, Rack, Section, Vendor, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "warehouse",
        "max_capacity",
        "current_stock",
        "last_change_date",
    )
    list_filter = ("warehouse",)
    search_fields = ("name", "warehouse__name")
    autocomplete_fields = ("warehouse", "updated_by")


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "section", "last_used")
    list_filter = ("section__warehouse", "section")
    search_fields = ("name", "section__name")
    autocomplete_fields = ("section",)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("id", "company_name", "vendor_name", "gst_number", "is_blocked")
    list_filter = ("is_blocked",)
    search_fields = ("company_name", "vendor_name", "gst_number")


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "isbn", "min_stock", "low_selling")
    list_filter = ("low_selling",)
    search_fields = ("title", "isbn")


@admin.register(BookInventory)
class BookInventoryAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "book",
        "rack",
        "vendor",
        "in_entry",
        "out_entry",
        "curr_stock",
    )
    list_filter = ("vendor", "rack__section__warehouse")
    search_fields = ("book__title", "book__isbn", "rack__name")
    autocomplete_fields = ("book", "rack", "vendor")
    readonly_fields = ("in_entry", "out_entry", "curr_stock")

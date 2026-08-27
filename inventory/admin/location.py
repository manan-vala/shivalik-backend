"""Admin for the storage hierarchy. **Owner: Team A.**"""

from django.contrib import admin

from ..models import Rack, Section, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "code", "location", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "code", "location")


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    # Capacity lives on Rack; the section totals shown here are
    # annotated, so they cannot disagree with the racks underneath.
    list_display = (
        "id",
        "name",
        "code",
        "warehouse",
        "max_capacity",
        "current_stock",
        "is_active",
    )
    list_filter = ("is_active", "warehouse")
    search_fields = ("name", "code", "warehouse__name", "warehouse__code")
    autocomplete_fields = ("warehouse",)

    def get_queryset(self, request):
        return super().get_queryset(request).with_rack_totals()

    @admin.display(description="Max capacity", ordering="max_capacity")
    def max_capacity(self, obj):
        return obj.max_capacity

    @admin.display(description="Current stock", ordering="current_stock")
    def current_stock(self, obj):
        return obj.current_stock


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "code",
        "section",
        "max_capacity",
        "current_stock",
        "is_active",
        "last_used",
        "last_change_date",
        "updated_by",
    )
    list_filter = ("is_active", "section__warehouse", "section")
    search_fields = ("name", "code", "section__name", "section__warehouse__name")
    autocomplete_fields = ("section",)
    # Written by adjust_stock() inside the movement engine's transaction —
    # hand-editing them here would desync the rack from the ledger.
    readonly_fields = ("current_stock", "last_change_date", "last_used", "updated_by")

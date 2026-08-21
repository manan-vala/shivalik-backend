"""Admin for the stock ledger. **Owner: Team B.**"""

from django.contrib import admin

from ..models import BookInventory, StockMovement


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
        "last_out_at",
    )
    list_filter = ("vendor", "rack__section__warehouse")
    search_fields = ("book__title", "book__isbn", "rack__name")
    autocomplete_fields = ("book", "rack", "vendor")
    # Counters are a projection of the movement log — hand-editing them here
    # is exactly the drift the ledger exists to prevent.
    readonly_fields = ("in_entry", "out_entry", "curr_stock", "last_out_at")

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("book", "vendor", "rack__section__warehouse")
        )


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """
    Read-only by construction: the movement log is append-only, and the admin
    is the one place someone could plausibly "fix" a row by hand. Adding,
    editing and deleting are all refused — a wrong movement is corrected by
    posting a compensating ADJUSTMENT, which is what an audit trail means.
    """

    list_display = (
        "id",
        "created_at",
        "movement_type",
        "quantity",
        "balance_after",
        "book",
        "rack",
        "actor",
    )
    list_filter = ("movement_type", "rack__section__warehouse", "created_at")
    search_fields = ("book__title", "book__isbn", "rack__name", "reason")
    date_hierarchy = "created_at"

    def get_queryset(self, request):
        return (
            super().get_queryset(request)
            .select_related("book", "rack", "vendor", "actor", "purchase_order")
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

"""Admin for the book catalog. **Owner: Team B.**"""

from django.contrib import admin

from ..models import Book


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "isbn",
        "author",
        "class_level",
        "board",
        "subject",
        "mrp",
        "min_stock",
        "low_selling",
    )
    list_filter = ("low_selling", "board", "class_level", "language")
    search_fields = ("title", "isbn", "author", "publisher")
    autocomplete_fields = ("default_warehouse", "default_section", "default_rack")
    fieldsets = (
        (None, {
            "fields": ("title", "isbn", "author", "publisher", "edition",
                       "language", "description", "cover_image"),
        }),
        ("Category", {"fields": ("class_level", "board", "subject")}),
        ("Pricing (INR)", {
            "fields": ("mrp", "tax_percent", "default_discount_percent"),
        }),
        ("Default storage", {
            "fields": ("default_warehouse", "default_section", "default_rack"),
        }),
        ("Thresholds", {
            "fields": ("min_stock", "dead_stock_threshold_days", "low_selling"),
        }),
    )

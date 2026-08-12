"""
Inventory domain models.

Covers the minimum entity chain required to expose the `books` slice of the
Inventory Module:

    Warehouse -> Section -> Rack -> BookInventory <- Book
                                          ^
                                          |
                                        Vendor

Derived values (deficit, needs_reorder, rack_location, ...) are computed at
the serializer layer to keep persisted state minimal and unambiguous.
"""

from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base that stamps every row with created/updated timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Location hierarchy
# ---------------------------------------------------------------------------


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Section(TimeStampedModel):
    warehouse = models.ForeignKey(
        Warehouse,
        related_name="sections",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=150)
    max_capacity = models.PositiveIntegerField(default=0)
    current_stock = models.PositiveIntegerField(default=0)
    last_change_date = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sections_updated",
    )

    class Meta:
        ordering = ["warehouse__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "name"],
                name="uniq_section_name_per_warehouse",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.warehouse.name} / {self.name}"


class Rack(TimeStampedModel):
    section = models.ForeignKey(
        Section,
        related_name="racks",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=150)
    last_used = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["section__warehouse__name", "section__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "name"],
                name="uniq_rack_name_per_section",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.section} / {self.name}"


# ---------------------------------------------------------------------------
# Suppliers and catalog
# ---------------------------------------------------------------------------


class Vendor(TimeStampedModel):
    company_name = models.CharField(max_length=200)
    vendor_name = models.CharField(max_length=150)
    gst_number = models.CharField(max_length=32, unique=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    categories_supplied = models.CharField(max_length=255, blank=True)
    expected_delivery_time = models.CharField(max_length=100, blank=True)
    payment_terms = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    is_blocked = models.BooleanField(default=False)

    class Meta:
        ordering = ["company_name"]

    def __str__(self) -> str:
        return f"{self.company_name} ({self.vendor_name})"


class Book(TimeStampedModel):
    title = models.CharField(max_length=255)
    isbn = models.CharField(max_length=20, unique=True)
    author = models.CharField(max_length=255, blank=True)
    publisher = models.CharField(max_length=255, blank=True)
    edition = models.CharField(max_length=50, blank=True)
    language = models.CharField(max_length=50, blank=True)
    category = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    tax = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    min_stock = models.PositiveIntegerField(
        default=0,
        help_text="Low-stock threshold. If curr_stock drops below this, the book "
                  "is flagged for re-order.",
    )
    low_selling = models.BooleanField(
        default=False,
        help_text="Set by the sales-analytics job; drives promotional campaigns.",
    )

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return f"{self.title} ({self.isbn})"


# ---------------------------------------------------------------------------
# Core inventory ledger
# ---------------------------------------------------------------------------


class BookInventory(TimeStampedModel):
    """
    Per-(book, rack) stock ledger.

    `in_entry` / `out_entry` are lifetime counters; `curr_stock` is the live
    balance and is mutated through the `stock-in` / `stock-out` view actions
    inside an atomic transaction — never edited by hand.
    """

    book = models.ForeignKey(
        Book,
        related_name="inventory_records",
        on_delete=models.PROTECT,
    )
    rack = models.ForeignKey(
        Rack,
        related_name="inventory_records",
        on_delete=models.PROTECT,
    )
    vendor = models.ForeignKey(
        Vendor,
        related_name="inventory_records",
        on_delete=models.PROTECT,
    )

    in_entry = models.PositiveIntegerField(default=0)
    out_entry = models.PositiveIntegerField(default=0)
    curr_stock = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["book__title", "rack__name"]
        verbose_name_plural = "Book inventory"
        constraints = [
            models.UniqueConstraint(
                fields=["book", "rack"],
                name="uniq_book_per_rack",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.book.title} @ {self.rack} — {self.curr_stock}"
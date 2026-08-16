"""
The book catalog.

**Owner: Team B (Inventory).**

Q4 answered: category is structured as ``class_level`` + ``board`` +
``subject``, not one free-text field — the Figma card renders "CLASS 12 • CBSE"
as two dimensions, and the persona's pain point is managing stock *across*
categories, which a typo-prone text field cannot support.

Q5 answered: money is INR, stored as ``Decimal``. Never ``FloatField`` — a
binary float cannot represent ₹0.10 exactly and the error compounds across a
purchase order.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from .base import TimeStampedModel


class Book(TimeStampedModel):
    # -- identity ----------------------------------------------------------
    title = models.CharField(max_length=255, db_index=True)
    isbn = models.CharField(max_length=20, unique=True)
    author = models.CharField(max_length=200, blank=True)
    publisher = models.CharField(max_length=200, blank=True)
    edition = models.CharField(max_length=50, blank=True)
    language = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    cover_image = models.ImageField(upload_to="books/covers/", blank=True, null=True)

    # -- category (Q4) -----------------------------------------------------
    class_level = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text='e.g. "Class 12". Rendered as the first half of the Figma card tag.',
    )
    board = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        help_text='e.g. "CBSE".',
    )
    subject = models.CharField(max_length=100, blank=True, db_index=True)

    # -- pricing (Q5 — INR) ------------------------------------------------
    mrp = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Maximum retail price in INR. Null until priced; the "
                  "register-book serializer requires it.",
    )
    tax_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    default_discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    # -- default storage location -----------------------------------------
    # Where new stock of this title goes unless the operator picks elsewhere.
    # SET_NULL, not PROTECT: deleting a rack should not be blocked by a
    # preference, unlike a ledger row which must never be orphaned.
    default_warehouse = models.ForeignKey(
        "inventory.Warehouse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_books",
    )
    default_section = models.ForeignKey(
        "inventory.Section",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_books",
    )
    default_rack = models.ForeignKey(
        "inventory.Rack",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_books",
    )

    # -- thresholds & flags ------------------------------------------------
    min_stock = models.PositiveIntegerField(
        default=0,
        help_text="Low-stock threshold. If curr_stock drops below this, the book "
                  "is flagged for re-order.",
    )
    dead_stock_threshold_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Per-title override of settings.DEAD_STOCK_DEFAULT_DAYS. "
                  "Q9: dead stock is computed on read, never stored.",
    )
    low_selling = models.BooleanField(
        default=False,
        help_text="Set by the sales-analytics job; drives promotional campaigns.",
    )

    class Meta:
        ordering = ["title"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(mrp__gte=0) | models.Q(mrp__isnull=True),
                name="book_mrp_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(tax_percent__gte=0) & models.Q(tax_percent__lte=100),
                name="book_tax_percent_in_range",
            ),
            models.CheckConstraint(
                condition=models.Q(default_discount_percent__gte=0)
                & models.Q(default_discount_percent__lte=100),
                name="book_discount_percent_in_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.title} ({self.isbn})"

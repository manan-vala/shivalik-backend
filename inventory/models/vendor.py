"""
Suppliers and purchase orders.

**Owner: Team C (Vendor).**

Q8 answered: a purchase order is a **header plus lines**. The ERD's
``PurchaseOrder(book_id, vendor_id)`` sketches the relationship, not the
document — one PO per title is not how any warehouse orders.

Q6 (how to store ``categories_supplied``) is Team C's alone. It is landed here
as a ``JSONField`` so the Day-3 schema is complete; swapping it for a Postgres
``ArrayField`` is a one-line migration if Team C prefers that.
"""

from django.conf import settings
from django.db import models

from .base import TimeStampedModel


class Vendor(TimeStampedModel):
    company_name = models.CharField(max_length=200)
    vendor_name = models.CharField(max_length=150)
    gst_number = models.CharField(max_length=32, unique=True)

    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)

    categories_supplied = models.JSONField(
        default=list,
        blank=True,
        help_text='List of category strings, e.g. ["Fiction", "Self-Help"]. '
                  "The UI collects them comma-separated.",
    )
    expected_delivery_days = models.PositiveIntegerField(null=True, blank=True)
    payment_terms = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    is_blocked = models.BooleanField(default=False, db_index=True)
    blocked_at = models.DateTimeField(null=True, blank=True)
    unblocked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["company_name"]

    def __str__(self) -> str:
        return f"{self.company_name} ({self.vendor_name})"


class PurchaseOrder(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PLACED = "PLACED", "Placed"
        DISPATCHED = "DISPATCHED", "Dispatched"
        RECEIVED = "RECEIVED", "Received"
        CANCELLED = "CANCELLED", "Cancelled"

    vendor = models.ForeignKey(
        Vendor,
        related_name="purchase_orders",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    order_date = models.DateField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders_created",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"PO-{self.pk} {self.vendor.company_name} ({self.status})"


class PurchaseOrderLine(TimeStampedModel):
    """One title on a purchase order."""

    purchase_order = models.ForeignKey(
        PurchaseOrder,
        related_name="lines",
        on_delete=models.CASCADE,  # a line has no meaning without its order
    )
    book = models.ForeignKey(
        "inventory.Book",
        related_name="purchase_order_lines",
        on_delete=models.PROTECT,
    )
    quantity_ordered = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["purchase_order", "book__title"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity_ordered__gte=1),
                name="po_line_quantity_ordered_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0),
                name="po_line_unit_price_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.book.title} x{self.quantity_ordered}"

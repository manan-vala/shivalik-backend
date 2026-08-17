"""
The stock ledger and the single write path into it.

**Owner: Team B (Inventory).**

`BookInventory` is the live balance per (book, rack). `StockMovement` — added
once Q7 was answered — is the append-only record of every individual change,
of which those balances are a projection.

> 🚨 Nothing writes stock except `apply_stock_movement()`. Not Team A, not
> Team C, not Team B. Any code that calls `BookInventory.objects.update()`
> directly puts the ledger and the movement log permanently out of step, and
> nobody notices until reconciliation weeks later.
"""

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .base import TimeStampedModel


class InsufficientStockError(Exception):
    """
    Raised by `apply_stock_movement` when an outbound movement exceeds the
    stock actually on the rack.

    A domain exception rather than a DRF one, because the engine is called
    from Team C's purchase-order code as well as from HTTP views. Each caller
    translates it — the stock-out endpoint owes a 400 with
    ``{"detail": "Insufficient stock on the specified rack."}``.
    """

    def __init__(self, available: int, requested: int):
        self.available = available
        self.requested = requested
        super().__init__(
            f"Insufficient stock: {available} available, {requested} requested."
        )


class MovementType(models.TextChoices):
    """
    Every way stock can move.

    Direction is carried by the *type*, so `quantity` is always positive.
    That is why `ADJUSTMENT` is split in two: a single `ADJUSTMENT` value
    cannot express "correct this down by three", which is the most common
    adjustment there is.
    """

    # Inbound
    IN = "IN", "Stock in"
    RECEIVE = "RECEIVE", "Purchase order receipt"
    RETURN_IN = "RETURN_IN", "Return to stock"
    ADJUSTMENT_IN = "ADJUSTMENT_IN", "Adjustment (increase)"
    # Outbound
    OUT = "OUT", "Stock out"
    WRITE_OFF = "WRITE_OFF", "Write off"
    ADJUSTMENT_OUT = "ADJUSTMENT_OUT", "Adjustment (decrease)"


#: Types that add stock. A rack-to-rack transfer is deliberately *not* a type:
#: it is an OUT from one rack and an IN to another, so both racks' counters
#: stay derivable from the log.
INBOUND_TYPES = frozenset({
    MovementType.IN,
    MovementType.RECEIVE,
    MovementType.RETURN_IN,
    MovementType.ADJUSTMENT_IN,
})

#: Types that remove stock.
OUTBOUND_TYPES = frozenset({
    MovementType.OUT,
    MovementType.WRITE_OFF,
    MovementType.ADJUSTMENT_OUT,
})

#: Types that must carry a `reason`. An unexplained correction to a money
#: -adjacent ledger is indistinguishable from a mistake.
REASON_REQUIRED_TYPES = frozenset({
    MovementType.ADJUSTMENT_IN,
    MovementType.ADJUSTMENT_OUT,
    MovementType.WRITE_OFF,
})


def signed_delta(movement_type: str, quantity: int) -> int:
    """Turn a (type, positive quantity) pair into the signed change."""
    if movement_type in INBOUND_TYPES:
        return quantity
    if movement_type in OUTBOUND_TYPES:
        return -quantity
    raise ValueError(f"Unknown movement type: {movement_type!r}")


class BookInventory(TimeStampedModel):
    """
    Per-(book, rack) stock ledger.

    `in_entry` / `out_entry` are lifetime counters — they only ever increase.
    `curr_stock` is the live balance. All three are mutated exclusively by
    `apply_stock_movement`, inside a transaction, behind a row lock.
    """

    book = models.ForeignKey(
        "inventory.Book",
        related_name="inventory_records",
        on_delete=models.PROTECT,
    )
    rack = models.ForeignKey(
        "inventory.Rack",
        related_name="inventory_records",
        on_delete=models.PROTECT,
    )
    vendor = models.ForeignKey(
        "inventory.Vendor",
        related_name="inventory_records",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Last supplier seen for this (book, rack). Nullable because "
                  "vendor is a property of a purchase, not of a shelf "
                  "(finding M-7) — the authoritative attribution is on "
                  "StockMovement and PurchaseOrder.",
    )

    in_entry = models.PositiveIntegerField(default=0)
    out_entry = models.PositiveIntegerField(default=0)
    curr_stock = models.PositiveIntegerField(default=0)

    last_out_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When stock last left this rack. Drives dead-stock ageing; "
                  "falls back to created_at for stock that never moved.",
    )

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


class StockMovement(TimeStampedModel):
    """
    One immutable row per stock change. Append only: never edited, never
    deleted. `BookInventory`'s counters are a projection of this table and
    must be reconcilable against it.

    Nothing enforces immutability at the database level — that would need a
    Postgres rule or trigger outside Django's migration graph. It is enforced
    by there being no update/delete route, and by the admin registering this
    model read-only. Keep it that way.
    """

    book = models.ForeignKey(
        "inventory.Book",
        related_name="movements",
        on_delete=models.PROTECT,
    )
    rack = models.ForeignKey(
        "inventory.Rack",
        related_name="movements",
        on_delete=models.PROTECT,
    )
    vendor = models.ForeignKey(
        "inventory.Vendor",
        related_name="movements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Set on incoming stock only.",
    )
    purchase_order = models.ForeignKey(
        "inventory.PurchaseOrder",
        related_name="movements",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        help_text="Set when the movement came from receiving a PO.",
    )

    movement_type = models.CharField(
        max_length=20,
        choices=MovementType.choices,
        db_index=True,
    )
    quantity = models.PositiveIntegerField(
        help_text="Always positive. Direction comes from movement_type.",
    )
    balance_after = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="BookInventory.curr_stock immediately after this movement, "
                  "recorded under the same lock. Makes reconciliation a "
                  "single comparison instead of a replay. Null only on rows "
                  "backfilled as opening balances.",
    )

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
        help_text="Who performed it. SET_NULL so history survives an employee "
                  "being deleted.",
    )
    reason = models.TextField(
        blank=True,
        help_text="Required for adjustments and write-offs.",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            # `books/{id}/history/` and the dead-stock scan.
            models.Index(fields=["book", "-created_at"], name="stockmove_book_created"),
            models.Index(fields=["rack", "-created_at"], name="stockmove_rack_created"),
            # `in-entries/` / `out-entries/` filter on type before ordering.
            models.Index(
                fields=["movement_type", "-created_at"],
                name="stockmove_type_created",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="stockmovement_quantity_positive",
            ),
            models.CheckConstraint(
                condition=~(
                    models.Q(movement_type__in=sorted(REASON_REQUIRED_TYPES))
                    & models.Q(reason="")
                ),
                name="stockmovement_reason_required",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.movement_type} {self.quantity} × {self.book.title}"

    @property
    def delta(self) -> int:
        """Signed effect of this movement on `curr_stock`."""
        return signed_delta(self.movement_type, self.quantity)


# ---------------------------------------------------------------------------
# The movement engine
# ---------------------------------------------------------------------------


def _lock_or_create_inventory_row(*, book, rack, vendor):
    """
    Return the `BookInventory` row for `(book, rack)`, locked with
    `select_for_update()`.

    `select_for_update()` cannot lock a row that does not exist yet, so two
    concurrent *first* movements for the same `(book, rack)` can both miss the
    lookup below and both try to insert — `uniq_book_per_rack` then turns the
    loser's insert into an `IntegrityError` instead of a lock wait.
    `get_or_create` alone does not fix this; it has the same race inside it.
    The nested `atomic()` block turns the loser's failure into a savepoint
    rollback rather than poisoning the caller's transaction, so re-selecting
    afterwards picks up the winner's row — by then it exists, and the lock
    acquires normally instead of racing again.
    """
    try:
        return BookInventory.objects.select_for_update().get(book=book, rack=rack)
    except BookInventory.DoesNotExist:
        pass

    try:
        with transaction.atomic():
            return BookInventory.objects.create(book=book, rack=rack, vendor=vendor)
    except IntegrityError:
        return BookInventory.objects.select_for_update().get(book=book, rack=rack)


@transaction.atomic
def apply_stock_movement(*, book, rack, quantity, movement_type, actor,
                         vendor=None, purchase_order=None, reason=""):
    """
    The single path for ALL stock changes. Runs in one atomic transaction.

    Updates BookInventory (curr_stock, in_entry/out_entry), calls
    rack.adjust_stock(), and writes one StockMovement row.

    Returns the refreshed `BookInventory` row — `curr_stock` is a plain
    integer, not an unresolved `F()` expression, so callers and their
    response shapes do not need to know an `F()` update ran underneath.

    Raises `InsufficientStockError` when an outbound movement exceeds the
    stock actually on the rack, and DRF's `ValidationError` for anything else
    the request got wrong: an unknown movement type, a blocked vendor, a
    missing reason on an adjustment or write-off, or a non-positive quantity.
    The sufficiency check runs *inside* the row lock acquired below —
    check-then-update in one critical section is the whole fix for `H-1`;
    checking before the transaction, as the old view code did, is the bug
    this replaces.

    Enforced here rather than in a serializer, because Team C's purchase-order
    receive calls this function directly with no serializer in front of it.
    Every guard below therefore has to turn a caller's mistake into a 400 —
    the database constraints behind them raise `IntegrityError`, which DRF
    reports as a 500 (playbook §5.3).
    """
    if quantity < 1:
        raise ValidationError({"quantity": "Quantity must be at least 1."})

    # `signed_delta` raises ValueError on an unknown type — correct for a
    # pure function, but a 500 through DRF. Translated here, at the boundary
    # three teams call, rather than changing `signed_delta`'s own contract.
    if movement_type not in INBOUND_TYPES | OUTBOUND_TYPES:
        raise ValidationError({
            "movement_type": f"Unknown movement type: {movement_type!r}.",
        })

    # `StockMovement.reason` is NOT NULL with a "" default; a caller passing
    # None (e.g. forwarding a nullable note field) would otherwise reach the
    # database and 500.
    reason = reason or ""

    if movement_type in REASON_REQUIRED_TYPES and not reason:
        raise ValidationError({
            "reason": "A reason is required for adjustments and write-offs.",
        })

    if vendor is not None and vendor.is_blocked:
        raise ValidationError({"vendor": "Vendor is blocked."})

    delta = signed_delta(movement_type, quantity)
    is_inbound = delta > 0

    record = _lock_or_create_inventory_row(
        book=book, rack=rack, vendor=vendor if is_inbound else None,
    )

    if not is_inbound and record.curr_stock < quantity:
        raise InsufficientStockError(available=record.curr_stock, requested=quantity)

    update_fields = {"curr_stock": F("curr_stock") + delta}
    if is_inbound:
        update_fields["in_entry"] = F("in_entry") + quantity
        # "Last supplier seen" (see the field's help_text) — only overwritten
        # when this movement actually names one, so an unattributed receipt
        # does not erase a vendor already on record.
        if vendor is not None:
            update_fields["vendor"] = vendor
    else:
        update_fields["out_entry"] = F("out_entry") + quantity
        update_fields["last_out_at"] = timezone.now()

    BookInventory.objects.filter(pk=record.pk).update(**update_fields)
    record.refresh_from_db()

    rack.adjust_stock(delta, actor)

    StockMovement.objects.create(
        book=book,
        rack=rack,
        vendor=vendor,
        purchase_order=purchase_order,
        movement_type=movement_type,
        quantity=quantity,
        balance_after=record.curr_stock,
        actor=actor,
        reason=reason,
    )

    return record

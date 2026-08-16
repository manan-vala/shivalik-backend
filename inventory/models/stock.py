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
from django.db import models

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


def apply_stock_movement(*, book, rack, quantity, movement_type, actor,
                         vendor=None, purchase_order=None, reason=""):
    """
    The single path for ALL stock changes. Runs in one atomic transaction.

    STUB — published on day 1 so Teams A and C can write real calls against a
    real signature. Team B fills in the body (their Task 2); no caller changes
    when they do.

    The contract callers may rely on:

    * Returns the updated `BookInventory` row, re-read after the update, so
      `curr_stock` is an integer and not an unresolved `F()` expression.
    * Raises `InsufficientStockError` when an outbound movement exceeds stock,
      and `rest_framework.exceptions.ValidationError` for anything the request
      itself got wrong (blocked vendor, missing reason, rack overflow).
    * Either everything lands or nothing does: the balance update, the
      `rack.adjust_stock()` call and the `StockMovement` row share one
      transaction.
    * `quantity` is always positive; direction comes from `movement_type`
      (see `signed_delta`).

    The body, when written, must — all inside `@transaction.atomic`:

    1. Lock the `BookInventory` row with `select_for_update()`. This is why Q2
       had to be PostgreSQL: the lock is a silent no-op on SQLite.
    2. Check sufficiency *inside* that lock. Check-then-update in one critical
       section is the whole fix for `H-1`; checking before the transaction is
       the bug.
    3. Update `curr_stock` and `in_entry`/`out_entry` with `F()` expressions,
       and stamp `last_out_at` on outbound movements.
    4. Call `rack.adjust_stock(delta, actor)`.
    5. Write exactly one `StockMovement` row, including `balance_after`.
    6. Enforce the invariants that cannot live in a serializer, because this
       function is also called directly from Python: blocked vendors, and
       `reason` being mandatory for `REASON_REQUIRED_TYPES`.

    Two traps worth writing a test for before writing the code:

    * `select_for_update()` cannot lock a row that does not exist yet. Two
      concurrent first-ever movements for the same (book, rack) both miss,
      both insert, and `uniq_book_per_rack` turns one into a 500. Catch
      `IntegrityError` and re-select.
    * `curr_stock` is a `PositiveIntegerField`, so underflow raises
      `IntegrityError`, not a validation error. The guard in step 2 is what
      keeps that a clean 400.
    """
    raise NotImplementedError(
        "Team B, Task 2 — pair on this one, then get a whole-team review."
    )

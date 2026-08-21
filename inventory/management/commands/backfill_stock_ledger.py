"""
Team B, Task 7 — write existing `BookInventory` balances back into the
ledger as opening-balance rows.

`StockMovement` starts empty on every environment that had stock before the
movement engine existed. Until those balances are represented as rows,
`books/{id}/history/` cannot reconcile against `curr_stock` for any
pre-existing stock, which defeats the point of adopting the log.

A management command, not a data migration: it needs to be safely re-runnable
(a fresh environment, or one seeded before this landed, may need it run more
than once as more pre-engine data surfaces) and testable with `call_command`,
neither of which a migration gives you for free — and a bug found later is a
code fix here, not a second migration to correct the first.

**Deliberately bypasses `apply_stock_movement()`.** That engine updates
`BookInventory.curr_stock` and calls `rack.adjust_stock()` — exactly what
must *not* happen here, because both already hold the correct value this
command is trying to *explain*, not change. This is the one sanctioned
exception to "nothing writes stock except the engine": it writes history,
never balance.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Exists, OuterRef

from inventory.models import BookInventory, MovementType, StockMovement

OPENING_BALANCE_REASON = "Opening balance (pre-ledger)"


def _rows_needing_backfill():
    """
    Every `BookInventory` row with stock that the ledger does not yet
    explain — `curr_stock > 0` and no `StockMovement` for that `(book, rack)`
    at all.

    "No movement yet", not "no movement matching our reason string": the
    point is to find stock nothing has ever accounted for, and a first real
    movement recorded before this command ever ran is just as much an
    explanation as a backfill row would be. This is also what makes the
    command idempotent — a second run finds nothing left to do.
    """
    has_movement = StockMovement.objects.filter(
        book=OuterRef("book"), rack=OuterRef("rack"),
    )
    return (
        BookInventory.objects
        .filter(curr_stock__gt=0)
        .annotate(has_movement=Exists(has_movement))
        .filter(has_movement=False)
        .select_related("book", "rack")
        .order_by("book__title", "rack__name")
    )


class Command(BaseCommand):
    help = (
        "Backfill StockMovement with one opening-balance row per "
        "BookInventory row that predates the movement engine."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List what would be created without writing anything.",
        )

    def handle(self, *args, dry_run=False, **kwargs):
        rows = list(_rows_needing_backfill())

        if not rows:
            self.stdout.write(self.style.SUCCESS("Nothing to backfill."))
            return

        for row in rows:
            self.stdout.write(
                f"  {row.book.title} @ {row.rack} — {row.curr_stock} unit(s)"
            )

        if dry_run:
            self.stdout.write(f"Would create {len(rows)} opening-balance row(s).")
            return

        movements = [
            StockMovement(
                book=row.book,
                rack=row.rack,
                movement_type=MovementType.ADJUSTMENT_IN,
                quantity=row.curr_stock,
                balance_after=None,  # reserved exactly for this case
                actor=None,
                reason=OPENING_BALANCE_REASON,
            )
            for row in rows
        ]
        with transaction.atomic():
            StockMovement.objects.bulk_create(movements)

        self.stdout.write(
            self.style.SUCCESS(f"Created {len(movements)} opening-balance row(s).")
        )

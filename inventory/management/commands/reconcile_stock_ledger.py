"""
The reconciliation command: recompute every stored stock number from the
ledger that is supposed to explain it, and report where they disagree.

Two independent checks, because there are two stored aggregates in the
schema and each can drift from its own source of truth for a different
reason:

* `BookInventory.curr_stock` should equal the signed sum of that
  `(book, rack)`'s `StockMovement` rows — this is what proves the backfill
  actually worked, and what would catch a bug in `apply_stock_movement()`
  itself.
* `Rack.current_stock` should equal `Sum(BookInventory.curr_stock)` across
  that rack — the other stored aggregate, and what would catch a bug in
  `Rack.adjust_stock()` specifically, one level up from the first check.

Reports only — it does not fix anything. Auto-correcting a stock number
outside `apply_stock_movement()` is exactly the "second writer" this whole
system exists to prevent; a real discrepancy is fixed with a human-reviewed
compensating `ADJUSTMENT` movement, not a script overwriting a column.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Case, F, IntegerField, Sum, When

from inventory.models import INBOUND_TYPES, BookInventory, Rack, StockMovement

_SIGNED_QUANTITY = Case(
    When(movement_type__in=INBOUND_TYPES, then=F("quantity")),
    default=-F("quantity"),
    output_field=IntegerField(),
)


def _ledger_totals_by_book_rack() -> dict[tuple[int, int], int]:
    """One aggregate query, not one query per `BookInventory` row."""
    rows = (
        StockMovement.objects
        .annotate(signed_quantity=_SIGNED_QUANTITY)
        .values("book_id", "rack_id")
        .annotate(total=Sum("signed_quantity"))
    )
    return {(row["book_id"], row["rack_id"]): row["total"] for row in rows}


def _ledger_totals_by_rack() -> dict[int, int]:
    rows = (
        BookInventory.objects
        .values("rack_id")
        .annotate(total=Sum("curr_stock"))
    )
    return {row["rack_id"]: row["total"] for row in rows}


class Command(BaseCommand):
    help = "Recompute BookInventory and Rack stock totals from the ledger and report drift."

    def handle(self, *args, **kwargs):
        drift_count = 0
        drift_count += self._check_book_inventory()
        drift_count += self._check_racks()

        if drift_count:
            raise CommandError(
                f"{drift_count} row(s) drifted from the ledger — see above."
            )
        self.stdout.write(self.style.SUCCESS("Ledger is reconciled. No drift found."))

    def _check_book_inventory(self) -> int:
        ledger_totals = _ledger_totals_by_book_rack()
        drifted = 0
        # `.iterator()` — this walks every ledger row, and the whole point of
        # the command is to be runnable against a full production warehouse.
        rows = BookInventory.objects.select_related("book", "rack").iterator()
        for inv in rows:
            computed = ledger_totals.get((inv.book_id, inv.rack_id), 0)
            if computed != inv.curr_stock:
                drifted += 1
                self.stdout.write(self.style.WARNING(
                    f"BookInventory #{inv.pk} ({inv.book.title} @ {inv.rack}): "
                    f"curr_stock={inv.curr_stock}, ledger says {computed} "
                    f"(diff {inv.curr_stock - computed:+d})"
                ))
        return drifted

    def _check_racks(self) -> int:
        ledger_totals = _ledger_totals_by_rack()
        drifted = 0
        for rack in Rack.objects.select_related("section__warehouse").iterator():
            computed = ledger_totals.get(rack.id, 0)
            if computed != rack.current_stock:
                drifted += 1
                self.stdout.write(self.style.WARNING(
                    f"Rack #{rack.pk} ({rack}): current_stock={rack.current_stock}, "
                    f"BookInventory says {computed} "
                    f"(diff {rack.current_stock - computed:+d})"
                ))
        return drifted

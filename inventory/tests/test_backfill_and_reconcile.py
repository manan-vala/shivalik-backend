"""
Team B, Task 7 — the ledger backfill and its reconciliation command.

`apply_stock_movement()` is used to build the "already has real history"
fixtures below, and plain `.create()`/`.update()` to build the "pre-engine"
fixtures — deliberately, since that is exactly the situation these commands
exist to detect and fix, and the one place in the whole suite it is correct
to write `BookInventory`/`Rack` state outside the engine.
"""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from inventory.management.commands.backfill_stock_ledger import OPENING_BALANCE_REASON
from inventory.models import (
    Book,
    BookInventory,
    MovementType,
    Rack,
    Section,
    StockMovement,
    Warehouse,
    apply_stock_movement,
)


class BackfillReconcileTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.warehouse = Warehouse.objects.create(name="Main")
        cls.section = Section.objects.create(warehouse=cls.warehouse, name="A")
        cls.rack = Rack.objects.create(section=cls.section, name="A-1", max_capacity=100)
        cls.book = Book.objects.create(title="Physics XII", isbn="9782000000001")

    @staticmethod
    def _run(command, *args, **kwargs):
        out, err = StringIO(), StringIO()
        try:
            call_command(command, *args, stdout=out, stderr=err, **kwargs)
            failed = None
        except CommandError as exc:
            failed = exc
        return out.getvalue(), failed

    def _seed_legacy_row(self, quantity: int):
        """A `BookInventory` row with stock but zero `StockMovement` rows —
        exactly what predates the engine."""
        Rack.objects.filter(pk=self.rack.pk).update(current_stock=quantity)
        return BookInventory.objects.create(
            book=self.book, rack=self.rack, curr_stock=quantity, in_entry=quantity,
        )


class BackfillCommandTests(BackfillReconcileTestCase):
    def test_creates_one_opening_balance_row_per_uncovered_book_rack(self):
        self._seed_legacy_row(25)

        out, failed = self._run("backfill_stock_ledger")

        self.assertIsNone(failed)
        self.assertIn("Created 1 opening-balance row(s)", out)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.movement_type, MovementType.ADJUSTMENT_IN)
        self.assertEqual(movement.quantity, 25)
        self.assertIsNone(movement.balance_after)
        self.assertIsNone(movement.actor)
        self.assertEqual(movement.reason, OPENING_BALANCE_REASON)

    def test_does_not_touch_bookinventory_or_rack(self):
        """
        The backfill explains existing numbers; it must never change them —
        that would be a second writer of the state `apply_stock_movement`
        owns.
        """
        record = self._seed_legacy_row(25)
        self._run("backfill_stock_ledger")

        record.refresh_from_db()
        self.rack.refresh_from_db()
        self.assertEqual(record.curr_stock, 25)
        self.assertEqual(self.rack.current_stock, 25)

    def test_zero_stock_rows_are_left_alone(self):
        BookInventory.objects.create(book=self.book, rack=self.rack, curr_stock=0)
        self._run("backfill_stock_ledger")
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_rows_with_real_history_are_not_touched(self):
        """
        A `(book, rack)` with even one real movement is not "pre-engine" —
        backfilling on top of it would double the ledger's account of it.
        """
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=10,
            movement_type=MovementType.IN, actor=None,
        )
        out, failed = self._run("backfill_stock_ledger")

        self.assertIsNone(failed)
        self.assertIn("Nothing to backfill", out)
        self.assertEqual(StockMovement.objects.count(), 1)  # only the real one

    def test_is_idempotent(self):
        self._seed_legacy_row(25)
        self._run("backfill_stock_ledger")
        self._run("backfill_stock_ledger")
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_dry_run_writes_nothing(self):
        self._seed_legacy_row(25)
        out, failed = self._run("backfill_stock_ledger", "--dry-run")

        self.assertIsNone(failed)
        self.assertIn("Would create 1 opening-balance row(s)", out)
        self.assertEqual(StockMovement.objects.count(), 0)


class ReconcileCommandTests(BackfillReconcileTestCase):
    def test_reports_clean_when_nothing_has_drifted(self):
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=10,
            movement_type=MovementType.IN, actor=None,
        )
        out, failed = self._run("reconcile_stock_ledger")

        self.assertIsNone(failed)
        self.assertIn("No drift found", out)

    def test_backfilling_is_what_makes_pre_engine_stock_reconcile(self):
        self._seed_legacy_row(25)

        _, failed_before = self._run("reconcile_stock_ledger")
        self.assertIsNotNone(failed_before)

        self._run("backfill_stock_ledger")

        _, failed_after = self._run("reconcile_stock_ledger")
        self.assertIsNone(failed_after)

    def test_detects_bookinventory_drift(self):
        self._seed_legacy_row(25)  # curr_stock=25, zero movements

        out, failed = self._run("reconcile_stock_ledger")

        self.assertIsNotNone(failed)
        self.assertIn("curr_stock=25", out)
        self.assertIn("ledger says 0", out)

    def test_detects_rack_drift_independently_of_bookinventory_drift(self):
        """
        A `BookInventory` row can reconcile against its own movements while
        the *rack's* stored total has still drifted from `Sum(BookInventory.
        curr_stock)` — a different stored aggregate, a different bug class.
        """
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=10,
            movement_type=MovementType.IN, actor=None,
        )
        Rack.objects.filter(pk=self.rack.pk).update(current_stock=50)

        out, failed = self._run("reconcile_stock_ledger")

        self.assertIsNotNone(failed)
        self.assertIn("current_stock=50", out)
        self.assertIn("BookInventory says 10", out)

    def test_command_error_is_only_raised_when_drift_exists(self):
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=10,
            movement_type=MovementType.IN, actor=None,
        )
        call_command("reconcile_stock_ledger")  # must not raise

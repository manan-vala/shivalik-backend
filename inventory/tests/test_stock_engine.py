"""
Behaviour tests for `apply_stock_movement`.

`inventory/tests/test_contracts.py` covers the *signature* (keyword-only,
defaults, "fails loudly"). This file covers what the body actually does, now
that it has one.

Most tests below patch `Rack.adjust_stock()` with a no-op double so the
engine's own correctness can be verified in isolation from Team A's file —
the same "test your own contract separately" split `test_contracts.py` uses.
`Rack.adjust_stock()` has since landed for real (see `test_rack_engine.py`
for its own tests); `EndToEndWithRealRackTests` below runs the engine against
the genuine implementation, unpatched, to prove the two actually integrate —
including the case only the real rack can produce: a movement that is fine
for `BookInventory` but exceeds the rack's own capacity.
"""

import threading
from unittest.mock import patch

import pytest
from django.db import connections
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import ValidationError

from inventory.models import (
    Book,
    BookInventory,
    InsufficientStockError,
    MovementType,
    Rack,
    Section,
    StockMovement,
    Vendor,
    Warehouse,
    apply_stock_movement,
)


def _noop_adjust_stock(self, delta, actor):
    """
    Stand-in for `Rack.adjust_stock()`, used to test the engine in isolation
    from it. `EndToEndWithRealRackTests` below runs against the real thing.
    """
    return


class StockEngineTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.warehouse = Warehouse.objects.create(name="Main")
        cls.section = Section.objects.create(warehouse=cls.warehouse, name="A")
        cls.rack = Rack.objects.create(section=cls.section, name="A-1", max_capacity=1000)
        cls.book = Book.objects.create(title="Physics XII", isbn="9780000000201")
        cls.vendor = Vendor.objects.create(
            company_name="Acme Books", vendor_name="Acme", gst_number="24AAACA0000A1Z1",
        )
        cls.blocked_vendor = Vendor.objects.create(
            company_name="Bad Co", vendor_name="Bad", gst_number="24AAACA0000A1Z2",
            is_blocked=True,
        )


@patch.object(Rack, "adjust_stock", _noop_adjust_stock)
class ApplyStockMovementTests(StockEngineTestCase):
    def test_stock_in_creates_the_row_and_writes_balance_after(self):
        record = apply_stock_movement(
            book=self.book, rack=self.rack, quantity=10,
            movement_type=MovementType.IN, actor=None, vendor=self.vendor,
        )
        self.assertEqual(record.curr_stock, 10)
        self.assertEqual(record.in_entry, 10)
        self.assertEqual(record.vendor, self.vendor)

        movement = StockMovement.objects.get()
        self.assertEqual(movement.movement_type, MovementType.IN)
        self.assertEqual(movement.quantity, 10)
        self.assertEqual(movement.balance_after, 10)
        self.assertEqual(movement.vendor, self.vendor)

    def test_stock_out_decrements_and_stamps_last_out_at(self):
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=10,
            movement_type=MovementType.IN, actor=None,
        )
        record = apply_stock_movement(
            book=self.book, rack=self.rack, quantity=4,
            movement_type=MovementType.OUT, actor=None,
        )
        self.assertEqual(record.curr_stock, 6)
        self.assertEqual(record.out_entry, 4)
        self.assertIsNotNone(record.last_out_at)

    def test_insufficient_stock_is_a_domain_error_and_writes_nothing(self):
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=5,
            movement_type=MovementType.IN, actor=None,
        )
        with self.assertRaises(InsufficientStockError) as ctx:
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=99,
                movement_type=MovementType.OUT, actor=None,
            )
        self.assertEqual(ctx.exception.available, 5)
        self.assertEqual(ctx.exception.requested, 99)

        record = BookInventory.objects.get(book=self.book, rack=self.rack)
        self.assertEqual(record.curr_stock, 5)
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_a_new_row_with_no_stock_cannot_be_stocked_out(self):
        """Insufficiency must be checked even when the row is created inline."""
        with self.assertRaises(InsufficientStockError):
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=1,
                movement_type=MovementType.OUT, actor=None,
            )
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_vendor_is_only_overwritten_on_a_named_receipt(self):
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=5,
            movement_type=MovementType.IN, actor=None, vendor=self.vendor,
        )
        record = apply_stock_movement(
            book=self.book, rack=self.rack, quantity=2,
            movement_type=MovementType.IN, actor=None,
        )
        self.assertEqual(record.vendor, self.vendor)

    def test_reason_supplied_lets_an_adjustment_through(self):
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=5,
            movement_type=MovementType.IN, actor=None,
        )
        record = apply_stock_movement(
            book=self.book, rack=self.rack, quantity=2,
            movement_type=MovementType.ADJUSTMENT_OUT, actor=None,
            reason="Damaged in transit.",
        )
        self.assertEqual(record.curr_stock, 3)

    def test_returns_a_plain_integer_not_an_f_expression(self):
        record = apply_stock_movement(
            book=self.book, rack=self.rack, quantity=3,
            movement_type=MovementType.IN, actor=None,
        )
        self.assertIsInstance(record.curr_stock, int)


class ApplyStockMovementValidationTests(StockEngineTestCase):
    """These fail before the row lock, so they run without patching Rack."""

    def test_blocked_vendor_is_rejected_and_nothing_is_written(self):
        with self.assertRaises(ValidationError):
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=1,
                movement_type=MovementType.IN, actor=None,
                vendor=self.blocked_vendor,
            )
        self.assertFalse(
            BookInventory.objects.filter(book=self.book, rack=self.rack).exists()
        )

    def test_reason_required_for_adjustment_and_write_off(self):
        for movement_type in (MovementType.ADJUSTMENT_IN, MovementType.WRITE_OFF):
            with self.assertRaises(ValidationError):
                apply_stock_movement(
                    book=self.book, rack=self.rack, quantity=1,
                    movement_type=movement_type, actor=None,
                )

    def test_non_positive_quantity_is_rejected(self):
        with self.assertRaises(ValidationError):
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=0,
                movement_type=MovementType.IN, actor=None,
            )

    def test_unknown_movement_type_is_a_400_not_a_500(self):
        """
        `signed_delta` raises ValueError, which DRF reports as a server
        error. The engine is a cross-team entry point called straight from
        Python, so a typo'd type has to come back as a validation failure.
        """
        with self.assertRaises(ValidationError):
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=1,
                movement_type="TELEPORT", actor=None,
            )


@patch.object(Rack, "adjust_stock", _noop_adjust_stock)
class ReasonNormalisationTests(StockEngineTestCase):
    def test_reason_none_is_stored_as_blank_not_null(self):
        """
        `StockMovement.reason` is NOT NULL with a "" default. A caller
        forwarding a nullable note field (`reason=po.notes`) would otherwise
        hit an IntegrityError → 500 on a movement that is otherwise valid.
        """
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=1,
            movement_type=MovementType.IN, actor=None, reason=None,
        )
        self.assertEqual(StockMovement.objects.get().reason, "")

    def test_reason_none_still_fails_the_types_that_require_one(self):
        with self.assertRaises(ValidationError):
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=1,
                movement_type=MovementType.ADJUSTMENT_IN, actor=None, reason=None,
            )


@patch.object(Rack, "adjust_stock")
class RackContractTests(StockEngineTestCase):
    """Pins the one contract Team A's real implementation must satisfy."""

    def test_calls_rack_adjust_stock_with_signed_delta_and_actor(self, mock_adjust):
        mock_adjust.return_value = None
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=7,
            movement_type=MovementType.IN, actor=None,
        )
        mock_adjust.assert_called_once_with(7, None)

    def test_a_failure_in_adjust_stock_rolls_back_the_whole_movement(self, mock_adjust):
        mock_adjust.side_effect = ValidationError("Rack is full.")
        with self.assertRaises(ValidationError):
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=5,
                movement_type=MovementType.IN, actor=None,
            )
        self.assertFalse(
            BookInventory.objects.filter(book=self.book, rack=self.rack).exists()
        )
        self.assertEqual(StockMovement.objects.count(), 0)


@pytest.mark.postgres_only
class MovementEngineConcurrencyTests(TransactionTestCase):
    """
    The test the engine exists to satisfy: two simultaneous stock-outs must
    not oversell. `TransactionTestCase`, not `TestCase` — `TestCase` wraps
    each test in a transaction that gets rolled back, so two "concurrent"
    writers never actually contend and this would pass no matter what the
    code does.
    """

    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Main")
        self.section = Section.objects.create(warehouse=self.warehouse, name="A")
        self.rack = Rack.objects.create(section=self.section, name="A-1", max_capacity=1000)
        self.book = Book.objects.create(title="Physics XII", isbn="9780000000202")
        # Seed directly rather than through the engine: setUp runs outside
        # the per-test Rack.adjust_stock patch below.
        BookInventory.objects.create(book=self.book, rack=self.rack, curr_stock=10, in_entry=10)

    def _stock_out(self, results, index):
        try:
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=6,
                movement_type=MovementType.OUT, actor=None,
            )
            results[index] = "ok"
        except InsufficientStockError:
            results[index] = "insufficient"
        finally:
            connections.close_all()

    @patch.object(Rack, "adjust_stock", _noop_adjust_stock)
    def test_concurrent_stock_outs_do_not_oversell(self):
        results = [None, None]
        threads = [
            threading.Thread(target=self._stock_out, args=(results, i))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 10 units on the rack, two attempts to take 6: exactly one must win.
        self.assertEqual(sorted(results), ["insufficient", "ok"])
        record = BookInventory.objects.get(book=self.book, rack=self.rack)
        self.assertEqual(record.curr_stock, 4)
        self.assertEqual(StockMovement.objects.count(), 1)


@pytest.mark.postgres_only
class MovementEngineInsertRaceTests(TransactionTestCase):
    """
    Two concurrent *first-ever* movements for the same (book, rack): both
    `select_for_update()` calls miss (no row yet), so without the
    catch-`IntegrityError`-and-reselect guard, `uniq_book_per_rack` turns one
    insert into a 500 instead of a lock wait.
    """

    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Main")
        self.section = Section.objects.create(warehouse=self.warehouse, name="A")
        self.rack = Rack.objects.create(section=self.section, name="A-1", max_capacity=1000)
        self.book = Book.objects.create(title="Chemistry XII", isbn="9780000000203")

    def _stock_in(self, results, index):
        try:
            apply_stock_movement(
                book=self.book, rack=self.rack, quantity=5,
                movement_type=MovementType.IN, actor=None,
            )
            results[index] = "ok"
        except Exception as exc:  # noqa: BLE001 — the point is that nothing escapes as a 500
            results[index] = repr(exc)
        finally:
            connections.close_all()

    @patch.object(Rack, "adjust_stock", _noop_adjust_stock)
    def test_concurrent_first_movements_do_not_500(self):
        results = [None, None]
        threads = [
            threading.Thread(target=self._stock_in, args=(results, i))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(results, ["ok", "ok"])
        record = BookInventory.objects.get(book=self.book, rack=self.rack)
        self.assertEqual(record.curr_stock, 10)
        self.assertEqual(record.in_entry, 10)
        self.assertEqual(StockMovement.objects.count(), 2)


class EndToEndWithRealRackTests(StockEngineTestCase):
    """
    No `Rack.adjust_stock()` patch anywhere in this class — these run the two
    halves of the cross-team contract together, the way production actually
    calls them.
    """

    def test_a_real_movement_updates_the_rack_too(self):
        record = apply_stock_movement(
            book=self.book, rack=self.rack, quantity=10,
            movement_type=MovementType.IN, actor=None,
        )
        self.assertEqual(record.curr_stock, 10)

        rack = Rack.objects.get(pk=self.rack.pk)
        self.assertEqual(rack.current_stock, 10)
        self.assertIsNotNone(rack.last_change_date)
        self.assertIsNotNone(rack.last_used)

    def test_rack_capacity_is_enforced_even_when_bookinventory_has_room(self):
        """
        The one failure mode a mocked `Rack.adjust_stock` cannot produce: a
        movement that `BookInventory` would happily accept but the physical
        rack cannot hold. Must roll back everything, not just the rack.
        """
        tight_rack = Rack.objects.create(
            section=self.section, name="A-tight", max_capacity=5,
        )
        with self.assertRaises(ValidationError):
            apply_stock_movement(
                book=self.book, rack=tight_rack, quantity=6,
                movement_type=MovementType.IN, actor=None,
            )
        self.assertFalse(
            BookInventory.objects.filter(book=self.book, rack=tight_rack).exists()
        )
        self.assertEqual(StockMovement.objects.filter(rack=tight_rack).count(), 0)
        self.assertEqual(Rack.objects.get(pk=tight_rack.pk).current_stock, 0)

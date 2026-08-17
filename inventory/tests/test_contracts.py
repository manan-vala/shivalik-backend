"""
The day-1 cross-team contracts.

These are the signatures three teams write code against before any of the
bodies exist. A stub that quietly changes shape is worse than no stub, so the
shape itself is the thing under test:

* `Rack.adjust_stock(delta, actor)` — Team B wrote it, Team A fills it in.
* `apply_stock_movement(...)` — Team B publishes and fills it in.

When a body lands, the `NotImplementedError` assertion here fails. That is the
signal to replace it with real behaviour tests — in a DB-enabled test module,
since this one is deliberately a `SimpleTestCase` with no database. Both
bodies have now landed: `apply_stock_movement`'s behaviour tests live in
`test_stock_engine.py`, `Rack.adjust_stock`'s live in `test_rack_engine.py`,
and this file keeps only the two signature contracts.
"""

import inspect

import pytest
from django.db import connection, transaction
from django.test import SimpleTestCase, TransactionTestCase

from inventory.models import (
    BookInventory,
    INBOUND_TYPES,
    OUTBOUND_TYPES,
    REASON_REQUIRED_TYPES,
    InsufficientStockError,
    MovementType,
    Rack,
    apply_stock_movement,
    signed_delta,
)


class RackAdjustStockContractTests(SimpleTestCase):
    def test_signature_is_exactly_what_team_b_calls(self):
        signature = inspect.signature(Rack.adjust_stock)
        self.assertEqual(list(signature.parameters), ["self", "delta", "actor"])

    # `test_stub_fails_loudly` lived here until Task 2 landed a real body —
    # see `test_rack_engine.py` for its behaviour tests.


class ApplyStockMovementContractTests(SimpleTestCase):
    def test_signature_is_keyword_only_and_complete(self):
        signature = inspect.signature(apply_stock_movement)
        self.assertEqual(
            list(signature.parameters),
            [
                "book",
                "rack",
                "quantity",
                "movement_type",
                "actor",
                "vendor",
                "purchase_order",
                "reason",
            ],
        )
        # Keyword-only: a positional call site would break the moment anyone
        # reorders the arguments, and three teams call this.
        self.assertTrue(
            all(
                parameter.kind is inspect.Parameter.KEYWORD_ONLY
                for parameter in signature.parameters.values()
            )
        )

    def test_optional_arguments_have_the_documented_defaults(self):
        defaults = {
            name: parameter.default
            for name, parameter in inspect.signature(apply_stock_movement).parameters.items()
            if parameter.default is not inspect.Parameter.empty
        }
        self.assertEqual(defaults, {"vendor": None, "purchase_order": None, "reason": ""})

    # `test_stub_fails_loudly` lived here until Team B's Task 2 landed a real
    # body — this class stays a `SimpleTestCase` (signature-only, no DB), and
    # a real body needs a database, so its behaviour tests moved to
    # `test_stock_engine.py` rather than turning this class into one.


class MovementTypeTests(SimpleTestCase):
    def test_every_type_has_a_direction(self):
        """
        The engine derives the sign of a movement from its type alone. A type
        in neither set would silently have no effect on stock.
        """
        self.assertEqual(
            INBOUND_TYPES | OUTBOUND_TYPES,
            set(MovementType.values),
        )
        self.assertFalse(INBOUND_TYPES & OUTBOUND_TYPES)

    def test_adjustments_are_directional(self):
        """
        The reason ADJUSTMENT is split in two: one value cannot express a
        correction downwards, which is the common case.
        """
        self.assertEqual(signed_delta(MovementType.ADJUSTMENT_IN, 3), 3)
        self.assertEqual(signed_delta(MovementType.ADJUSTMENT_OUT, 3), -3)

    def test_signed_delta_directions(self):
        self.assertEqual(signed_delta(MovementType.IN, 5), 5)
        self.assertEqual(signed_delta(MovementType.RECEIVE, 5), 5)
        self.assertEqual(signed_delta(MovementType.OUT, 5), -5)
        self.assertEqual(signed_delta(MovementType.WRITE_OFF, 5), -5)

    def test_unknown_type_is_rejected_rather_than_ignored(self):
        with self.assertRaises(ValueError):
            signed_delta("TELEPORT", 1)

    def test_corrections_must_be_explained(self):
        self.assertEqual(
            REASON_REQUIRED_TYPES,
            {
                MovementType.ADJUSTMENT_IN,
                MovementType.ADJUSTMENT_OUT,
                MovementType.WRITE_OFF,
            },
        )


class InsufficientStockErrorTests(SimpleTestCase):
    def test_carries_the_numbers_a_caller_needs_for_its_message(self):
        error = InsufficientStockError(available=2, requested=5)
        self.assertEqual((error.available, error.requested), (2, 5))
        self.assertIn("2 available", str(error))


@pytest.mark.postgres_only
class RowLockingTests(TransactionTestCase):
    """
    The premise the whole engine rests on (Q2 / finding `H-2`).

    Skipped on SQLite rather than passed, because there it would pass while
    proving the opposite of what it claims.
    """

    def test_select_for_update_reaches_the_database(self):
        self.assertTrue(connection.features.has_select_for_update)
        with transaction.atomic():
            query = str(BookInventory.objects.select_for_update().all().query)
        self.assertIn("FOR UPDATE", query)

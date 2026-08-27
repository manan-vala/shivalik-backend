"""
Behaviour tests for `Rack.adjust_stock()`.

`test_contracts.py` covers the signature. This covers the body: bounds
checking, the "unmeasured" exemption, timestamp/actor stamping, and the
same check-then-update race `apply_stock_movement` has to guard against
one level down — two movements against the *same* rack can come
from two different books, so the caller's `BookInventory` lock does not
serialise them.
"""

import threading

import pytest
from django.db import connections, transaction
from django.test import TestCase, TransactionTestCase
from rest_framework.exceptions import ValidationError

from inventory.models import Rack, Section, Warehouse
from staff_auth.models import Employee


class RackAdjustStockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.warehouse = Warehouse.objects.create(name="Main")
        cls.section = Section.objects.create(warehouse=cls.warehouse, name="A")
        cls.actor = Employee.objects.create_user(
            email="ops@shivalik.test", password="not-a-default-password",
            name="Ops", role=Employee.Role.INVENTORY_MANAGER,
        )

    def test_inbound_delta_increases_stock_and_stamps_metadata(self):
        rack = Rack.objects.create(section=self.section, name="A-1", max_capacity=100)
        with transaction.atomic():
            rack.adjust_stock(10, self.actor)
        rack.refresh_from_db()
        self.assertEqual(rack.current_stock, 10)
        self.assertIsNotNone(rack.last_change_date)
        self.assertIsNotNone(rack.last_used)
        self.assertEqual(rack.updated_by, self.actor)

    def test_outbound_delta_decreases_stock(self):
        rack = Rack.objects.create(
            section=self.section, name="A-2", max_capacity=100, current_stock=10,
        )
        with transaction.atomic():
            rack.adjust_stock(-4, None)
        rack.refresh_from_db()
        self.assertEqual(rack.current_stock, 6)
        self.assertIsNone(rack.updated_by)  # actor may legitimately be None

    def test_refuses_to_drop_below_zero(self):
        rack = Rack.objects.create(
            section=self.section, name="A-3", max_capacity=100, current_stock=5,
        )
        with self.assertRaises(ValidationError), transaction.atomic():
            rack.adjust_stock(-6, None)
        rack.refresh_from_db()
        self.assertEqual(rack.current_stock, 5)  # nothing was written

    def test_refuses_to_exceed_capacity(self):
        rack = Rack.objects.create(
            section=self.section, name="A-4", max_capacity=10, current_stock=8,
        )
        with self.assertRaises(ValidationError), transaction.atomic():
            rack.adjust_stock(5, None)
        rack.refresh_from_db()
        self.assertEqual(rack.current_stock, 8)

    def test_zero_capacity_means_unmeasured_and_skips_the_ceiling_check(self):
        rack = Rack.objects.create(
            section=self.section, name="A-5", max_capacity=0, current_stock=0,
        )
        with transaction.atomic():
            rack.adjust_stock(10_000, None)
        rack.refresh_from_db()
        self.assertEqual(rack.current_stock, 10_000)

    def test_does_not_require_the_caller_to_save(self):
        rack = Rack.objects.create(section=self.section, name="A-6", max_capacity=100)
        with transaction.atomic():
            result = rack.adjust_stock(3, None)
        self.assertIsNone(result)
        self.assertEqual(Rack.objects.get(pk=rack.pk).current_stock, 3)


@pytest.mark.postgres_only
class RackAdjustStockConcurrencyTests(TransactionTestCase):
    """
    Two movements against the same rack from two different books: the
    caller's `BookInventory` lock is on a different row for each, so it does
    not serialise these calls. Without `adjust_stock`'s own lock, both could
    read a `current_stock` within capacity and both write, landing the real
    total above it.
    """

    def setUp(self):
        self.warehouse = Warehouse.objects.create(name="Main")
        self.section = Section.objects.create(warehouse=self.warehouse, name="A")
        self.rack = Rack.objects.create(
            section=self.section, name="A-1", max_capacity=10, current_stock=0,
        )

    def _adjust(self, results, index):
        try:
            with transaction.atomic():
                self.rack.adjust_stock(6, None)
            results[index] = "ok"
        except ValidationError:
            results[index] = "rejected"
        finally:
            connections.close_all()

    def test_concurrent_adjustments_do_not_exceed_capacity(self):
        results = [None, None]
        threads = [
            threading.Thread(target=self._adjust, args=(results, i))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Capacity is 10, two attempts to add 6 each: exactly one must win.
        self.assertEqual(sorted(results), ["ok", "rejected"])
        rack = Rack.objects.get(pk=self.rack.pk)
        self.assertEqual(rack.current_stock, 6)

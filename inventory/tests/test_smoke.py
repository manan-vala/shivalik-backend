"""
Smoke tests — the fundamental invariants, checked on every PR.

Deliberately small. The rest of the suite proves specific behaviour in
depth; this file answers one question fast: **is the base of this system
still standing?** If anything here goes red, the branch is broken in a way
that affects every team, and no amount of detailed passing tests elsewhere
makes it safe to merge.

Each test guards something that has already gone wrong once, or that the
whole system rests on:

1. The API is closed by default            (`C-1` — was open to anonymous)
2. Stock moves only through the engine     (the project's non-negotiable rule)
3. Overselling is a 400, not a 500         (`H-1` — the TOCTOU race)
4. The ledger reconciles                   (Task 7 — counters vs the log)
5. The core read surface answers           (routes wired, serializers sane)
6. The OpenAPI contract still generates    (`L-6` — the published API shape)

Run just these with `pytest -m smoke`.

**Keep this file cheap and general.** It is a gate, not a spec — resist
adding a case here for every bug fixed. New detail belongs in the focused
files next to it.
"""

from io import StringIO

import pytest
from django.core.management import call_command
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from inventory.models import (
    Book,
    BookInventory,
    MovementType,
    Rack,
    Section,
    StockMovement,
    Vendor,
    Warehouse,
    apply_stock_movement,
)
from staff_auth.models import Employee

pytestmark = pytest.mark.smoke


class SmokeTests(APITestCase):
    """One fixture, six checks — the whole write-then-read round trip."""

    @classmethod
    def setUpTestData(cls):
        cls.staff = Employee.objects.create_user(
            email="smoke@shivalik.test",
            password="not-a-default-password",
            name="Smoke",
            role=Employee.Role.INVENTORY_MANAGER,
            status=Employee.Status.APPROVED,
        )
        cls.warehouse = Warehouse.objects.create(name="Main")
        cls.section = Section.objects.create(warehouse=cls.warehouse, name="A")
        cls.rack = Rack.objects.create(section=cls.section, name="A-1", max_capacity=100)
        cls.vendor = Vendor.objects.create(
            company_name="Acme Books", vendor_name="Acme", gst_number="24AAACA0000A1Z7",
        )
        cls.book = Book.objects.create(
            title="Physics XII", isbn="9789999999999", min_stock=5, mrp="499.00",
        )

    def setUp(self):
        self.client.force_authenticate(user=self.staff)

    # 1 -------------------------------------------------------------------
    def test_api_is_closed_to_anonymous_callers(self):
        """
        `C-1`: the entire warehouse API was once readable and writable
        without a token.

        Two independent layers hold this shut — `DEFAULT_PERMISSION_CLASSES`
        in settings, and the explicit `permission_classes` every viewset
        declares. This asserts the *outcome*, so it stays honest whichever
        one regresses; verified by mutation, it only goes red when both are
        gone, which is the actual security boundary rather than one
        mechanism's implementation detail.
        """
        anonymous = APIClient()
        for url in (
            "/api/v1/inventory/books/",
            "/api/v1/inventory/stock/low-stock/",
            f"/api/v1/inventory/books/{self.book.pk}/stock-in/",
        ):
            response = anonymous.get(url)
            self.assertEqual(
                response.status_code, status.HTTP_401_UNAUTHORIZED, f"{url} is open",
            )

    # 2 -------------------------------------------------------------------
    def test_a_stock_movement_updates_every_number_it_should(self):
        """
        The non-negotiable rule, end to end: one call to the engine writes
        the ledger row, the rack, and the movement log — together or not at
        all. If this passes, the single write path is intact.
        """
        record = apply_stock_movement(
            book=self.book, rack=self.rack, quantity=10,
            movement_type=MovementType.IN, actor=self.staff, vendor=self.vendor,
        )

        self.rack.refresh_from_db()
        movement = StockMovement.objects.get()

        self.assertEqual(record.curr_stock, 10)          # ledger balance
        self.assertEqual(record.in_entry, 10)            # lifetime counter
        self.assertEqual(self.rack.current_stock, 10)    # rack aggregate
        self.assertIsNotNone(self.rack.last_used)        # `M-1`
        self.assertEqual(movement.quantity, 10)          # the log itself
        self.assertEqual(movement.balance_after, 10)
        self.assertEqual(movement.actor, self.staff)     # audit trail

    # 3 -------------------------------------------------------------------
    def test_overselling_is_a_400_not_a_500(self):
        """
        `H-1`. The check must sit inside the engine's row lock; a regression
        here shows up as an `IntegerityError` 500 and a corrupted ledger,
        not as a polite failure.
        """
        self.client.post(
            f"/api/v1/inventory/books/{self.book.pk}/stock-in/",
            {"rack": self.rack.pk, "vendor": self.vendor.pk, "quantity": 5},
            format="json",
        )
        response = self.client.post(
            f"/api/v1/inventory/books/{self.book.pk}/stock-out/",
            {"rack": self.rack.pk, "vendor": self.vendor.pk, "quantity": 999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"], "Insufficient stock on the specified rack.",
        )

    # 4 -------------------------------------------------------------------
    def test_the_ledger_reconciles_against_its_own_movement_log(self):
        """
        The counters are a projection of `StockMovement`. If they can drift
        apart, every number this system reports is unreliable — and nobody
        notices for weeks. `reconcile_stock_ledger` raises on any drift.
        """
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=8,
            movement_type=MovementType.IN, actor=self.staff, vendor=self.vendor,
        )
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=3,
            movement_type=MovementType.OUT, actor=self.staff,
        )
        call_command("reconcile_stock_ledger")  # CommandError on drift

        record = BookInventory.objects.get(book=self.book, rack=self.rack)
        self.assertEqual(record.curr_stock, 5)

    # 5 -------------------------------------------------------------------
    def test_the_core_read_surface_answers(self):
        """
        Routes wired, serializers importable, querysets valid. Cheap, and it
        catches a broken router or a serializer typo before anything subtler.
        """
        apply_stock_movement(
            book=self.book, rack=self.rack, quantity=2,   # below min_stock=5
            movement_type=MovementType.IN, actor=self.staff, vendor=self.vendor,
        )
        for url in (
            "/api/v1/inventory/books/",
            "/api/v1/inventory/warehouses/",
            "/api/v1/inventory/racks/",
            "/api/v1/inventory/vendors/",
            "/api/v1/inventory/books/inventory/",
            "/api/v1/inventory/stock/low-stock/",
            "/api/v1/inventory/stock/in-stock/",
            "/api/v1/inventory/stock/low-selling/",
            f"/api/v1/inventory/books/{self.book.pk}/history/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    # 6 -------------------------------------------------------------------
    def test_the_openapi_schema_generates_without_warnings(self):
        """
        `/api/schema/` is the machine-readable contract the frontend builds
        against (`L-6`). A viewset without a resolvable serializer degrades
        it — and that failure is invisible from the outside, because the
        endpoint still answers **200** with a schema that quietly documents
        nothing for the broken route. Only `--fail-on-warn` catches it, so
        assert on the generator, not on the HTTP response.
        """
        # `--file` takes a path, so swallow the rendered schema via stdout;
        # this asserts generation succeeds, not what it contains.
        call_command("spectacular", "--fail-on-warn", stdout=StringIO())

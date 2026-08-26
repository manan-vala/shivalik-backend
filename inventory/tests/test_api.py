"""
The endpoints that already existed must still behave after Sprint 0.

The file split, the permission default and the Q3 field move all touched code
paths that had no test at all (finding `M-8`), so this covers the round trips
an operator actually makes.
"""

import threading
from unittest import mock

import pytest
from django.db import connections
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient, APITestCase, APITransactionTestCase

from inventory.models import (
    Book,
    BookInventory,
    Rack,
    Section,
    StockMovement,
    Vendor,
    Warehouse,
)
from inventory.views import BookViewSet
from staff_auth.models import Employee


class InventoryAPITestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = Employee.objects.create_user(
            email="ops@shivalik.test",
            password="not-a-default-password",
            name="Ops",
            role=Employee.Role.INVENTORY_MANAGER,
            status=Employee.Status.APPROVED,
        )
        cls.warehouse = Warehouse.objects.create(name="Main")
        cls.section = Section.objects.create(warehouse=cls.warehouse, name="A")
        cls.rack = Rack.objects.create(section=cls.section, name="A-1", max_capacity=100)
        cls.vendor = Vendor.objects.create(
            company_name="Acme Books", vendor_name="Acme", gst_number="24AAACA0000A1Z0",
        )
        cls.book = Book.objects.create(title="Physics XII", isbn="9780000000001")

    def setUp(self):
        self.client.force_authenticate(user=self.staff)


class SectionEndpointTests(InventoryAPITestCase):
    def test_create_returns_the_derived_totals(self):
        """
        Q3 turned `max_capacity` / `current_stock` into annotations. A newly
        created Section has never been through `with_rack_totals()`, so the
        serializer must not assume the attribute is there.
        """
        response = self.client.post(
            "/api/v1/inventory/sections/",
            {"warehouse": self.warehouse.pk, "name": "B"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["max_capacity"], 0)
        self.assertEqual(response.data["current_stock"], 0)

    def test_list_totals_come_from_the_racks(self):
        Rack.objects.create(section=self.section, name="A-2", max_capacity=40)
        response = self.client.get("/api/v1/inventory/sections/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(r for r in response.data["results"] if r["id"] == self.section.pk)
        self.assertEqual(row["max_capacity"], 140)

    def test_retrieve_is_consistent_with_list(self):
        response = self.client.get(f"/api/v1/inventory/sections/{self.section.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["max_capacity"], 100)

    def test_capacity_cannot_be_written_through_the_section(self):
        """It is the racks' number now; accepting it here would be a lie."""
        response = self.client.patch(
            f"/api/v1/inventory/sections/{self.section.pk}/",
            {"max_capacity": 9999},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["max_capacity"], 100)


class RackEndpointTests(InventoryAPITestCase):
    def test_create_accepts_capacity(self):
        response = self.client.post(
            "/api/v1/inventory/racks/",
            {"section": self.section.pk, "name": "A-3", "max_capacity": 60},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["max_capacity"], 60)
        self.assertEqual(response.data["current_stock"], 0)

    def test_shrinking_capacity_below_stock_is_a_400_not_a_500(self):
        """
        The DB constraint would raise IntegrityError here, which DRF reports
        as a 500. The serializer has to catch it first.
        """
        Rack.objects.filter(pk=self.rack.pk).update(current_stock=40)
        response = self.client.patch(
            f"/api/v1/inventory/racks/{self.rack.pk}/",
            {"max_capacity": 10},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("max_capacity", response.data)

    def test_capacity_can_still_grow(self):
        Rack.objects.filter(pk=self.rack.pk).update(current_stock=40)
        response = self.client.patch(
            f"/api/v1/inventory/racks/{self.rack.pk}/",
            {"max_capacity": 200},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_stock_fields_are_read_only(self):
        response = self.client.patch(
            f"/api/v1/inventory/racks/{self.rack.pk}/",
            {"current_stock": 500},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.rack.refresh_from_db()
        self.assertEqual(self.rack.current_stock, 0)


class WarehouseEndpointTests(InventoryAPITestCase):
    """
    Ported from PR #2, which built this CRUD against a duplicate Warehouse in
    the `api` app. The assertions are the author's; only the routes and the
    field names changed, because the models they were written for were folded
    into `inventory` rather than merged alongside it.
    """

    def test_create_warehouse(self):
        response = self.client.post(
            "/api/v1/inventory/warehouses/",
            {
                "name": "Main Warehouse",
                "code": "WH-001",
                "location": "Industrial Area",
                "description": "Primary warehouse",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["code"], "WH-001")
        self.assertEqual(response.data["sections_count"], 0)
        self.assertTrue(Warehouse.objects.filter(code="WH-001").exists())

    def test_sections_count_is_annotated_on_list(self):
        response = self.client.get("/api/v1/inventory/warehouses/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(r for r in response.data["results"] if r["id"] == self.warehouse.pk)
        self.assertEqual(row["sections_count"], 1)

    def test_warehouse_code_is_unique_when_set(self):
        self.client.post(
            "/api/v1/inventory/warehouses/",
            {"name": "First", "code": "WH-009"},
            format="json",
        )
        response = self.client.post(
            "/api/v1/inventory/warehouses/",
            {"name": "Second", "code": "WH-009"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_blank_codes_do_not_collide(self):
        """
        The whole reason the constraint is partial. Every row that predates
        PR #2 has `code=""`, so a plain unique index would make the second
        warehouse ever created un-saveable.
        """
        Warehouse.objects.create(name="No code one")
        Warehouse.objects.create(name="No code two")
        response = self.client.post(
            "/api/v1/inventory/warehouses/", {"name": "No code three"}, format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)


class SectionRackCodeTests(InventoryAPITestCase):
    def test_create_section_and_rack_with_codes(self):
        section = self.client.post(
            "/api/v1/inventory/sections/",
            {
                "warehouse": self.warehouse.pk,
                "name": "Cold Storage",
                "code": "SEC-01",
                "is_active": True,
            },
            format="json",
        )
        self.assertEqual(section.status_code, status.HTTP_201_CREATED, section.data)
        self.assertEqual(section.data["warehouse_name"], "Main")
        self.assertEqual(section.data["racks_count"], 0)

        rack = self.client.post(
            "/api/v1/inventory/racks/",
            {
                "section": section.data["id"],
                "name": "Rack A1",
                "code": "R-001",
                "max_capacity": 100,
            },
            format="json",
        )
        self.assertEqual(rack.status_code, status.HTTP_201_CREATED, rack.data)
        self.assertEqual(rack.data["section_name"], "Cold Storage")
        self.assertEqual(rack.data["warehouse_name"], "Main")

    def test_section_code_is_unique_within_its_warehouse_only(self):
        other = Warehouse.objects.create(name="Second site")
        Section.objects.create(warehouse=self.warehouse, name="S1", code="SEC-01")

        clash = self.client.post(
            "/api/v1/inventory/sections/",
            {"warehouse": self.warehouse.pk, "name": "S2", "code": "SEC-01"},
            format="json",
        )
        self.assertEqual(clash.status_code, status.HTTP_400_BAD_REQUEST)

        reuse = self.client.post(
            "/api/v1/inventory/sections/",
            {"warehouse": other.pk, "name": "S3", "code": "SEC-01"},
            format="json",
        )
        self.assertEqual(reuse.status_code, status.HTTP_201_CREATED, reuse.data)

    def test_racks_count_is_annotated_on_list(self):
        Rack.objects.create(section=self.section, name="A-9", max_capacity=10)
        response = self.client.get("/api/v1/inventory/sections/")
        row = next(r for r in response.data["results"] if r["id"] == self.section.pk)
        self.assertEqual(row["racks_count"], 2)
        # The Count must not inflate the subquery-based totals, or vice versa.
        self.assertEqual(row["max_capacity"], 110)


class BookEndpointTests(InventoryAPITestCase):
    def test_register_alias_creates_a_book(self):
        """L-7: `register/` delegates to `create()` rather than duplicating it."""
        response = self.client.post(
            "/api/v1/inventory/books/register/",
            {
                "title": "Chemistry XII", "isbn": "9780000000002",
                "min_stock": 5, "mrp": "450.00",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(Book.objects.filter(isbn="9780000000002").exists())

    def test_register_and_create_produce_the_same_shape(self):
        created = self.client.post(
            "/api/v1/inventory/books/",
            {"title": "A", "isbn": "9780000000003", "mrp": "100.00"},
            format="json",
        )
        registered = self.client.post(
            "/api/v1/inventory/books/register/",
            {"title": "B", "isbn": "9780000000004", "mrp": "100.00"},
            format="json",
        )
        self.assertEqual(set(created.data), set(registered.data))

    def test_mrp_is_required_at_the_api_even_though_the_column_is_nullable(self):
        """
        `mrp` is nullable in the database on purpose — existing rows may
        predate pricing — but a *new* book must be priced. Enforced in the
        serializer rather than defaulting to 0.00, which would silently
        misprice a book nobody actually priced.
        """
        response = self.client.post(
            "/api/v1/inventory/books/",
            {"title": "No price", "isbn": "9780000000006"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("mrp", response.data)

    def test_full_catalog_fields_round_trip(self):
        """The Register New Book screen needs more than the original five."""
        response = self.client.post(
            "/api/v1/inventory/books/",
            {
                "title": "Physics XI", "isbn": "9780000000007",
                "author": "R. Author", "publisher": "P. Publisher",
                "class_level": "Class 11", "board": "CBSE", "subject": "Physics",
                "mrp": "550.00", "tax_percent": "5.00",
                "default_warehouse": self.warehouse.pk,
                "default_section": self.section.pk,
                "default_rack": self.rack.pk,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["class_level"], "Class 11")
        self.assertEqual(response.data["default_warehouse_name"], "Main")
        self.assertEqual(response.data["default_rack_name"], "A-1")

    def test_get_post_and_patch_all_answer_with_the_same_shape(self):
        """
        Third time this codebase has been bitten by a read-only field
        silently vanishing (`05` §5.3): once on `POST /sections/`, and once
        here — the nullable `default_*` FKs drop their `_name` companions
        unless the field is a `SerializerMethodField`. `default=None` looks
        like a fix but is ignored when `partial=True`, so GET and POST stay
        correct while every PATCH answers with three fewer keys.
        """
        created = self.client.post(
            "/api/v1/inventory/books/",
            {"title": "Shape", "isbn": "9780000000011", "mrp": "10.00"},
            format="json",
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        book_id = created.data["id"]

        fetched = self.client.get(f"/api/v1/inventory/books/{book_id}/")
        patched = self.client.patch(
            f"/api/v1/inventory/books/{book_id}/", {"title": "Reshaped"}, format="json",
        )

        self.assertEqual(set(created.data), set(fetched.data))
        self.assertEqual(set(fetched.data), set(patched.data))
        for key in ("default_warehouse_name", "default_section_name",
                    "default_rack_name"):
            self.assertIn(key, patched.data)
            self.assertIsNone(patched.data[key])

    def test_search_by_title_or_isbn(self):
        Book.objects.create(title="Advanced Calculus", isbn="9780000000008", mrp="300.00")
        response = self.client.get("/api/v1/inventory/books/?search=Calculus")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["isbn"], "9780000000008")

    def test_filter_by_category_fields(self):
        Book.objects.create(
            title="Chem XII", isbn="9780000000009",
            class_level="Class 12", board="CBSE", mrp="400.00",
        )
        Book.objects.create(
            title="Chem XI", isbn="9780000000010",
            class_level="Class 11", board="CBSE", mrp="400.00",
        )
        response = self.client.get("/api/v1/inventory/books/?class_level=Class+12")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["isbn"], "9780000000009")


class StockActionTests(InventoryAPITestCase):
    """
    The existing stock endpoints, unchanged by Sprint 0 beyond the serializer
    rename. These are the regression net for Team B's Tasks 2–4.
    """

    def _stock_in(self, quantity):
        return self.client.post(
            f"/api/v1/inventory/books/{self.book.pk}/stock-in/",
            {"rack": self.rack.pk, "vendor": self.vendor.pk, "quantity": quantity},
            format="json",
        )

    def _stock_out(self, quantity):
        return self.client.post(
            f"/api/v1/inventory/books/{self.book.pk}/stock-out/",
            {"rack": self.rack.pk, "vendor": self.vendor.pk, "quantity": quantity},
            format="json",
        )

    def test_stock_in_then_out(self):
        response = self._stock_in(10)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["curr_stock"], 10)
        self.assertEqual(response.data["in_entry"], 10)

        response = self._stock_out(3)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["curr_stock"], 7)
        self.assertEqual(response.data["out_entry"], 3)

    def test_overselling_is_a_400_not_a_500(self):
        self._stock_in(5)
        response = self._stock_out(999)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data["detail"], "Insufficient stock on the specified rack.",
        )

    def test_blocked_vendor_is_rejected(self):
        self.vendor.is_blocked = True
        self.vendor.save()
        response = self._stock_in(1)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("vendor", response.data)

    def test_ledger_report_still_serialises(self):
        self._stock_in(4)
        response = self.client.get("/api/v1/inventory/books/inventory/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["rack_location"], "Main / A / A-1")
        self.assertEqual(response.data[0]["curr_stock"], 4)

    def test_stock_in_records_the_caller_as_actor(self):
        """
        The movement is attributed to whoever made the request.

        `595b66b` fell back to `User.objects.first()` when the caller was
        anonymous, which put an arbitrary employee's name against stock they
        never touched. Removed — this pins the attribution.
        """
        self._stock_in(6)
        movement = self.book.movements.get()
        self.assertEqual(movement.actor, self.staff)

    def test_anonymous_stock_in_is_401_and_writes_nothing(self):
        """
        An unauthenticated stock-in is refused outright rather than booked
        against a stand-in actor. Both halves matter: the status code, and
        the ledger staying empty behind it.
        """
        anonymous = APIClient()
        response = anonymous.post(
            f"/api/v1/inventory/books/{self.book.pk}/stock-in/",
            {"rack": self.rack.pk, "vendor": self.vendor.pk, "quantity": 5},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(BookInventory.objects.filter(curr_stock__gt=0).exists())
        self.rack.refresh_from_db()
        self.assertEqual(self.rack.current_stock, 0)

    def test_stock_routes_still_401_with_permissions_relaxed(self):
        """
        The one that actually pins `595b66b`.

        `IsAuthenticated` refuses an anonymous caller before the view body
        runs, so the `User.objects.first()` fallback that lived there was
        unreachable over HTTP and no ordinary test could see it. It only
        mattered if someone relaxed the permission classes — which is
        precisely why it was added. With them relaxed, the routes must still
        refuse rather than attribute the movement to an arbitrary employee.
        """
        anonymous = APIClient()
        payload = {"rack": self.rack.pk, "vendor": self.vendor.pk, "quantity": 5}

        with mock.patch.object(BookViewSet, "permission_classes", [AllowAny]):
            for route in ("stock-in", "stock-out"):
                with self.subTest(route=route):
                    response = anonymous.post(
                        f"/api/v1/inventory/books/{self.book.pk}/{route}/",
                        payload,
                        format="json",
                    )
                    self.assertEqual(
                        response.status_code,
                        status.HTTP_401_UNAUTHORIZED,
                        f"{route} accepted an anonymous caller: {response.data}",
                    )

        self.assertFalse(StockMovement.objects.exists())
        self.rack.refresh_from_db()
        self.assertEqual(self.rack.current_stock, 0)


@pytest.mark.postgres_only
class StockOutConcurrencyAPITests(APITransactionTestCase):
    """
    `H-1`, closed for real: two concurrent HTTP `stock-out` requests for the
    same book/rack must not both succeed. `APITestCase` (used above) wraps
    each test in a transaction that rolls back, so two "concurrent" requests
    would never actually contend — this needs `APITransactionTestCase`, the
    DRF equivalent of `TransactionTestCase`.
    """

    def setUp(self):
        self.staff = Employee.objects.create_user(
            email="ops@shivalik.test",
            password="not-a-default-password",
            name="Ops",
            role=Employee.Role.INVENTORY_MANAGER,
            status=Employee.Status.APPROVED,
        )
        self.warehouse = Warehouse.objects.create(name="Main")
        self.section = Section.objects.create(warehouse=self.warehouse, name="A")
        # Both counters seeded directly and in agreement — `curr_stock` on
        # `BookInventory` and `current_stock` on `Rack` must never drift
        # apart, or `rack.adjust_stock()`'s own bounds check (correctly)
        # rejects a movement `BookInventory` alone would have allowed.
        self.rack = Rack.objects.create(
            section=self.section, name="A-1", max_capacity=100, current_stock=10,
        )
        self.vendor = Vendor.objects.create(
            company_name="Acme Books", vendor_name="Acme", gst_number="24AAACA0000A1Z0",
        )
        self.book = Book.objects.create(title="Physics XII", isbn="9780000000005")
        BookInventory.objects.create(book=self.book, rack=self.rack, curr_stock=10, in_entry=10)

    def _stock_out(self, results, index):
        # Each thread needs its own client/connection — sharing self.client
        # across threads would share one HTTP-test connection state too.
        client = APIClient()
        client.force_authenticate(user=self.staff)
        response = client.post(
            f"/api/v1/inventory/books/{self.book.pk}/stock-out/",
            {"rack": self.rack.pk, "vendor": self.vendor.pk, "quantity": 6},
            format="json",
        )
        results[index] = response.status_code
        connections.close_all()

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

        # 10 units, two attempts to take 6: exactly one 200 and one 400.
        self.assertEqual(sorted(results), [200, 400])
        record = BookInventory.objects.get(book=self.book, rack=self.rack)
        self.assertEqual(record.curr_stock, 4)

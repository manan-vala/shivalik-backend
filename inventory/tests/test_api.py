"""
The endpoints that already existed must still behave after Sprint 0.

The file split, the permission default and the Q3 field move all touched code
paths that had no test at all (finding `M-8`), so this covers the round trips
an operator actually makes.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from inventory.models import Book, Rack, Section, Vendor, Warehouse
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
            {"title": "Chemistry XII", "isbn": "9780000000002", "min_stock": 5},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(Book.objects.filter(isbn="9780000000002").exists())

    def test_register_and_create_produce_the_same_shape(self):
        created = self.client.post(
            "/api/v1/inventory/books/",
            {"title": "A", "isbn": "9780000000003"},
            format="json",
        )
        registered = self.client.post(
            "/api/v1/inventory/books/register/",
            {"title": "B", "isbn": "9780000000004"},
            format="json",
        )
        self.assertEqual(set(created.data), set(registered.data))


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

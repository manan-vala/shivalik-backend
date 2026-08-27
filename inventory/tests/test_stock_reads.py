"""
The `stock/` read surface and the book-level movement log.

Also covers the correctness note the task doc calls out explicitly: low-stock
and needs-reorder must aggregate a book's stock across every rack, not
compare `min_stock` against one `(book, rack)` row at a time.
"""

from rest_framework import status
from rest_framework.test import APITestCase

from inventory.models import (
    Book,
    MovementType,
    Rack,
    Section,
    Vendor,
    Warehouse,
    apply_stock_movement,
)
from inventory.serializers import BookStockLevelSerializer
from staff_auth.models import Employee


class StockReadsTestCase(APITestCase):
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
        cls.rack1 = Rack.objects.create(section=cls.section, name="A-1", max_capacity=100)
        cls.rack2 = Rack.objects.create(section=cls.section, name="A-2", max_capacity=100)
        cls.rack3 = Rack.objects.create(section=cls.section, name="A-3", max_capacity=100)
        cls.vendor = Vendor.objects.create(
            company_name="Acme Books", vendor_name="Acme", gst_number="24AAACA0000A1Z3",
        )

    def setUp(self):
        self.client.force_authenticate(user=self.staff)

    def _stock_in(self, book, rack, quantity):
        apply_stock_movement(
            book=book, rack=rack, quantity=quantity,
            movement_type=MovementType.IN, actor=self.staff, vendor=self.vendor,
        )


class LowStockAndInStockTests(StockReadsTestCase):
    def test_split_stock_above_threshold_is_healthy_not_low(self):
        """
        The exact scenario `04-api-surface.md` §4.7 warns about: min_stock=10
        split 4/4/4 across three racks holds 12 and is healthy, even though
        every individual row looks low on its own.
        """
        book = Book.objects.create(title="Split Book", isbn="9781000000001",
                                    min_stock=10, mrp="200.00")
        self._stock_in(book, self.rack1, 4)
        self._stock_in(book, self.rack2, 4)
        self._stock_in(book, self.rack3, 4)

        response = self.client.get("/api/v1/inventory/stock/low-stock/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        isbns = [row["isbn"] for row in response.data["results"]]
        self.assertNotIn("9781000000001", isbns)

        # The old per-row bug would also have flagged every row here.
        inventory = self.client.get("/api/v1/inventory/books/inventory/")
        for row in inventory.data:
            if row["isbn"] == "9781000000001":
                self.assertFalse(row["needs_reorder"], row)
                self.assertEqual(row["deficit"], 0, row)

    def test_low_stock_reports_the_aggregate_and_the_rack_breakdown(self):
        book = Book.objects.create(title="Thin Book", isbn="9781000000002",
                                    min_stock=10, mrp="200.00")
        self._stock_in(book, self.rack1, 3)
        self._stock_in(book, self.rack2, 3)

        response = self.client.get("/api/v1/inventory/stock/low-stock/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        row = next(r for r in response.data["results"] if r["isbn"] == "9781000000002")
        self.assertEqual(row["curr_stock"], 6)
        self.assertEqual(row["deficit"], 4)
        self.assertEqual(len(row["racks"]), 2)
        self.assertEqual({r["curr_stock"] for r in row["racks"]}, {3})

    def test_in_stock_excludes_books_with_no_stock_anywhere(self):
        with_stock = Book.objects.create(title="Has Stock", isbn="9781000000003",
                                          mrp="100.00")
        Book.objects.create(title="No Stock", isbn="9781000000004", mrp="100.00")
        self._stock_in(with_stock, self.rack1, 5)

        response = self.client.get("/api/v1/inventory/stock/in-stock/")
        isbns = [row["isbn"] for row in response.data["results"]]
        self.assertIn("9781000000003", isbns)
        self.assertNotIn("9781000000004", isbns)

    def test_serializer_survives_a_book_without_the_queryset_annotation(self):
        """
        `curr_stock` comes from `_books_with_stock_totals()`. A read-only
        field whose attribute is missing is *omitted* rather than raising
        (`05` §5.3), which previously made `deficit` blow up with
        AttributeError → 500. Any future caller reusing this serializer on a
        plain `Book` — `reorder/` being the obvious one — must get a number.
        """
        book = Book.objects.create(title="Bare", isbn="9781000000099",
                                    min_stock=10, mrp="100.00")
        data = BookStockLevelSerializer(book).data
        self.assertEqual(data["curr_stock"], 0)
        self.assertEqual(data["deficit"], 10)
        self.assertEqual(data["racks"], [])

    def test_annotated_and_unannotated_paths_agree(self):
        book = Book.objects.create(title="Agree", isbn="9781000000098",
                                    min_stock=10, mrp="100.00")
        self._stock_in(book, self.rack1, 4)
        self._stock_in(book, self.rack2, 3)

        annotated = self.client.get("/api/v1/inventory/stock/low-stock/")
        row = next(r for r in annotated.data["results"] if r["isbn"] == "9781000000098")
        bare = BookStockLevelSerializer(Book.objects.get(pk=book.pk)).data

        self.assertEqual(row["curr_stock"], bare["curr_stock"], 7)
        self.assertEqual(row["deficit"], bare["deficit"], 3)


class LowSellingTests(StockReadsTestCase):
    def test_returns_only_flagged_books(self):
        Book.objects.create(title="Slow Mover", isbn="9781000000005",
                             mrp="150.00", low_selling=True)
        Book.objects.create(title="Fast Mover", isbn="9781000000006",
                             mrp="150.00", low_selling=False)

        response = self.client.get("/api/v1/inventory/stock/low-selling/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        isbns = [row["isbn"] for row in response.data["results"]]
        self.assertEqual(isbns, ["9781000000005"])


class MovementLogTests(StockReadsTestCase):
    def test_history_in_entries_out_entries(self):
        book = Book.objects.create(title="History Book", isbn="9781000000007",
                                    mrp="100.00")
        self._stock_in(book, self.rack1, 10)
        apply_stock_movement(
            book=book, rack=self.rack1, quantity=3,
            movement_type=MovementType.OUT, actor=self.staff,
        )

        history = self.client.get(f"/api/v1/inventory/books/{book.pk}/history/")
        self.assertEqual(history.status_code, status.HTTP_200_OK)
        self.assertEqual(history.data["count"], 2)
        # Newest first.
        self.assertEqual(history.data["results"][0]["movement_type"], MovementType.OUT)

        in_entries = self.client.get(f"/api/v1/inventory/books/{book.pk}/in-entries/")
        self.assertEqual(in_entries.data["count"], 1)
        self.assertEqual(in_entries.data["results"][0]["movement_type"], MovementType.IN)
        self.assertEqual(in_entries.data["results"][0]["vendor_name"], "Acme Books")

        out_entries = self.client.get(f"/api/v1/inventory/books/{book.pk}/out-entries/")
        self.assertEqual(out_entries.data["count"], 1)
        self.assertEqual(out_entries.data["results"][0]["movement_type"], MovementType.OUT)
        # Outbound movements carry no vendor.
        self.assertIsNone(out_entries.data["results"][0]["vendor"])

    def test_history_is_scoped_to_the_book(self):
        book_a = Book.objects.create(title="A", isbn="9781000000008", mrp="10.00")
        book_b = Book.objects.create(title="B", isbn="9781000000009", mrp="10.00")
        self._stock_in(book_a, self.rack1, 5)
        self._stock_in(book_b, self.rack1, 5)

        response = self.client.get(f"/api/v1/inventory/books/{book_a.pk}/history/")
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["book"], book_a.pk)


class StockViewSetPermissionTests(StockReadsTestCase):
    def test_anonymous_is_rejected(self):
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/v1/inventory/stock/low-stock/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

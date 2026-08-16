"""
The Day-3 schema: the constraints that are meant to make bad data impossible,
and the two derived reads that replaced stored columns.
"""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from inventory.models import (
    Book,
    BookInventory,
    MovementType,
    Rack,
    Section,
    StockMovement,
    Vendor,
    Warehouse,
)


class SchemaTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.warehouse = Warehouse.objects.create(name="Main")
        cls.section = Section.objects.create(warehouse=cls.warehouse, name="A")
        cls.rack = Rack.objects.create(section=cls.section, name="A-1", max_capacity=100)
        cls.vendor = Vendor.objects.create(
            company_name="Acme Books",
            vendor_name="Acme",
            gst_number="24AAACA0000A1Z0",
        )
        cls.book = Book.objects.create(title="Physics XII", isbn="9780000000001")


class BookSchemaTests(SchemaTestCase):
    def test_money_is_decimal_not_float(self):
        """Q5: a float cannot hold ₹1234.55 exactly, and the error compounds."""
        self.book.mrp = Decimal("1234.55")
        self.book.save()
        self.book.refresh_from_db()
        self.assertEqual(self.book.mrp, Decimal("1234.55"))

    def test_category_is_structured(self):
        """Q4: the Figma card renders two dimensions, so we store two."""
        self.book.class_level = "Class 12"
        self.book.board = "CBSE"
        self.book.subject = "Physics"
        self.book.save()
        self.assertEqual(
            Book.objects.filter(board="CBSE", class_level="Class 12").count(), 1
        )

    def test_tax_percent_above_100_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Book.objects.create(
                    title="Bad", isbn="9780000000002", tax_percent=Decimal("101"),
                )

    def test_negative_price_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Book.objects.create(
                    title="Bad", isbn="9780000000003", mrp=Decimal("-1"),
                )


class RackCapacityTests(SchemaTestCase):
    def test_capacity_lives_on_rack(self):
        """Q3: these four fields moved off Section."""
        for field in ("max_capacity", "current_stock", "last_change_date", "updated_by"):
            self.assertIn(field, {f.name for f in Rack._meta.get_fields()})

    def test_section_no_longer_stores_capacity(self):
        section_fields = {f.name for f in Section._meta.get_fields()}
        for field in ("max_capacity", "current_stock", "last_change_date", "updated_by"):
            self.assertNotIn(field, section_fields)

    def test_section_totals_are_derived_from_racks(self):
        Rack.objects.create(section=self.section, name="A-2", max_capacity=50)
        Rack.objects.filter(name="A-1").update(current_stock=10)

        section = Section.objects.with_rack_totals().get(pk=self.section.pk)
        self.assertEqual(section.max_capacity, 150)
        self.assertEqual(section.current_stock, 10)

    def test_section_with_no_racks_totals_zero_rather_than_none(self):
        empty = Section.objects.create(warehouse=self.warehouse, name="Empty")
        section = Section.objects.with_rack_totals().get(pk=empty.pk)
        self.assertEqual((section.max_capacity, section.current_stock), (0, 0))

    def test_stock_beyond_capacity_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Rack.objects.create(
                    section=self.section, name="A-9", max_capacity=5, current_stock=6,
                )

    def test_zero_capacity_means_unmeasured_not_full(self):
        """Racks predating Q3 have no capacity recorded; they still hold stock."""
        rack = Rack.objects.create(
            section=self.section, name="A-8", max_capacity=0, current_stock=40,
        )
        self.assertEqual(rack.current_stock, 40)


class StockMovementSchemaTests(SchemaTestCase):
    def _movement(self, **overrides):
        payload = {
            "book": self.book,
            "rack": self.rack,
            "movement_type": MovementType.IN,
            "quantity": 5,
        }
        payload.update(overrides)
        return StockMovement.objects.create(**payload)

    def test_zero_quantity_is_rejected(self):
        """Direction lives in the type, so quantity is strictly positive."""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._movement(quantity=0)

    def test_adjustment_without_a_reason_is_rejected(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._movement(movement_type=MovementType.ADJUSTMENT_OUT, reason="")

    def test_adjustment_with_a_reason_is_accepted(self):
        movement = self._movement(
            movement_type=MovementType.ADJUSTMENT_OUT, reason="Stock count variance",
        )
        self.assertEqual(movement.delta, -5)

    def test_ordinary_movements_need_no_reason(self):
        self.assertEqual(self._movement().delta, 5)

    def test_direction_survives_a_database_round_trip(self):
        """
        `movement_type` comes back from the database as a plain string, not a
        `MovementType` member. The direction lookup must still match, or every
        movement read back from the ledger would be direction-less.
        """
        self._movement(movement_type=MovementType.OUT, quantity=4)
        reloaded = StockMovement.objects.get()
        self.assertIsInstance(reloaded.movement_type, str)
        self.assertEqual(reloaded.delta, -4)

    def test_history_survives_the_actor_being_deleted(self):
        """SET_NULL on actor, PROTECT on book/rack — history is never orphaned."""
        self.assertEqual(
            StockMovement._meta.get_field("actor").remote_field.on_delete.__name__,
            "SET_NULL",
        )
        for field in ("book", "rack", "vendor", "purchase_order"):
            self.assertEqual(
                StockMovement._meta.get_field(field).remote_field.on_delete.__name__,
                "PROTECT",
                msg=f"{field} must not let ledger history be orphaned",
            )


class BookInventoryTests(SchemaTestCase):
    def test_vendor_is_optional(self):
        """
        M-7: vendor is a property of a purchase, not of a shelf. An outbound
        movement has no vendor, and used to be unable to create its row.
        """
        record = BookInventory.objects.create(book=self.book, rack=self.rack)
        self.assertIsNone(record.vendor)

    def test_one_row_per_book_and_rack(self):
        BookInventory.objects.create(book=self.book, rack=self.rack)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                BookInventory.objects.create(book=self.book, rack=self.rack)

    def test_last_out_at_exists_for_dead_stock_ageing(self):
        record = BookInventory.objects.create(book=self.book, rack=self.rack)
        self.assertIsNone(record.last_out_at)

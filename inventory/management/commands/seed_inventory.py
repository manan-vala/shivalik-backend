"""
Seed a development database with a small, realistic inventory.

Idempotent: every write is a `get_or_create` keyed on the natural key, so
running it twice changes nothing.

Stock is deliberately *not* written here. `BookInventory` rows are created at
zero and then filled by `apply_stock_movement()`, the single write path
documented in `inventory/models/stock.py`. While that engine is still a stub
(Team B, Task 2) the command seeds catalog, locations and vendors, leaves the
balances at zero, and says so. Once the engine lands, the opening balances
below start applying with no change to this file.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from inventory.models import (
    Book,
    BookInventory,
    MovementType,
    Rack,
    Section,
    Vendor,
    Warehouse,
    apply_stock_movement,
)


class Command(BaseCommand):
    help = "Seeds the database with initial inventory data for testing."

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding inventory data...")

        # 1. Warehouses
        wh1, _ = Warehouse.objects.get_or_create(name="North Zone Main Hub")
        Warehouse.objects.get_or_create(name="South City Reserve")

        # 2. Sections
        #
        # No capacity here: Q3 put capacity on Rack, and Section's
        # `max_capacity` / `current_stock` are annotations from
        # `Section.objects.with_rack_totals()`, not columns.
        sec1, _ = Section.objects.get_or_create(warehouse=wh1, name="Fiction Wing")
        sec2, _ = Section.objects.get_or_create(
            warehouse=wh1, name="Engineering Texts"
        )
        sec3, _ = Section.objects.get_or_create(
            warehouse=wh1, name="Arts & Humanities"
        )
        sec4, _ = Section.objects.get_or_create(
            warehouse=wh1, name="Reference & General"
        )

        # 3. Racks — capacity lives here.
        now = timezone.now()
        rack1, _ = Rack.objects.get_or_create(
            section=sec1,
            name="A1-Top",
            defaults={"max_capacity": 2500, "last_used": now},
        )
        Rack.objects.get_or_create(
            section=sec1,
            name="A1-Bottom",
            defaults={"max_capacity": 2500, "last_used": now},
        )
        rack3, _ = Rack.objects.get_or_create(
            section=sec2,
            name="CS-101",
            defaults={"max_capacity": 3000, "last_used": now},
        )
        Rack.objects.get_or_create(
            section=sec3,
            name="AH-101",
            defaults={"max_capacity": 2000, "last_used": now},
        )
        Rack.objects.get_or_create(
            section=sec2,
            name="CS-102",
            defaults={"max_capacity": 3000, "last_used": now},
        )
        Rack.objects.get_or_create(
            section=sec4,
            name="REF-101",
            defaults={"max_capacity": 2000, "last_used": now},
        )
        Rack.objects.get_or_create(
            section=sec3,
            name="AH-102",
            defaults={"max_capacity": 2000, "last_used": now},
        )
        Rack.objects.get_or_create(
            section=sec4,
            name="REF-102",
            defaults={"max_capacity": 2000, "last_used": now},
        )

        # 4. Vendors — `categories_supplied` is a JSON list, not a CSV string.
        vendor1, _ = Vendor.objects.get_or_create(
            gst_number="22AAAAA0000A1Z5",
            defaults={
                "company_name": "Penguin Distributors",
                "vendor_name": "Ramesh Kumar",
                "contact_person": "Ramesh Kumar",
                "email": "ramesh@penguin.test",
                "phone": "+91-9876543210",
                "categories_supplied": ["Fiction", "Non-Fiction"],
                "expected_delivery_days": 7,
                "payment_terms": "Net 30",
            },
        )

        vendor2, _ = Vendor.objects.get_or_create(
            gst_number="33BBBBB1111B2Z6",
            defaults={
                "company_name": "Tech Books India",
                "vendor_name": "Sita Sharma",
                "contact_person": "Sita Sharma",
                "email": "sita@techbooks.test",
                "categories_supplied": ["Engineering", "Computer Science"],
                "expected_delivery_days": 14,
                "payment_terms": "Net 45",
            },
        )

        # 5. Books — category is (class_level, board, subject); money is Decimal INR.
        book1, _ = Book.objects.get_or_create(
            isbn="978-0131103627",
            defaults={
                "title": "The C Programming Language",
                "author": "Brian W. Kernighan",
                "publisher": "Prentice Hall",
                "edition": "2nd",
                "language": "English",
                "subject": "Computer Science",
                "min_stock": 20,
                "mrp": "600.00",
                "tax_percent": "5.00",
                "default_warehouse": wh1,
                "default_section": sec2,
                "default_rack": rack3,
            },
        )

        book2, _ = Book.objects.get_or_create(
            isbn="978-0439708180",
            defaults={
                "title": "Harry Potter and the Sorcerer's Stone",
                "author": "J.K. Rowling",
                "publisher": "Scholastic",
                "language": "English",
                "subject": "Fiction",
                "min_stock": 50,
                "mrp": "499.00",
                "tax_percent": "5.00",
                "default_warehouse": wh1,
                "default_section": sec1,
                "default_rack": rack1,
            },
        )

        # 6. Stock ledger rows at zero. Balances come from the engine, below.
        BookInventory.objects.get_or_create(
            book=book1, rack=rack3, defaults={"vendor": vendor2}
        )
        BookInventory.objects.get_or_create(
            book=book2, rack=rack1, defaults={"vendor": vendor1}
        )

        # 7. Opening balances, through the one legal write path.
        opening = [
            (book1, rack3, vendor2, 50),
            (book2, rack1, vendor1, 150),
        ]
        seeded_stock = True
        for book, rack, vendor, quantity in opening:
            record = BookInventory.objects.get(book=book, rack=rack)
            if record.curr_stock:
                continue  # already seeded; stay idempotent
            try:
                apply_stock_movement(
                    book=book,
                    rack=rack,
                    quantity=quantity,
                    movement_type=MovementType.IN,
                    actor=None,
                    vendor=vendor,
                    reason="Seed data: opening balance.",
                )
            except NotImplementedError:
                seeded_stock = False
                break

        if seeded_stock:
            self.stdout.write(self.style.SUCCESS("Successfully seeded the database!"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Seeded catalog, locations and vendors. Stock left at zero: "
                    "apply_stock_movement() is still a stub (Team B, Task 2). "
                    "Re-run this command once it lands to fill the balances."
                )
            )

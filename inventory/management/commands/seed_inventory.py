from django.core.management.base import BaseCommand
from django.utils import timezone
from inventory.models import Warehouse, Section, Rack, Vendor, Book, BookInventory

class Command(BaseCommand):
    help = 'Seeds the database with initial inventory data for testing.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding inventory data...")

        # 1. Create Warehouses
        wh1, _ = Warehouse.objects.get_or_create(name="North Zone Main Hub")
        wh2, _ = Warehouse.objects.get_or_create(name="South City Reserve")

        # 2. Create Sections
        sec1, _ = Section.objects.get_or_create(
            warehouse=wh1, name="Fiction Wing", max_capacity=5000, current_stock=150
        )
        sec2, _ = Section.objects.get_or_create(
            warehouse=wh1, name="Engineering texts", max_capacity=3000, current_stock=50
        )

        # 3. Create Racks
        rack1, _ = Rack.objects.get_or_create(section=sec1, name="A1-Top", last_used=timezone.now())
        rack2, _ = Rack.objects.get_or_create(section=sec1, name="A1-Bottom", last_used=timezone.now())
        rack3, _ = Rack.objects.get_or_create(section=sec2, name="CS-101", last_used=timezone.now())

        # 4. Create Vendors
        vendor1, _ = Vendor.objects.get_or_create(
            gst_number="22AAAAA0000A1Z5",
            defaults={
                "company_name": "Penguin Distributors",
                "vendor_name": "Ramesh Kumar",
                "email": "ramesh@penguin.test",
                "phone": "+91-9876543210",
                "categories_supplied": "Fiction, Non-Fiction",
            }
        )
        
        vendor2, _ = Vendor.objects.get_or_create(
            gst_number="33BBBBB1111B2Z6",
            defaults={
                "company_name": "Tech Books India",
                "vendor_name": "Sita Sharma",
                "email": "sita@techbooks.test",
                "categories_supplied": "Engineering, Computer Science",
            }
        )

        # 5. Create Books
        book1, _ = Book.objects.get_or_create(
            isbn="978-0131103627",
            defaults={
                "title": "The C Programming Language",
                "author": "Brian W. Kernighan",
                "category": "Computer Science",
                "min_stock": 20,
                "cost": 450.00,
                "selling_price": 600.00
            }
        )

        book2, _ = Book.objects.get_or_create(
            isbn="978-0439708180",
            defaults={
                "title": "Harry Potter and the Sorcerer's Stone",
                "author": "J.K. Rowling",
                "category": "Fantasy",
                "min_stock": 50,
                "cost": 300.00,
                "selling_price": 499.00
            }
        )

        # 6. Create Inventory Ledger
        BookInventory.objects.get_or_create(
            book=book1, rack=rack3,
            defaults={"vendor": vendor2, "in_entry": 100, "out_entry": 50, "curr_stock": 50}
        )
        
        BookInventory.objects.get_or_create(
            book=book2, rack=rack1,
            defaults={"vendor": vendor1, "in_entry": 200, "out_entry": 50, "curr_stock": 150}
        )

        self.stdout.write(self.style.SUCCESS("Successfully seeded the database!"))
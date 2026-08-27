"""
The capacity-to-Rack data migration, exercised against real rows.

Every other test in this package runs against a database built by migrating a
schema onto *nothing*, which proves the migrations apply but says nothing
about whether `0003` carries the data down correctly. This one migrates back
to `0002`, writes rows through the historical models, and migrates forward.

It is the only migration in the project that moves data, and getting it wrong
loses every capacity number the warehouse has recorded.
"""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("inventory", "0002_sprint0_full_schema")]
# HEAD, not just the migration this test is about — `tearDown` uses this to
# restore the real schema for every test that runs after this one in the same
# session. Letting it lag behind HEAD (as it did when 0004 landed and this
# stayed at 0003) silently downgrades the live schema for the rest of the
# suite instead of "leaving the database at HEAD" as intended.
AFTER = [("inventory", "0004_warehouse_codes_and_active_flags")]


class CapacityMoveMigrationTests(TransactionTestCase):
    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        executor.loader.build_graph()
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        # Leave the database at HEAD so later tests are unaffected.
        self.migrate(AFTER)

    def test_capacity_is_split_across_racks_and_stock_comes_from_the_ledger(self):
        old_apps = self.migrate(BEFORE)

        Warehouse = old_apps.get_model("inventory", "Warehouse")
        Section = old_apps.get_model("inventory", "Section")
        Rack = old_apps.get_model("inventory", "Rack")
        Book = old_apps.get_model("inventory", "Book")
        BookInventory = old_apps.get_model("inventory", "BookInventory")

        warehouse = Warehouse.objects.create(name="Main")
        section = Section.objects.create(
            warehouse=warehouse, name="A", max_capacity=101, current_stock=0,
        )
        rack_1 = Rack.objects.create(section=section, name="A-1")
        rack_2 = Rack.objects.create(section=section, name="A-2")
        Rack.objects.create(section=section, name="A-3")

        book = Book.objects.create(title="Physics XII", isbn="9780000000001")
        BookInventory.objects.create(book=book, rack=rack_1, curr_stock=12)
        BookInventory.objects.create(book=book, rack=rack_2, curr_stock=5)

        new_apps = self.migrate(AFTER)
        Rack = new_apps.get_model("inventory", "Rack")
        racks = {rack.name: rack for rack in Rack.objects.all()}

        # 101 across three racks: 34 + 33 + 33, remainder to the first.
        self.assertEqual(
            sorted(rack.max_capacity for rack in racks.values()), [33, 33, 35],
        )
        # A-2 holds 5 books, so its 33-unit share stands; nothing was capped.
        self.assertEqual(racks["A-2"].max_capacity, 33)
        # The section's total is preserved, which is what the old column meant.
        self.assertEqual(sum(rack.max_capacity for rack in racks.values()), 101)

        # Stock comes from the ledger, not from the section's dead counter.
        self.assertEqual(racks["A-1"].current_stock, 12)
        self.assertEqual(racks["A-2"].current_stock, 5)
        self.assertEqual(racks["A-3"].current_stock, 0)

    def test_a_rack_holding_more_than_its_share_keeps_a_workable_capacity(self):
        """
        An even split can hand a rack less capacity than the stock already on
        it, which the `rack_stock_within_capacity` constraint would reject.
        The observed stock wins.
        """
        old_apps = self.migrate(BEFORE)

        Warehouse = old_apps.get_model("inventory", "Warehouse")
        Section = old_apps.get_model("inventory", "Section")
        Rack = old_apps.get_model("inventory", "Rack")
        Book = old_apps.get_model("inventory", "Book")
        BookInventory = old_apps.get_model("inventory", "BookInventory")

        warehouse = Warehouse.objects.create(name="Main")
        section = Section.objects.create(
            warehouse=warehouse, name="A", max_capacity=10, current_stock=0,
        )
        crowded = Rack.objects.create(section=section, name="A-1")
        Rack.objects.create(section=section, name="A-2")

        book = Book.objects.create(title="Physics XII", isbn="9780000000001")
        BookInventory.objects.create(book=book, rack=crowded, curr_stock=40)

        new_apps = self.migrate(AFTER)
        Rack = new_apps.get_model("inventory", "Rack")

        rack = Rack.objects.get(name="A-1")
        self.assertEqual(rack.current_stock, 40)
        self.assertGreaterEqual(rack.max_capacity, rack.current_stock)

    def test_a_section_with_no_racks_does_not_break_the_migration(self):
        old_apps = self.migrate(BEFORE)

        Warehouse = old_apps.get_model("inventory", "Warehouse")
        Section = old_apps.get_model("inventory", "Section")

        warehouse = Warehouse.objects.create(name="Main")
        Section.objects.create(
            warehouse=warehouse, name="Empty", max_capacity=50, current_stock=0,
        )

        new_apps = self.migrate(AFTER)
        self.assertEqual(new_apps.get_model("inventory", "Rack").objects.count(), 0)

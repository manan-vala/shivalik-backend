from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from staff_auth.models import Employee

from .models import Rack, Section, Warehouse
from .serializers import RackInfoSerializer, RackSerializer


class RackBehaviorTests(TestCase):
	def setUp(self):
		self.user = Employee.objects.create_user(
			email="warehouse@example.com",
			password="test-password",
			name="Warehouse User",
		)
		warehouse = Warehouse.objects.create(name="Main Warehouse")
		section = Section.objects.create(warehouse=warehouse, name="General")
		self.rack = Rack.objects.create(
			section=section,
			name="Rack A1",
			max_capacity=10,
		)

	def test_adjust_stock_updates_state_atomically(self):
		before = timezone.now()

		self.assertIsNone(self.rack.adjust_stock(4, self.user))

		self.rack.refresh_from_db()
		self.assertEqual(self.rack.current_stock, 4)
		self.assertEqual(self.rack.updated_by, self.user)
		self.assertGreaterEqual(self.rack.last_used, before)
		self.assertEqual(self.rack.last_used, self.rack.last_change_date)

	def test_adjust_stock_rejects_invalid_bounds(self):
		with self.assertRaises(ValidationError):
			self.rack.adjust_stock(-1)
		with self.assertRaises(ValidationError):
			self.rack.adjust_stock(11)

	def test_zero_capacity_is_unmeasured(self):
		self.rack.max_capacity = 0
		self.rack.save(update_fields=["max_capacity"])

		self.rack.adjust_stock(100)

		self.rack.refresh_from_db()
		self.assertEqual(self.rack.current_stock, 100)

	def test_rack_serializer_rejects_capacity_below_stock(self):
		self.rack.current_stock = 6
		self.rack.save(update_fields=["current_stock"])

		serializer = RackSerializer(
			self.rack,
			data={"max_capacity": 5},
			partial=True,
		)

		self.assertFalse(serializer.is_valid())
		self.assertIn("max_capacity", serializer.errors)

	def test_rack_info_calculates_empty_duration_and_book_count(self):
		self.rack.last_used = timezone.now() - timedelta(days=3)
		self.rack.save(update_fields=["last_used"])

		data = RackInfoSerializer(self.rack).data

		self.assertEqual(data["available"], 10)
		self.assertTrue(data["is_empty"])
		self.assertEqual(data["empty_for_days"], 3)
		self.assertEqual(data["books_stored"], 0)


class RackEndpointTests(TestCase):
	def test_rack_endpoints_require_authentication(self):
		client = APIClient()
		warehouse = Warehouse.objects.create(name="Main Warehouse")
		section = Section.objects.create(warehouse=warehouse, name="General")
		rack = Rack.objects.create(section=section, name="Rack A1")

		self.assertEqual(client.get("/api/v1/inventory/racks/").status_code, 401)
		self.assertEqual(
			client.get(f"/api/v1/inventory/racks/{rack.pk}/info/").status_code,
			401,
		)
		self.assertEqual(
			client.get("/api/v1/inventory/racks/empty/").status_code,
			401,
		)

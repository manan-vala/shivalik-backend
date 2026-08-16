from django.test import TestCase
from rest_framework.test import APIClient

from .models import Rack, Section, Warehouse


class WarehouseApiTests(TestCase):
	def setUp(self):
		self.client = APIClient()

	def test_health_endpoint(self):
		response = self.client.get("/api/health/")
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.json()["status"], "success")

	def test_create_warehouse(self):
		response = self.client.post(
			"/api/warehouses/",
			{
				"name": "Main Warehouse",
				"code": "WH-001",
				"location": "Industrial Area",
				"description": "Primary warehouse",
				"is_active": True,
			},
			format="json",
		)
		self.assertEqual(response.status_code, 201)
		self.assertEqual(Warehouse.objects.count(), 1)
		self.assertEqual(response.data["code"], "WH-001")

	def test_create_section_and_rack(self):
		warehouse = Warehouse.objects.create(
			name="Main Warehouse",
			code="WH-001",
			location="Industrial Area",
		)

		section_response = self.client.post(
			"/api/sections/",
			{
				"warehouse": warehouse.id,
				"name": "Cold Storage",
				"code": "SEC-01",
				"capacity": 1000,
				"current_stock": 200,
				"is_active": True,
			},
			format="json",
		)
		self.assertEqual(section_response.status_code, 201)

		rack_response = self.client.post(
			"/api/racks/",
			{
				"section": section_response.data["id"],
				"name": "Rack A1",
				"code": "R-001",
				"capacity": 100,
				"current_stock": 40,
				"is_active": True,
			},
			format="json",
		)
		self.assertEqual(rack_response.status_code, 201)
		self.assertEqual(Section.objects.count(), 1)
		self.assertEqual(Rack.objects.count(), 1)

	def test_rack_capacity_validation(self):
		warehouse = Warehouse.objects.create(name="Main Warehouse", code="WH-001")
		section = Section.objects.create(
			warehouse=warehouse,
			name="General",
			code="SEC-01",
			capacity=500,
			current_stock=100,
		)

		response = self.client.post(
			"/api/racks/",
			{
				"section": section.id,
				"name": "Rack A1",
				"code": "R-001",
				"capacity": 50,
				"current_stock": 60,
				"is_active": True,
			},
			format="json",
		)
		self.assertEqual(response.status_code, 400)
		self.assertIn("current_stock", response.data)

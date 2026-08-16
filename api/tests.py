"""
Sprint 0's headline claim: the API is closed by default (finding `C-1`).

Before this, every inventory route — including `stock-in`, `stock-out` and
vendor deletion — answered anonymous callers. These tests are what stops that
regressing the next time someone adds a viewset.
"""

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from staff_auth.models import Employee


class PublicRouteTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_is_public(self):
        response = self.client.get(reverse("api:health"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["status"], "success")

    def test_login_is_reachable_without_a_token(self):
        """It must not 401 — you cannot present a token to get a token."""
        response = self.client.post(reverse("token_obtain_pair"), {})
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_token_refresh_is_reachable_without_a_token(self):
        response = self.client.post(reverse("token_refresh"), {})
        self.assertNotEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class DefaultPermissionTests(TestCase):
    """C-1: anything not explicitly opened is closed."""

    def setUp(self):
        self.client = APIClient()

    def test_anonymous_cannot_read_the_catalog(self):
        response = self.client.get("/api/v1/inventory/books/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_cannot_move_stock(self):
        response = self.client.post(
            "/api/v1/inventory/books/1/stock-in/",
            {"rack": 1, "vendor": 1, "quantity": 5},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_anonymous_cannot_delete_a_vendor(self):
        response = self.client.delete("/api/v1/inventory/vendors/1/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_authenticated_staff_can_read_the_catalog(self):
        employee = Employee.objects.create_user(
            email="picker@shivalik.test",
            password="not-a-default-password",
            name="Picker",
            role=Employee.Role.INVENTORY_MANAGER,
            status=Employee.Status.APPROVED,
        )
        self.client.force_authenticate(user=employee)
        response = self.client.get("/api/v1/inventory/books/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class PaginationTests(TestCase):
    """M-5: list endpoints are paginated project-wide, not per view."""

    def setUp(self):
        self.client = APIClient()
        employee = Employee.objects.create_user(
            email="lister@shivalik.test",
            password="not-a-default-password",
            name="Lister",
            status=Employee.Status.APPROVED,
        )
        self.client.force_authenticate(user=employee)

    def test_list_responses_are_paginated(self):
        response = self.client.get("/api/v1/inventory/books/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.json()) & {"count", "next", "previous", "results"},
            {"count", "next", "previous", "results"},
        )


class SchemaEndpointTests(TestCase):
    """L-6: the frontend gets a real contract to build against."""

    def test_openapi_schema_is_served(self):
        response = self.client.get(reverse("schema"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

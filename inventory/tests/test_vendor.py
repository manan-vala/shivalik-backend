from datetime import timedelta

import pytest
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from inventory.models import (
    BookInventory,
    Book,
    PurchaseOrder,
    Rack,
    Section,
    Vendor,
    Warehouse,
)
from staff_auth.models import Employee

pytestmark = pytest.mark.django_db

@pytest.fixture
def admin_client():
    client = APIClient()
    admin = Employee.objects.create_superuser(email="admin@example.com", password="pass")
    admin.status = Employee.Status.APPROVED
    admin.save()
    client.force_authenticate(user=admin)
    return client

@pytest.fixture
def test_vendor():
    return Vendor.objects.create(
        company_name="Test Company",
        vendor_name="Tester",
        gst_number="27ABCDE1234F1Z5"
    )

@pytest.fixture
def test_book():
    return Book.objects.create(
        title="Test Book",
        isbn="978-3-16-148410-0",
        mrp=500
    )

@pytest.fixture
def test_rack():
    wh = Warehouse.objects.create(name="WH1")
    sec = Section.objects.create(warehouse=wh, name="SEC1")
    return Rack.objects.create(section=sec, name="R1", max_capacity=100)

def test_vendor_validations(admin_client):
    url = reverse('inventory:vendor-list')
    
    # Invalid phone
    resp = admin_client.post(url, {
        "company_name": "C1", "vendor_name": "V1", "gst_number": "27ABCDE1234F1Z5",
        "phone": "invalid123"
    })
    assert resp.status_code == 400
    assert "phone" in resp.data

    # Invalid GST
    resp = admin_client.post(url, {
        "company_name": "C1", "vendor_name": "V1", "gst_number": "BADGST",
    })
    assert resp.status_code == 400
    assert "gst_number" in resp.data

    # Valid
    resp = admin_client.post(url, {
        "company_name": "C1", "vendor_name": "V1", "gst_number": "27ABCDE1234F1Z5",
        "phone": "+919876543210"
    })
    assert resp.status_code == 201

def test_block_unblock_vendor(admin_client, test_vendor):
    block_url = reverse('inventory:vendor-block', kwargs={'pk': test_vendor.pk})
    resp = admin_client.patch(block_url)
    assert resp.status_code == 200
    test_vendor.refresh_from_db()
    assert test_vendor.is_blocked is True
    assert test_vendor.blocked_at is not None

    unblock_url = reverse('inventory:vendor-unblock', kwargs={'pk': test_vendor.pk})
    resp = admin_client.patch(unblock_url)
    assert resp.status_code == 200
    test_vendor.refresh_from_db()
    assert test_vendor.is_blocked is False
    assert test_vendor.unblocked_at is not None

def test_purchase_order_transitions(admin_client, test_vendor):
    url = reverse('inventory:purchase-order-list')
    resp = admin_client.post(url, {
        "vendor": test_vendor.pk,
        "status": "DRAFT"
    }, format="json")
    assert resp.status_code == 201
    po_id = resp.data["id"]

    detail_url = reverse('inventory:purchase-order-detail', kwargs={'pk': po_id})
    receive_url = reverse('inventory:purchase-order-receive', kwargs={'pk': po_id})
    dispatch_url = reverse('inventory:purchase-order-dispatch-po', kwargs={'pk': po_id})
    
    # Try jumping directly to RECEIVED using receive endpoint
    resp = admin_client.patch(receive_url, {"lines": []}, format="json")
    assert resp.status_code == 400

    # Go DRAFT -> DISPATCHED using dispatch endpoint
    resp = admin_client.patch(dispatch_url)
    assert resp.status_code == 200

def test_purchase_order_receive_flow(admin_client, test_vendor, test_book, test_rack):
    # 1. Create PO
    po = PurchaseOrder.objects.create(vendor=test_vendor, status=PurchaseOrder.Status.DISPATCHED)
    line = po.lines.create(book=test_book, quantity_ordered=10, unit_price=150.00)

    # 2. Receive via endpoint
    receive_url = reverse('inventory:purchase-order-receive', kwargs={'pk': po.pk})
    resp = admin_client.patch(receive_url, {
        "lines": [
            {"line_id": line.pk, "quantity_received": 10, "rack_id": test_rack.pk}
        ]
    }, format="json")

    assert resp.status_code == 200
    
    po.refresh_from_db()
    line.refresh_from_db()
    assert po.status == PurchaseOrder.Status.RECEIVED
    assert line.quantity_received == 10

    # 3. Verify stock movement and inventory
    test_rack.refresh_from_db()
    assert test_rack.current_stock == 10
    
    # Check BookInventory
    inv = BookInventory.objects.get(book=test_book, rack=test_rack)
    assert inv.curr_stock == 10
    
    # Stock Movement row should exist
    assert test_book.movements.filter(movement_type="RECEIVE").exists()

@override_settings(ENFORCE_ROLE_PERMISSIONS=True)
def test_permission_denied(test_vendor):
    # Unauthenticated user
    client = APIClient()
    
    list_url = reverse('inventory:vendor-list')
    assert client.get(list_url).status_code == 401
    
    block_url = reverse('inventory:vendor-block', kwargs={'pk': test_vendor.pk})
    assert client.patch(block_url).status_code == 401
    
    # Authenticated but not approved/admin
    user = Employee.objects.create(email="user@example.com", password="pass")
    client.force_authenticate(user=user)
    
    assert client.get(list_url).status_code == 403
    assert client.patch(block_url).status_code == 403


# --- receipt guards -------------------------------------------------------
#
# The first cut of `receive` wrapped its body in `except Exception` and
# returned every failure as a 400 carrying the raw exception text, incremented
# `quantity_received` with a read-modify-write, and marked the order RECEIVED
# no matter how little of it actually turned up. These pin the corrected
# behaviour.

@pytest.fixture
def dispatched_po(test_vendor, test_book):
    po = PurchaseOrder.objects.create(
        vendor=test_vendor, status=PurchaseOrder.Status.DISPATCHED,
    )
    po.lines.create(book=test_book, quantity_ordered=10, unit_price=150.00)
    return po


def test_receive_rejects_over_receipt(admin_client, dispatched_po, test_rack):
    line = dispatched_po.lines.get()
    url = reverse('inventory:purchase-order-receive', kwargs={'pk': dispatched_po.pk})

    resp = admin_client.patch(url, {
        "lines": [{"line_id": line.pk, "quantity_received": 11, "rack_id": test_rack.pk}]
    }, format="json")

    assert resp.status_code == 400
    line.refresh_from_db()
    dispatched_po.refresh_from_db()
    test_rack.refresh_from_db()
    # Nothing booked in: the rejection happens before the engine is called.
    assert line.quantity_received == 0
    assert dispatched_po.status == PurchaseOrder.Status.DISPATCHED
    assert test_rack.current_stock == 0


def test_partial_receipt_leaves_order_dispatched(admin_client, dispatched_po, test_rack):
    line = dispatched_po.lines.get()
    url = reverse('inventory:purchase-order-receive', kwargs={'pk': dispatched_po.pk})

    resp = admin_client.patch(url, {
        "lines": [{"line_id": line.pk, "quantity_received": 4, "rack_id": test_rack.pk}]
    }, format="json")

    assert resp.status_code == 200
    line.refresh_from_db()
    dispatched_po.refresh_from_db()
    assert line.quantity_received == 4
    assert dispatched_po.status == PurchaseOrder.Status.DISPATCHED

    # The rest arrives later and closes the order.
    resp = admin_client.patch(url, {
        "lines": [{"line_id": line.pk, "quantity_received": 6, "rack_id": test_rack.pk}]
    }, format="json")

    assert resp.status_code == 200
    line.refresh_from_db()
    dispatched_po.refresh_from_db()
    test_rack.refresh_from_db()
    assert line.quantity_received == 10
    assert dispatched_po.status == PurchaseOrder.Status.RECEIVED
    assert test_rack.current_stock == 10


def test_receive_is_atomic_across_lines(admin_client, dispatched_po, test_rack):
    """A bad second line must roll the first one back, stock included."""
    line = dispatched_po.lines.get()
    other = Book.objects.create(title="Second", isbn="978-0-13-235088-4", mrp=100)
    bad_line = dispatched_po.lines.create(
        book=other, quantity_ordered=5, unit_price=100.00,
    )
    url = reverse('inventory:purchase-order-receive', kwargs={'pk': dispatched_po.pk})

    resp = admin_client.patch(url, {
        "lines": [
            {"line_id": line.pk, "quantity_received": 3, "rack_id": test_rack.pk},
            {"line_id": bad_line.pk, "quantity_received": 99, "rack_id": test_rack.pk},
        ]
    }, format="json")

    assert resp.status_code == 400
    line.refresh_from_db()
    test_rack.refresh_from_db()
    assert line.quantity_received == 0
    assert test_rack.current_stock == 0
    assert not BookInventory.objects.filter(curr_stock__gt=0).exists()


def test_receive_rejects_non_integer_quantity(admin_client, dispatched_po, test_rack):
    """Garbage in the payload is a 400, not a 500 from int()."""
    line = dispatched_po.lines.get()
    url = reverse('inventory:purchase-order-receive', kwargs={'pk': dispatched_po.pk})

    resp = admin_client.patch(url, {
        "lines": [{"line_id": line.pk, "quantity_received": "ten", "rack_id": test_rack.pk}]
    }, format="json")

    assert resp.status_code == 400


# --- reorder / dead stock -------------------------------------------------

def test_reorder_creates_draft_po_for_low_stock(admin_client, test_vendor, test_rack):
    low = Book.objects.create(
        title="Below Threshold", isbn="978-1-4028-9462-6", mrp=200, min_stock=50,
    )
    Book.objects.create(
        title="No Threshold", isbn="978-0-306-40615-7", mrp=200, min_stock=0,
    )
    url = reverse('inventory:stock-reorder')

    resp = admin_client.post(url, {"vendor_id": test_vendor.pk}, format="json")

    assert resp.status_code == 201
    po = PurchaseOrder.objects.get(pk=resp.data["purchase_order"])
    assert po.status == PurchaseOrder.Status.DRAFT
    assert po.vendor == test_vendor
    # Only the title actually under its min_stock is ordered.
    assert [line.book_id for line in po.lines.all()] == [low.pk]
    assert po.lines.get().quantity_ordered == 50


def test_reorder_refuses_blocked_vendor(admin_client, test_vendor):
    Book.objects.create(
        title="Below Threshold", isbn="978-1-4028-9462-6", mrp=200, min_stock=50,
    )
    test_vendor.is_blocked = True
    test_vendor.save(update_fields=["is_blocked"])

    resp = admin_client.post(
        reverse('inventory:stock-reorder'), {"vendor_id": test_vendor.pk}, format="json",
    )

    assert resp.status_code == 400
    assert not PurchaseOrder.objects.exists()


def test_dead_stock_respects_per_title_threshold(admin_client, test_rack, test_vendor):
    """
    Ageing is compared in SQL against the title's own threshold, falling back
    to settings.DEAD_STOCK_DEFAULT_DAYS. The earlier version looped in Python
    over every BookInventory row.
    """
    stale = Book.objects.create(
        title="Stale", isbn="978-0-321-75104-1", mrp=100, dead_stock_threshold_days=30,
    )
    patient = Book.objects.create(
        title="Patient", isbn="978-0-201-63361-0", mrp=100,
        dead_stock_threshold_days=3650,
    )
    long_ago = timezone.now() - timedelta(days=400)
    for book in (stale, patient):
        BookInventory.objects.create(
            book=book, rack=test_rack, curr_stock=5, last_out_at=long_ago,
        )
    # Holding no stock is not dead stock, however old it is.
    empty = Book.objects.create(title="Empty", isbn="978-0-596-52068-7", mrp=100)
    BookInventory.objects.create(
        book=empty, rack=test_rack, curr_stock=0, last_out_at=long_ago,
    )

    resp = admin_client.get(reverse('inventory:stock-dead-stock'))

    assert resp.status_code == 200
    titles = {row["book_title"] for row in resp.data["results"]}
    assert titles == {"Stale"}

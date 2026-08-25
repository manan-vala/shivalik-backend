import pytest
from rest_framework.test import APIClient
from django.urls import reverse
from django.test import override_settings
from inventory.models import Vendor, PurchaseOrder, Book, Rack, Section, Warehouse, BookInventory
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

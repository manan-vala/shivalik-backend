"""
Guards that turn the database's refusals into client errors.

Each of these used to reach the client as the wrong thing: a 500 for a
protected delete, a 204 for deleting a received purchase order, a 200 for
stock booked onto a retired rack.
"""

import pytest
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from inventory.models import (
    Book,
    MovementType,
    PurchaseOrder,
    Rack,
    Section,
    Vendor,
    Warehouse,
    apply_stock_movement,
)
from staff_auth.models import Employee

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return Employee.objects.create_superuser(
        email="guards@example.com", password="guard-lantern-5530", name="Guards",
    )


@pytest.fixture
def client(admin):
    c = APIClient()
    c.force_authenticate(user=admin)
    return c


@pytest.fixture
def stocked(admin):
    """One book with one movement onto one rack — enough history to protect."""
    wh = Warehouse.objects.create(name="Guard WH")
    rack = Rack.objects.create(
        section=Section.objects.create(warehouse=wh, name="Guard S"),
        name="Guard R", max_capacity=100,
    )
    vendor = Vendor.objects.create(
        company_name="Guard V", vendor_name="GV", gst_number="27ABCDE1234F1Z5",
    )
    book = Book.objects.create(title="Guard B", isbn="978-0-00-000000-1", mrp=10)
    apply_stock_movement(
        book=book, rack=rack, quantity=5, movement_type=MovementType.IN,
        actor=admin, vendor=vendor,
    )
    return {"warehouse": wh, "rack": rack, "vendor": vendor, "book": book}


# -- protected deletes: 409, not 500 --------------------------------------

@pytest.mark.parametrize(
    "kind, route, model, hint",
    [
        ("vendor", "inventory:vendor-detail", Vendor, "Block it instead."),
        ("book", "inventory:book-detail", Book, None),
        ("rack", "inventory:rack-detail", Rack, "Deactivate it instead."),
        ("warehouse", "inventory:warehouse-detail", Warehouse, "Deactivate it instead."),
    ],
)
def test_deleting_a_row_with_stock_history_is_a_409(client, stocked, kind, route, model, hint):
    obj = stocked[kind]
    response = client.delete(reverse(route, kwargs={"pk": obj.pk}))

    assert response.status_code == 409
    detail = response.data["detail"]
    assert "stock movement" in detail
    if hint:
        assert detail.endswith(hint)
    else:
        assert "instead" not in detail
    assert model.objects.filter(pk=obj.pk).exists()


def test_a_refused_vendor_delete_writes_no_audit_row(client, stocked):
    from auditlog.models import AuditLog

    client.delete(reverse("inventory:vendor-detail", kwargs={"pk": stocked["vendor"].pk}))
    assert not AuditLog.objects.filter(action=AuditLog.Action.DELETE).exists()


# -- purchase orders: only a DRAFT may be deleted ----------------------------

@pytest.mark.parametrize(
    "status, hint",
    [
        (PurchaseOrder.Status.PLACED, True),
        (PurchaseOrder.Status.DISPATCHED, True),
        (PurchaseOrder.Status.RECEIVED, False),
        (PurchaseOrder.Status.CANCELLED, False),
    ],
)
def test_only_a_draft_purchase_order_can_be_deleted(client, stocked, status, hint):
    po = PurchaseOrder.objects.create(vendor=stocked["vendor"], status=status)
    response = client.delete(reverse("inventory:purchase-order-detail", kwargs={"pk": po.pk}))

    assert response.status_code == 400
    # A plain string, like dispatch/receive's own status refusals.
    assert isinstance(response.data["detail"], str)
    assert ("Cancel it instead" in response.data["detail"]) is hint
    assert PurchaseOrder.objects.filter(pk=po.pk).exists()


def test_a_draft_purchase_order_can_be_deleted(client, stocked):
    po = PurchaseOrder.objects.create(vendor=stocked["vendor"])
    response = client.delete(reverse("inventory:purchase-order-detail", kwargs={"pk": po.pk}))

    assert response.status_code == 204
    assert not PurchaseOrder.objects.filter(pk=po.pk).exists()


# -- inactive locations take no new stock ------------------------------------

def _deactivate(obj):
    # `.update()`, not `obj.save()`: the fixture's in-memory rack predates the
    # stock movement, and a full save would write its stale `current_stock`
    # back over the real one.
    type(obj).objects.filter(pk=obj.pk).update(is_active=False)


@pytest.mark.parametrize("retired", ["rack", "section", "warehouse"])
def test_inbound_stock_is_refused_on_an_inactive_location(admin, stocked, retired):
    rack = stocked["rack"]
    target = {"rack": rack, "section": rack.section, "warehouse": rack.section.warehouse}[retired]
    _deactivate(target)
    rack.refresh_from_db()

    with pytest.raises(ValidationError) as exc:
        apply_stock_movement(
            book=stocked["book"], rack=rack, quantity=1,
            movement_type=MovementType.IN, actor=admin, vendor=stocked["vendor"],
        )
    assert "rack" in exc.value.detail


def test_an_inactive_rack_can_still_be_emptied(admin, stocked):
    rack = stocked["rack"]
    _deactivate(rack)
    rack.refresh_from_db()

    record = apply_stock_movement(
        book=stocked["book"], rack=rack, quantity=5,
        movement_type=MovementType.OUT, actor=admin,
    )
    assert record.curr_stock == 0


def test_receiving_a_po_onto_an_inactive_rack_is_refused(client, stocked):
    po = PurchaseOrder.objects.create(
        vendor=stocked["vendor"], status=PurchaseOrder.Status.DISPATCHED,
    )
    line = po.lines.create(book=stocked["book"], quantity_ordered=2, unit_price=1)
    rack = stocked["rack"]
    _deactivate(rack)

    response = client.patch(
        reverse("inventory:purchase-order-receive", kwargs={"pk": po.pk}),
        {"lines": [{"line_id": line.pk, "quantity_received": 2, "rack_id": rack.pk}]},
        format="json",
    )

    assert response.status_code == 400
    line.refresh_from_db()
    assert line.quantity_received == 0

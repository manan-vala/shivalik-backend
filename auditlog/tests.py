from unittest import mock

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework.test import APIClient

from auditlog.models import AuditLog
from inventory.models import (
    Book,
    PurchaseOrder,
    PurchaseOrderLine,
    Rack,
    Section,
    Vendor,
    Warehouse,
)
from staff_auth.models import Employee

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    user = Employee.objects.create_superuser(email="admin@example.com", password="pass")
    user.status = Employee.Status.APPROVED
    user.save()
    return user


@pytest.fixture
def client(admin):
    c = APIClient()
    c.force_authenticate(user=admin)
    return c


@pytest.fixture
def vendor():
    return Vendor.objects.create(
        company_name="Acme", vendor_name="A", gst_number="27ABCDE1234F1Z5"
    )


@pytest.fixture
def book():
    return Book.objects.create(title="B1", isbn="978-3-16-148410-0", mrp=500)


@pytest.fixture
def book2():
    return Book.objects.create(title="B2", isbn="978-0-306-40615-7", mrp=300)


@pytest.fixture
def rack():
    wh = Warehouse.objects.create(name="WH1")
    sec = Section.objects.create(warehouse=wh, name="S1")
    return Rack.objects.create(section=sec, name="R1", max_capacity=100)


def logs_for(obj):
    return AuditLog.objects.filter(
        content_type=ContentType.objects.get_for_model(obj), object_id=str(obj.pk)
    )


def test_create_is_logged_with_actor(client, admin):
    resp = client.post(
        reverse("inventory:vendor-list"),
        {"company_name": "New", "vendor_name": "N", "gst_number": "27ABCDE1234F1Z5"},
    )
    assert resp.status_code == 201
    log = AuditLog.objects.get(action=AuditLog.Action.CREATE)
    assert log.actor == admin
    assert log.object_id == str(resp.data["id"])
    assert log.changes["after"]["company_name"] == "New"


def test_update_logs_only_the_diff(client, vendor):
    resp = client.patch(
        reverse("inventory:vendor-detail", kwargs={"pk": vendor.pk}), {"notes": "late"}
    )
    assert resp.status_code == 200
    log = logs_for(vendor).get(action=AuditLog.Action.UPDATE)
    assert log.changes == {"diff": {"notes": {"old": "", "new": "late"}}}


def test_noop_update_writes_nothing(client, vendor):
    client.patch(
        reverse("inventory:vendor-detail", kwargs={"pk": vendor.pk}),
        {"company_name": vendor.company_name},
    )
    assert not logs_for(vendor).exists()


def test_delete_keeps_a_snapshot(client, vendor):
    pk = vendor.pk
    resp = client.delete(reverse("inventory:vendor-detail", kwargs={"pk": pk}))
    assert resp.status_code == 204
    log = AuditLog.objects.get(action=AuditLog.Action.DELETE)
    assert log.object_id == str(pk)
    assert log.changes["before"]["company_name"] == "Acme"


def test_replacing_po_lines_is_audited_and_response_is_fresh(client, vendor, book, book2):
    po = PurchaseOrder.objects.create(vendor=vendor)
    PurchaseOrderLine.objects.create(
        purchase_order=po, book=book, quantity_ordered=5, unit_price="10.00"
    )

    resp = client.patch(
        reverse("inventory:purchase-order-detail", kwargs={"pk": po.pk}),
        {"lines": [{"book": book2.pk, "quantity_ordered": 7, "unit_price": "12.00"}]},
        format="json",
    )

    assert resp.status_code == 200
    assert [line["book"] for line in resp.data["lines"]] == [book2.pk]
    diff = logs_for(po).get(action=AuditLog.Action.UPDATE).changes["diff"]
    assert [line["book"] for line in diff["lines"]["old"]] == [book.pk]
    assert [line["book"] for line in diff["lines"]["new"]] == [book2.pk]


def test_audit_failure_rolls_back_the_mutation(client):
    client.raise_request_exception = False
    with mock.patch.object(AuditLog.objects, "create", side_effect=RuntimeError("boom")):
        resp = client.post(
            reverse("inventory:vendor-list"),
            {"company_name": "Ghost", "vendor_name": "G", "gst_number": "27ABCDE1234F1Z5"},
        )
    assert resp.status_code == 500
    assert not Vendor.objects.filter(company_name="Ghost").exists()


def test_block_and_unblock_are_logged(client, vendor):
    client.patch(reverse("inventory:vendor-block", kwargs={"pk": vendor.pk}))
    client.patch(reverse("inventory:vendor-unblock", kwargs={"pk": vendor.pk}))
    actions = list(logs_for(vendor).order_by("id").values_list("action", flat=True))
    assert actions == [AuditLog.Action.BLOCK, AuditLog.Action.UNBLOCK]
    block = logs_for(vendor).get(action=AuditLog.Action.BLOCK)
    assert block.changes["diff"]["is_blocked"] == {"old": False, "new": True}


def test_dispatch_and_receive_are_logged(client, vendor, book, rack):
    po = PurchaseOrder.objects.create(vendor=vendor, status=PurchaseOrder.Status.PLACED)
    line = PurchaseOrderLine.objects.create(
        purchase_order=po, book=book, quantity_ordered=5, unit_price="10.00"
    )
    client.patch(reverse("inventory:purchase-order-dispatch-po", kwargs={"pk": po.pk}))
    client.patch(
        reverse("inventory:purchase-order-receive", kwargs={"pk": po.pk}),
        {"lines": [{"line_id": line.pk, "quantity_received": 5, "rack_id": rack.pk}]},
        format="json",
    )

    dispatch = logs_for(po).get(action=AuditLog.Action.DISPATCH)
    assert dispatch.changes["diff"]["status"] == {
        "old": PurchaseOrder.Status.PLACED,
        "new": PurchaseOrder.Status.DISPATCHED,
    }
    receive = logs_for(po).get(action=AuditLog.Action.RECEIVE)
    assert receive.changes["diff"]["status"]["new"] == PurchaseOrder.Status.RECEIVED
    assert receive.changes["received"] == [
        {"line_id": line.pk, "quantity_received": 5, "rack_id": rack.pk}
    ]


def test_rejected_receive_writes_no_log(client, vendor, book, rack):
    po = PurchaseOrder.objects.create(vendor=vendor, status=PurchaseOrder.Status.DISPATCHED)
    line = PurchaseOrderLine.objects.create(
        purchase_order=po, book=book, quantity_ordered=5, unit_price="10.00"
    )
    resp = client.patch(
        reverse("inventory:purchase-order-receive", kwargs={"pk": po.pk}),
        {"lines": [{"line_id": line.pk, "quantity_received": 99, "rack_id": rack.pk}]},
        format="json",
    )
    assert resp.status_code == 400
    assert not logs_for(po).exists()


def test_admin_is_read_only_and_searchable(admin):
    c = APIClient()
    c.force_login(admin)
    AuditLog.objects.create(
        actor=admin,
        action=AuditLog.Action.CREATE,
        content_type=ContentType.objects.get_for_model(Vendor),
        object_id="1",
    )
    assert c.get("/admin/auditlog/auditlog/?q=admin@example.com").status_code == 200
    assert c.get("/admin/auditlog/auditlog/add/").status_code == 403

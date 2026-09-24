import json
import logging
import logging.config
from unittest import mock

import pytest
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from api.observability import RequestIdFilter
from api.views import TelemetryThrottle
from staff_auth.models import Employee

pytestmark = pytest.mark.django_db

TELEMETRY = "/api/v1/telemetry/"


@pytest.fixture(autouse=True)
def fresh_throttle():
    cache.clear()


@pytest.fixture
def user():
    u = Employee.objects.create_user(email="picker@shivalik.test", password="pass")
    u.status = Employee.Status.APPROVED
    u.save()
    return u


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def access_records(caplog):
    return [r for r in caplog.records if r.name == "shivalik.request"]


def test_every_request_gets_one_access_line(client, user, caplog):
    with caplog.at_level(logging.INFO, logger="shivalik.request"):
        resp = client.get("/api/v1/inventory/books/?token=secret")

    [record] = access_records(caplog)
    assert record.method == "GET"
    assert record.path == "/api/v1/inventory/books/"
    assert record.status == 200
    assert record.user_id == user.pk
    assert record.duration_ms >= 0
    assert "secret" not in record.getMessage()
    assert len(resp["X-Request-ID"]) == 32


def test_client_request_id_is_kept_when_sane_and_replaced_when_not(client):
    assert client.get(reverse("api:health"), HTTP_X_REQUEST_ID="abc-123")["X-Request-ID"] == "abc-123"
    assert client.get(reverse("api:health"), HTTP_X_REQUEST_ID="bad\nid")["X-Request-ID"] != "bad\nid"


def test_log_lines_inside_a_request_carry_its_id(client, caplog):
    caplog.handler.addFilter(RequestIdFilter())
    with caplog.at_level(logging.INFO):
        resp = client.post(TELEMETRY, {"event": "export_clicked"}, format="json")
    [record] = [r for r in caplog.records if r.name == "shivalik.telemetry"]
    assert record.request_id == resp["X-Request-ID"]


def test_djangos_own_error_records_carry_the_request_id(caplog):
    caplog.handler.addFilter(RequestIdFilter())
    with caplog.at_level(logging.WARNING, logger="django.request"):
        resp = APIClient().get("/api/v1/inventory/books/")
    [record] = [r for r in caplog.records if r.name == "django.request"]
    assert record.status_code == 401
    assert record.request_id == resp["X-Request-ID"]


def test_json_formatter_emits_one_parseable_line():
    config = dict(settings.LOGGING["formatters"]["json"])
    formatter = config.pop("()")
    formatter = logging.config.DictConfigurator({}).resolve(formatter)(**config)
    record = logging.LogRecord("shivalik.request", logging.INFO, "", 0, "GET / 200", (), None)
    record.request_id = "abc"
    record.status = 200

    line = formatter.format(record)

    assert "\n" not in line
    assert json.loads(line) | {"timestamp": None} == {
        "level": "INFO",
        "logger": "shivalik.request",
        "message": "GET / 200",
        "request_id": "abc",
        "status": 200,
        "timestamp": None,
    }


def test_telemetry_is_closed_to_anonymous_callers():
    assert APIClient().post(TELEMETRY, {"event": "x"}, format="json").status_code == 401


def test_telemetry_logs_and_never_touches_the_database(client, user, caplog, django_assert_num_queries):
    payload = {
        "level": "error",
        "event": "render_failed",
        "message": "Cannot read properties of undefined",
        "url": "/vendors/12",
        "context": {"component": "VendorTable"},
    }
    with caplog.at_level(logging.INFO, logger="shivalik.telemetry"):
        with django_assert_num_queries(0):
            resp = client.post(TELEMETRY, payload, format="json")

    assert resp.status_code == 204
    [record] = [r for r in caplog.records if r.name == "shivalik.telemetry"]
    assert record.levelno == logging.ERROR
    assert record.user_id == user.pk
    assert record.telemetry["context"] == {"component": "VendorTable"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"event": "has spaces"},
        {"event": "x", "level": "critical"},
        {"event": "x", "message": "m" * 2001},
        {"event": "x", "context": {"blob": "b" * 4000}},
    ],
)
def test_telemetry_rejects_malformed_or_oversized_events(client, payload):
    assert client.post(TELEMETRY, payload, format="json").status_code == 400


def test_telemetry_is_rate_limited(client):
    with mock.patch.dict(TelemetryThrottle.THROTTLE_RATES, {"telemetry": "2/min"}):
        codes = [client.post(TELEMETRY, {"event": "x"}, format="json").status_code for _ in range(3)]
    assert codes == [204, 204, 429]

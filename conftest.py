"""
Project-wide pytest configuration.

Two things live here:

1. `@pytest.mark.postgres_only` skips instead of running. A concurrency test
   on SQLite does not fail — it *passes*, because `select_for_update()` is
   ignored and the two threads never contend. A green tick
   that proves nothing is worse than a red one, so the marker makes the gap
   visible in the test report::

       @pytest.mark.postgres_only
       def test_two_stock_outs_cannot_oversell(...):
           ...

2. HTTPS redirects are turned off for the duration of the run — see below.
"""

import pytest
from django.db import connection
from django.test.utils import override_settings


@pytest.fixture(autouse=True, scope="session")
def plain_http_for_tests():
    """
    Tests are not a TLS deployment.

    `DJANGO_DEBUG=false` — what CI runs, and what anyone verifying a
    production-shaped config runs — enables `SECURE_SSL_REDIRECT`. Django's
    test client speaks plain HTTP, so `SecurityMiddleware` answers every
    request with a 301 to `https://testserver` and every status-code
    assertion in the suite fails at once.

    This cannot be done by setting an environment variable in this file:
    pytest-django calls `django.setup()` from `pytest_load_initial_conftests`,
    which runs *before* conftest modules are imported, so settings are already
    resolved by the time this line is read. It has to be an override applied
    at test time.
    """
    with override_settings(SECURE_SSL_REDIRECT=False, SECURE_HSTS_SECONDS=0):
        yield


def pytest_collection_modifyitems(config, items):
    if connection.vendor == "postgresql":
        return

    skip = pytest.mark.skip(
        reason=(
            f"needs PostgreSQL row locking; DB engine is {connection.vendor!r}. "
            "Run `docker compose up -d db` and set DB_ENGINE=postgresql."
        )
    )
    for item in items:
        if "postgres_only" in item.keywords:
            item.add_marker(skip)

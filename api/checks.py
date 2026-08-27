"""
Deployment checks that run on every ``manage.py`` command.

These exist because two of this project's worst failure modes are silent:

* SQLite accepts ``SELECT … FOR UPDATE`` and silently ignores it, so
  the stock ledger's locking looks correct in code, passes its tests, and
  protects nothing.
* ``DEBUG`` left on in a deployed environment leaks the settings module on any
  exception.

Neither shows up as an error at runtime, so they are surfaced here instead.
"""

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

# Same finding, two severities — Django's convention is that the id prefix
# matches the level it is reported at.
DB_ENGINE_WARNING_ID = "api.W001"
DB_ENGINE_ERROR_ID = "api.E001"
DEBUG_ID = "api.W002"


@register(Tags.database)
def check_database_is_postgresql(app_configs, **kwargs):
    """This project requires PostgreSQL; warn (or fail) when we are not on it."""
    engine = settings.DATABASES["default"]["ENGINE"]
    if engine.endswith("postgresql"):
        return []

    message = (
        f"Database engine is {engine!r}, not PostgreSQL. "
        "select_for_update() is a silent no-op outside PostgreSQL, so "
        "the stock ledger's row locking does nothing and concurrency tests "
        "pass without proving anything."
    )
    hint = (
        "Run `docker compose up -d db` and set DB_ENGINE=postgresql in .env. "
        "SQLite is only acceptable for offline schema work."
    )

    if settings.DEBUG:
        # Local schema work on SQLite is tolerated; shipping on it is not.
        return [Warning(message, hint=hint, id=DB_ENGINE_WARNING_ID)]
    return [Error(message, hint=hint, id=DB_ENGINE_ERROR_ID)]


@register(Tags.security, deploy=True)
def check_debug_is_off(app_configs, **kwargs):
    """Belt-and-braces alongside Django's own ``security.W018``."""
    if settings.DEBUG:
        return [
            Warning(
                "DEBUG is enabled.",
                hint="Set DJANGO_DEBUG=false in .env for anything shared.",
                id=DEBUG_ID,
            )
        ]
    return []

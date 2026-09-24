"""
Operational logging: request correlation and per-request access logs.

Nothing here touches the database. Business history lives in `auditlog`;
this is telemetry, and it goes to stdout (or `LOG_FILE`) only.
"""

import logging
import re
import time
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# A client may send its own id so frontend telemetry and backend logs line up.
# Anything that does not look like an id is replaced, not trusted.
_CLIENT_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

access_log = logging.getLogger("shivalik.request")


class RequestIdFilter(logging.Filter):
    """Stamps every record with the current request's id, or "-" outside one."""

    def filter(self, record):
        request_id = request_id_var.get()
        if request_id == "-":
            # `django.request` logs 4xx/5xx after the middleware chain has
            # returned, so the context is gone, but it attaches the request.
            request_id = getattr(getattr(record, "request", None), "request_id", "-")
        record.request_id = request_id
        return True


class RequestLogMiddleware:
    """One structured line per request: method, path, status, duration, user."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        request_id = incoming if _CLIENT_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            # DRF authenticates inside the view and writes the user back onto
            # the Django request, so it is only known after the response.
            user = getattr(request, "user", None)
            user_id = user.pk if user is not None and user.is_authenticated else None
            # `request.path`, not the full URL: query strings can carry tokens.
            access_log.info(
                "%s %s %s %sms",
                request.method,
                request.path,
                response.status_code,
                duration_ms,
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                    "user_id": user_id,
                },
            )
            response["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)

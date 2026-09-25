"""
Project-wide DRF exception handler.

DRF's default handler only translates its own `APIException`s; anything else
reaches Django as an unhandled exception and the client gets a 500. That is
right for genuine bugs, and wrong for the database refusing a delete on
purpose.

The stock ledger's foreign keys are `on_delete=PROTECT` so stock history can
never be orphaned. Deleting a vendor, book, rack, warehouse or purchase order
that has history therefore raises `ProtectedError` — the protection working —
which used to surface as a 500 and an ERROR line in the operational log for
what is a user mistake. It is now a 409 that says what still depends on the
row.
"""

from django.db.models import ProtectedError, RestrictedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def _describe(objects) -> str:
    """'3 stock movements, 1 book inventory' — what is still holding on."""
    counts: dict[str, int] = {}
    for obj in objects:
        meta = obj._meta
        counts[str(meta.verbose_name_plural)] = counts.get(str(meta.verbose_name_plural), 0) + 1
    return ", ".join(f"{n} {name.lower()}" for name, n in sorted(counts.items()))


def _deleting_model(context):
    view = context.get("view")
    try:
        return view.get_queryset().model
    except Exception:  # noqa: BLE001 — best effort, only used to phrase a hint
        return None


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is not None:
        return response

    if isinstance(exc, (ProtectedError, RestrictedError)):
        blocking = exc.protected_objects if isinstance(exc, ProtectedError) else exc.restricted_objects
        detail = f"Can't delete this: it still has history ({_describe(blocking)})."
        model = _deleting_model(context)
        if model is not None and any(f.name == "is_active" for f in model._meta.get_fields()):
            detail += " Deactivate it instead."
        return Response({"detail": detail}, status=status.HTTP_409_CONFLICT)

    return None

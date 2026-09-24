from contextlib import contextmanager

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import AuditLog


def diff(before, after):
    return {
        key: {"old": before.get(key), "new": after.get(key)}
        for key in before.keys() | after.keys()
        if before.get(key) != after.get(key)
    }


def record(actor, action, instance, changes):
    """Write one audit row. Call it inside the mutation's transaction."""
    return AuditLog.objects.create(
        actor=actor if actor is not None and actor.is_authenticated else None,
        action=action,
        content_type=ContentType.objects.get_for_model(instance),
        object_id=str(instance.pk),
        changes=changes,
    )


class AuditLogMixin:
    """
    Audits create, update and destroy on a ModelViewSet.

    Custom `@action`s bypass `perform_*`, so wrap their writes in
    `with self.audited(action, instance):`.
    """

    def snapshot(self, instance):
        return self.get_serializer_class()(instance, context=self.get_serializer_context()).data

    def audit(self, action, instance, changes):
        return record(self.request.user, action, instance, changes)

    @contextmanager
    def audited(self, action, instance):
        """
        Atomically run the block and audit its diff. Yields a dict whose
        entries are stored alongside the diff.
        """
        extra = {}
        with transaction.atomic():
            before = self.snapshot(instance)
            yield extra
            # Re-read: the block may have written through querysets or F()
            # expressions that `instance` and its prefetch cache never see.
            after = self.snapshot(self.get_queryset().get(pk=instance.pk))
            self.audit(action, instance, {"diff": diff(before, after), **extra})

    def perform_create(self, serializer):
        with transaction.atomic():
            super().perform_create(serializer)
            self.audit(AuditLog.Action.CREATE, serializer.instance, {"after": serializer.data})

    def perform_update(self, serializer):
        with transaction.atomic():
            before = self.snapshot(serializer.instance)
            super().perform_update(serializer)
            changed = diff(before, serializer.data)
            if changed:
                self.audit(AuditLog.Action.UPDATE, serializer.instance, {"diff": changed})

    def perform_destroy(self, instance):
        with transaction.atomic():
            # Snapshot and pk first: both are gone once the row is deleted.
            before = self.snapshot(instance)
            self.audit(AuditLog.Action.DELETE, instance, {"before": before})
            super().perform_destroy(instance)

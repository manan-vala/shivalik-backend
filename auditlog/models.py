from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class AuditLog(models.Model):
    """
    One row per business mutation, written in the same transaction as the
    mutation itself — if either fails, neither is kept.

    Rows are append-only: nothing in the app updates or deletes them, and the
    admin is read-only.
    """

    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        BLOCK = "BLOCK", "Block"
        UNBLOCK = "UNBLOCK", "Unblock"
        DISPATCH = "DISPATCH", "Dispatch"
        RECEIVE = "RECEIVE", "Receive"

    # SET_NULL, so an employee leaving does not erase the record of what they did.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who performed the action.",
    )
    action = models.CharField(max_length=20, choices=Action.choices)

    content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT)
    object_id = models.CharField(max_length=255)
    content_object = GenericForeignKey("content_type", "object_id")

    changes = models.JSONField(
        default=dict,
        help_text=(
            '{"after": ...} on create, {"diff": {field: {"old", "new"}}} on '
            'update, {"before": ...} on delete.'
        ),
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.actor} -> {self.action} on {self.content_type} ({self.object_id})"

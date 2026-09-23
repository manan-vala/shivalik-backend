from django.db import models
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = 'CREATE', 'Create'
        UPDATE = 'UPDATE', 'Update'
        DELETE = 'DELETE', 'Delete'

    # Who did it
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The user who performed the action."
    )

    # What they did
    action = models.CharField(max_length=10, choices=Action.choices)

    # What they changed (Links to ANY model in the project)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=255) 
    content_object = GenericForeignKey('content_type', 'object_id')

    # The actual data payload (Before/After)
    changes = models.JSONField(
        default=dict, 
        help_text="Stores the dictionary of changed fields (Before & After states)."
    )

    # When it happened
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['content_type', 'object_id']), 
        ]

    def __str__(self):
        return f"{self.actor} -> {self.action} on {self.content_type} ({self.object_id})"

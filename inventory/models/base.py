"""Shared model plumbing for the inventory app."""

from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base that stamps every row with created/updated timestamps."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

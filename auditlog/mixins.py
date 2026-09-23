from django.contrib.contenttypes.models import ContentType
from .models import AuditLog

class AuditLogMixin:
    """
    Mixin for DRF ViewSets to automatically log CREATE, UPDATE, and DELETE actions.
    Attach this to any ModelViewSet to track mutations without writing manual logs.
    """
    def _get_actor(self):
        request = self.request
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            return request.user
        return None

    def perform_create(self, serializer):
        super().perform_create(serializer)
        instance = serializer.instance
        content_type = ContentType.objects.get_for_model(instance)
        
        # Record what was created
        changes = {
            "after": serializer.data
        }

        AuditLog.objects.create(
            actor=self._get_actor(),
            action=AuditLog.Action.CREATE,
            content_type=content_type,
            object_id=str(instance.pk),
            changes=changes
        )

    def perform_update(self, serializer):
        # 1. Get the 'Before' state directly from the database instance
        instance = self.get_object()
        serializer_class = self.get_serializer_class()
        before_data = serializer_class(instance, context=self.get_serializer_context()).data
        
        # 2. Perform the actual update
        super().perform_update(serializer)
        
        # 3. Get the 'After' state
        after_data = serializer.data

        # 4. Calculate exactly what changed to save database space
        changed_data = {}
        for key, value in after_data.items():
            if before_data.get(key) != value:
                changed_data[key] = {"old": before_data.get(key), "new": value}
        
        # 5. Only save an audit log if fields actually changed
        if changed_data:
            content_type = ContentType.objects.get_for_model(instance)
            AuditLog.objects.create(
                actor=self._get_actor(),
                action=AuditLog.Action.UPDATE,
                content_type=content_type,
                object_id=str(instance.pk),
                changes={"diff": changed_data}
            )

    def perform_destroy(self, instance):
        content_type = ContentType.objects.get_for_model(instance)
        object_id = str(instance.pk)
        
        # Record what was deleted just in case we need to restore it
        serializer_class = self.get_serializer_class()
        before_data = serializer_class(instance, context=self.get_serializer_context()).data

        super().perform_destroy(instance)
        
        AuditLog.objects.create(
            actor=self._get_actor(),
            action=AuditLog.Action.DELETE,
            content_type=content_type,
            object_id=object_id,
            changes={"deleted_data": before_data}
        )

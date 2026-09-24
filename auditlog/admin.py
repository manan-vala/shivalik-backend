from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "actor", "action", "content_type", "object_id")
    list_filter = ("action", "content_type", "timestamp")
    search_fields = ("actor__email", "object_id")
    list_select_related = ("actor", "content_type")

    # An audit trail an admin can edit is not an audit trail.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

from django.contrib import admin
from .models import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('actor', 'action', 'content_type', 'object_id', 'timestamp')
    list_filter = ('action', 'content_type', 'timestamp')
    search_fields = ('actor__username', 'object_id')
    readonly_fields = ('actor', 'action', 'content_type', 'object_id', 'changes', 'timestamp')

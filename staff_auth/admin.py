from django.contrib import admin
from .models import Employee, WhitelistedIP

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('email', 'name', 'role', 'department', 'status', 'is_staff', 'is_active')
    list_filter = ('status', 'is_staff', 'is_active', 'role', 'department')
    search_fields = ('email', 'name', 'phone')

@admin.register(WhitelistedIP)
class WhitelistedIPAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'description', 'created_at')
    search_fields = ('ip_address', 'description')

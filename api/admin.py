from django.contrib import admin

from .models import Rack, Section, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
	list_display = ("name", "code", "location", "is_active", "created_at")
	search_fields = ("name", "code", "location")
	list_filter = ("is_active",)


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
	list_display = ("name", "code", "warehouse", "capacity", "current_stock", "is_active")
	search_fields = ("name", "code", "warehouse__name", "warehouse__code")
	list_filter = ("is_active", "warehouse")


@admin.register(Rack)
class RackAdmin(admin.ModelAdmin):
	list_display = ("name", "code", "section", "capacity", "current_stock", "is_active")
	search_fields = ("name", "code", "section__name", "section__warehouse__name")
	list_filter = ("is_active", "section")

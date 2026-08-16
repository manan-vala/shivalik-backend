from django.core.exceptions import ValidationError
from django.db import models


class Warehouse(models.Model):
	name = models.CharField(max_length=120, unique=True)
	code = models.CharField(max_length=40, unique=True)
	location = models.CharField(max_length=255, blank=True)
	description = models.TextField(blank=True)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["name"]

	def __str__(self):
		return self.name


class Section(models.Model):
	warehouse = models.ForeignKey(Warehouse, on_delete=models.CASCADE, related_name="sections")
	name = models.CharField(max_length=120)
	code = models.CharField(max_length=40)
	capacity = models.PositiveIntegerField(default=0)
	current_stock = models.PositiveIntegerField(default=0)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["warehouse__name", "name"]
		constraints = [
			models.UniqueConstraint(fields=["warehouse", "code"], name="unique_section_code_per_warehouse"),
			models.UniqueConstraint(fields=["warehouse", "name"], name="unique_section_name_per_warehouse"),
		]

	def clean(self):
		if self.current_stock > self.capacity:
			raise ValidationError({"current_stock": "Current stock cannot exceed section capacity."})

	def save(self, *args, **kwargs):
		self.full_clean()
		return super().save(*args, **kwargs)

	def __str__(self):
		return f"{self.warehouse.code} / {self.name}"


class Rack(models.Model):
	section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="racks")
	name = models.CharField(max_length=120)
	code = models.CharField(max_length=40)
	capacity = models.PositiveIntegerField(default=0)
	current_stock = models.PositiveIntegerField(default=0)
	is_active = models.BooleanField(default=True)
	created_at = models.DateTimeField(auto_now_add=True)
	updated_at = models.DateTimeField(auto_now=True)

	class Meta:
		ordering = ["section__warehouse__name", "section__name", "name"]
		constraints = [
			models.UniqueConstraint(fields=["section", "code"], name="unique_rack_code_per_section"),
			models.UniqueConstraint(fields=["section", "name"], name="unique_rack_name_per_section"),
		]

	def clean(self):
		if self.current_stock > self.capacity:
			raise ValidationError({"current_stock": "Current stock cannot exceed rack capacity."})

	def save(self, *args, **kwargs):
		self.full_clean()
		return super().save(*args, **kwargs)

	def __str__(self):
		return f"{self.section.warehouse.code} / {self.section.code} / {self.name}"

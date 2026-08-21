from django.db import migrations, models
import django.db.models.deletion


def move_section_state_to_racks(apps, schema_editor):
    Section = apps.get_model("inventory", "Section")
    Rack = apps.get_model("inventory", "Rack")
    BookInventory = apps.get_model("inventory", "BookInventory")

    for section in Section.objects.all():
        racks = list(Rack.objects.filter(section_id=section.pk))
        if not racks:
            continue

        base_capacity, remainder = divmod(section.max_capacity, len(racks))
        for index, rack in enumerate(racks):
            observed_stock = sum(
                BookInventory.objects.filter(rack_id=rack.pk).values_list(
                    "curr_stock", flat=True
                )
            )
            rack.max_capacity = max(base_capacity + (index < remainder), observed_stock)
            rack.current_stock = observed_stock
            rack.last_change_date = section.last_change_date
            rack.updated_by_id = section.updated_by_id
        Rack.objects.bulk_update(
            racks,
            ["max_capacity", "current_stock", "last_change_date", "updated_by"],
        )


def reverse_move_section_state(apps, schema_editor):
    Section = apps.get_model("inventory", "Section")
    Rack = apps.get_model("inventory", "Rack")

    for section in Section.objects.all():
        racks = Rack.objects.filter(section_id=section.pk)
        section.max_capacity = sum(r.max_capacity for r in racks)
        section.current_stock = sum(r.current_stock for r in racks)
        latest = racks.order_by("-last_change_date").first()
        if latest:
            section.last_change_date = latest.last_change_date
            section.updated_by_id = latest.updated_by_id
        section.save(update_fields=["max_capacity", "current_stock", "last_change_date", "updated_by"])


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0002_book_author_book_category_book_cost_book_description_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="rack",
            name="max_capacity",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="rack",
            name="current_stock",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="rack",
            name="last_change_date",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="rack",
            name="updated_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="racks_updated",
                to="staff_auth.employee",
            ),
        ),
        migrations.RunPython(move_section_state_to_racks, reverse_move_section_state),
        migrations.RemoveField(model_name="section", name="max_capacity"),
        migrations.RemoveField(model_name="section", name="current_stock"),
        migrations.RemoveField(model_name="section", name="last_change_date"),
        migrations.RemoveField(model_name="section", name="updated_by"),
        migrations.AddConstraint(
            model_name="rack",
            constraint=models.CheckConstraint(
                condition=models.Q(max_capacity=0)
                | models.Q(current_stock__lte=models.F("max_capacity")),
                name="rack_stock_within_capacity",
            ),
        ),
    ]

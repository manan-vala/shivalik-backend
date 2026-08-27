"""
Capacity moves from Section down to Rack.

0002 added the four fields to `Rack` and left `Section`'s originals in place.
This migration carries the data down and then drops them, so the columns are
never removed while they are still the only copy.

Two different rules, because the two values mean different things:

* **max_capacity** is divided evenly across the section's racks, with the
  remainder going to the first, so the section's total is preserved. There is
  no better guess: the source data records one number for the whole section.
* **current_stock** is *not* divided — it is recomputed from the ledger
  (`BookInventory.curr_stock` summed per rack), which is where the real
  per-rack quantities have been all along. `Section.current_stock` was never
  written by any code and is 0 everywhere, so copying it would
  propagate a known-wrong number into the field the whole warehouse module is
  about to depend on.
"""

from django.db import migrations
from django.db.models import Sum


def carry_capacity_down_to_racks(apps, schema_editor):
    Section = apps.get_model("inventory", "Section")
    Rack = apps.get_model("inventory", "Rack")
    BookInventory = apps.get_model("inventory", "BookInventory")

    stock_by_rack = {
        row["rack"]: row["total"]
        for row in (
            BookInventory.objects
            .values("rack")
            .annotate(total=Sum("curr_stock"))
        )
    }

    updated = []
    for section in Section.objects.prefetch_related("racks"):
        racks = list(section.racks.all())
        if not racks:
            continue

        share, remainder = divmod(section.max_capacity or 0, len(racks))
        for index, rack in enumerate(racks):
            stock = stock_by_rack.get(rack.pk, 0)
            # A rack cannot have less capacity than the stock physically on
            # it. Where the even split says otherwise the observed stock wins,
            # because the `rack_stock_within_capacity` constraint added in
            # 0002 would otherwise reject the row — and a capacity below the
            # contents was never a fact, just an artefact of the split.
            rack.max_capacity = max(share + (remainder if index == 0 else 0), stock)
            rack.current_stock = stock
            rack.last_change_date = section.last_change_date
            rack.updated_by_id = section.updated_by_id
            updated.append(rack)

    if updated:
        Rack.objects.bulk_update(
            updated,
            ["max_capacity", "current_stock", "last_change_date", "updated_by"],
        )


def roll_capacity_back_up_to_sections(apps, schema_editor):
    """
    Reverse: sum the racks back into their section.

    Not a perfect inverse — an uneven split cannot be undone field by field —
    but the section totals come back correct, which is what the old column
    meant.
    """
    Section = apps.get_model("inventory", "Section")
    Rack = apps.get_model("inventory", "Rack")

    totals = {
        row["section"]: row
        for row in (
            Rack.objects
            .values("section")
            .annotate(capacity=Sum("max_capacity"), stock=Sum("current_stock"))
        )
    }

    restored = []
    for section in Section.objects.all():
        row = totals.get(section.pk)
        if row is None:
            continue
        section.max_capacity = row["capacity"] or 0
        section.current_stock = row["stock"] or 0
        restored.append(section)

    if restored:
        Section.objects.bulk_update(restored, ["max_capacity", "current_stock"])


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_sprint0_full_schema"),
    ]

    operations = [
        migrations.RunPython(
            carry_capacity_down_to_racks,
            roll_capacity_back_up_to_sections,
        ),
        migrations.RemoveField(model_name="section", name="current_stock"),
        migrations.RemoveField(model_name="section", name="last_change_date"),
        migrations.RemoveField(model_name="section", name="max_capacity"),
        migrations.RemoveField(model_name="section", name="updated_by"),
    ]

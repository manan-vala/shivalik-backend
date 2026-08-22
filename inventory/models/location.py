"""
Physical storage hierarchy: Warehouse -> Section -> Rack.

**Owner: Team A (Warehouse).** Nobody else edits this file. The one exception
was the day-1 `Rack.adjust_stock` stub below, written by Team B so their
movement engine had a real name to call; ownership reverted on merge.

Q3 answered: capacity lives on **Rack**. A Section's capacity and stock are
totals of its racks, annotated on read (`Section.objects.with_rack_totals()`)
rather than stored — a stored copy is a second source of truth that drifts.

`code` / `location` / `description` / `is_active` came from PR #2's parallel
`api`-app hierarchy, folded in here so there is one Warehouse in the project
rather than two. `code` is optional-but-unique: existing rows predate it and
have none, so a plain ``unique=True`` would collide on the empty string across
every one of them. The partial constraints below exempt ``""`` instead.
"""

from django.conf import settings
from django.db import models
from django.db.models import F, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .base import TimeStampedModel


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(
        max_length=40,
        blank=True,
        default="",
        db_index=True,
        help_text='Short operator-facing identifier, e.g. "WH-001". Optional; '
                  "unique among warehouses that set one.",
    )
    location = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Deactivate rather than delete: racks and ledger rows hang "
                  "off this row and must not be orphaned.",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=~models.Q(code=""),
                name="uniq_warehouse_code_when_set",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class SectionQuerySet(models.QuerySet):
    def with_rack_totals(self):
        """
        Annotate ``max_capacity`` and ``current_stock`` as sums over racks.

        Correlated subqueries rather than ``.annotate(Sum("racks__..."))``:
        a join-based aggregate multiplies its rows against any other join the
        caller adds later, and that bug is invisible until the numbers are
        quietly wrong.
        """
        racks = (
            Rack.objects
            .filter(section=OuterRef("pk"))
            .order_by()
            .values("section")
        )

        def total(field):
            return Coalesce(
                Subquery(
                    racks.annotate(total=Sum(field)).values("total")[:1],
                    output_field=IntegerField(),
                ),
                0,
            )

        return self.annotate(
            max_capacity=total("max_capacity"),
            current_stock=total("current_stock"),
        )


class Section(TimeStampedModel):
    warehouse = models.ForeignKey(
        Warehouse,
        related_name="sections",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=40,
        blank=True,
        default="",
        db_index=True,
        help_text='Short identifier, e.g. "SEC-01". Optional; unique within '
                  "its warehouse among sections that set one.",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    objects = SectionQuerySet.as_manager()

    class Meta:
        ordering = ["warehouse__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "name"],
                name="uniq_section_name_per_warehouse",
            ),
            models.UniqueConstraint(
                fields=["warehouse", "code"],
                condition=~models.Q(code=""),
                name="uniq_section_code_per_warehouse_when_set",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.warehouse.name} / {self.name}"


class Rack(TimeStampedModel):
    section = models.ForeignKey(
        Section,
        related_name="racks",
        on_delete=models.CASCADE,
    )
    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=40,
        blank=True,
        default="",
        db_index=True,
        help_text='Short identifier, e.g. "R-001". Optional; unique within '
                  "its section among racks that set one.",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    max_capacity = models.PositiveIntegerField(
        default=0,
        help_text="How many books this rack can hold. 0 means unmeasured.",
    )
    current_stock = models.PositiveIntegerField(
        default=0,
        help_text="Books on this rack right now. Written only by adjust_stock().",
    )
    last_change_date = models.DateTimeField(null=True, blank=True)
    last_used = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="racks_updated",
    )

    class Meta:
        ordering = ["section__warehouse__name", "section__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["section", "name"],
                name="uniq_rack_name_per_section",
            ),
            models.UniqueConstraint(
                fields=["section", "code"],
                condition=~models.Q(code=""),
                name="uniq_rack_code_per_section_when_set",
            ),
            models.CheckConstraint(
                check=models.Q(current_stock__lte=models.F("max_capacity"))
                | models.Q(max_capacity=0),
                name="rack_stock_within_capacity",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.section} / {self.name}"

    # -- cross-team contract ------------------------------------------------

    def adjust_stock(self, delta: int, actor) -> None:
        """
        Change this rack's stock by ``delta``.

        ``delta`` is signed — positive for inbound, negative for outbound.
        Refuses to drop below zero or above ``max_capacity`` by raising DRF's
        ``ValidationError`` — Django's own ``ValidationError`` would surface
        as a 500 through DRF instead of a clean 400. ``max_capacity == 0``
        means "unmeasured" and skips the ceiling check; the
        ``rack_stock_within_capacity`` constraint above encodes the same
        exemption, so the two must stay in agreement.

        Re-selects and locks *this* rack with ``select_for_update()`` before
        checking those bounds. The caller (``apply_stock_movement``) has
        already locked the ``BookInventory`` row, but two movements against
        the same rack can come from two different books, so that lock does
        not serialise them — this is the same check-then-update race as
        ``H-1``, one level down, for the same reason: without it, two
        concurrent movements could each read a ``current_stock`` that is
        individually within bounds, then both write, landing the real total
        outside them. Locking here is safe — never opens a transaction of its
        own — because the caller is always already inside one.

        Stamps ``last_change_date`` and ``last_used`` to now, and
        ``updated_by`` to ``actor`` (which may be ``None``). Updates
        ``current_stock`` with an ``F()`` expression, never a
        read-modify-write in Python. Persists the change itself and returns
        ``None`` — the caller re-reads the rack if it needs the new value.
        """
        rack = Rack.objects.select_for_update().get(pk=self.pk)
        new_stock = rack.current_stock + delta

        if new_stock < 0:
            raise ValidationError({
                "rack": "This movement would drop the rack below zero stock.",
            })
        if rack.max_capacity and new_stock > rack.max_capacity:
            raise ValidationError({
                "rack": "This movement would exceed the rack's capacity.",
            })

        now = timezone.now()
        Rack.objects.filter(pk=self.pk).update(
            current_stock=F("current_stock") + delta,
            last_change_date=now,
            last_used=now,
            updated_by=actor,
        )

"""
Physical storage hierarchy: Warehouse -> Section -> Rack.

**Owner: Team A (Warehouse).** Nobody else edits this file. The one exception
was the day-1 `Rack.adjust_stock` stub below, written by Team B so their
movement engine had a real name to call; ownership reverted on merge.

Q3 answered: capacity lives on **Rack**. A Section's capacity and stock are
totals of its racks, annotated on read (`Section.objects.with_rack_totals()`)
rather than stored — a stored copy is a second source of truth that drifts.
"""

from django.conf import settings
from django.db import models
from django.db.models import IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce

from .base import TimeStampedModel


class Warehouse(TimeStampedModel):
    name = models.CharField(max_length=150, unique=True)

    class Meta:
        ordering = ["name"]

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

    objects = SectionQuerySet.as_manager()

    class Meta:
        ordering = ["warehouse__name", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "name"],
                name="uniq_section_name_per_warehouse",
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
            models.CheckConstraint(
                condition=models.Q(current_stock__lte=models.F("max_capacity"))
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

        STUB — written by Team B so the movement engine could be written
        against a real name on day 1. **Team A replaces this body** (their
        Task 2); the signature is already called from `apply_stock_movement`,
        so it must not change without telling Team B first.

        The contract Team A must satisfy:

        * ``delta`` is signed — positive for inbound, negative for outbound.
        * Refuse to drop below zero, or above ``max_capacity``, by raising
          ``rest_framework.exceptions.ValidationError``. Django's
          ``django.core.exceptions.ValidationError`` surfaces as a 500 through
          DRF, so it is the wrong one here.
        * Update ``current_stock`` with an ``F()`` expression — never a
          read-modify-write in Python.
        * Stamp ``last_change_date`` and ``last_used`` to now, and
          ``updated_by`` to ``actor`` (which may be ``None``).
        * Persist the change itself. Callers do not save the rack afterwards.
        * Return ``None``. The caller re-reads if it needs the new value.

        It is always called inside the engine's transaction, with the
        ``BookInventory`` row already locked, so it must not open its own.
        `max_capacity == 0` means "unmeasured" and skips the ceiling check —
        the `rack_stock_within_capacity` constraint above encodes the same
        exemption, so the two must stay in agreement.
        """
        raise NotImplementedError("Team A to implement — see docstring contract.")

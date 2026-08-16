"""Viewsets for the storage hierarchy. **Owner: Team A.**"""

from django.db.models import Count
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from staff_auth.permissions import IsApprovedStaff

from ..models import Rack, Section, Warehouse
from ..serializers import RackSerializer, SectionSerializer, WarehouseSerializer


class WarehouseViewSet(viewsets.ModelViewSet):
    # `.order_by()` restated explicitly: `annotate(Count(...))` puts the query
    # into GROUP BY, and Django drops `Meta.ordering` from aggregate queries.
    # Losing it makes pagination non-deterministic — page 2 can repeat or skip
    # rows from page 1 — which surfaces only as DRF's UnorderedObjectList
    # warning, not as a failure.
    queryset = (
        Warehouse.objects
        .annotate(sections_count=Count("sections"))
        .order_by("name")
    )
    serializer_class = WarehouseSerializer
    # TODO(Team D, Task 2): tighten to the agreed role once the matrix exists.
    permission_classes = [IsAuthenticated, IsApprovedStaff]


class SectionViewSet(viewsets.ModelViewSet):
    # `with_rack_totals()` supplies the annotated max_capacity / current_stock
    # the serializer reads. Without it those two fields are absent.
    #
    # `racks_count` is a plain Count and safe here only because
    # `with_rack_totals()` uses correlated subqueries rather than joins — a
    # join-based Sum alongside this Count would multiply rows against each
    # other and quietly inflate both numbers.
    queryset = (
        Section.objects
        .select_related("warehouse")
        .with_rack_totals()
        .annotate(racks_count=Count("racks"))
        .order_by("warehouse__name", "name")  # see WarehouseViewSet
    )
    serializer_class = SectionSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]


class RackViewSet(viewsets.ModelViewSet):
    queryset = Rack.objects.select_related("section__warehouse", "updated_by").all()
    serializer_class = RackSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]

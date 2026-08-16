"""Viewsets for the storage hierarchy. **Owner: Team A.**"""

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from staff_auth.permissions import IsApprovedStaff

from ..models import Rack, Section, Warehouse
from ..serializers import RackSerializer, SectionSerializer, WarehouseSerializer


class WarehouseViewSet(viewsets.ModelViewSet):
    queryset = Warehouse.objects.all()
    serializer_class = WarehouseSerializer
    # TODO(Team D, Task 2): tighten to the agreed role once the matrix exists.
    permission_classes = [IsAuthenticated, IsApprovedStaff]


class SectionViewSet(viewsets.ModelViewSet):
    # `with_rack_totals()` supplies the annotated max_capacity / current_stock
    # the serializer reads. Without it those two fields are absent.
    queryset = (
        Section.objects
        .select_related("warehouse")
        .with_rack_totals()
    )
    serializer_class = SectionSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]


class RackViewSet(viewsets.ModelViewSet):
    queryset = Rack.objects.select_related("section__warehouse", "updated_by").all()
    serializer_class = RackSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]

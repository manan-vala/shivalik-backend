from django.http import JsonResponse
from django.db.models import Count
from rest_framework import viewsets

from .models import Rack, Section, Warehouse
from .serializers import RackSerializer, SectionSerializer, WarehouseSerializer


def health(request):
    return JsonResponse({"status": "success", "message": "Backend running"})


class WarehouseViewSet(viewsets.ModelViewSet):
    serializer_class = WarehouseSerializer

    def get_queryset(self):
        return Warehouse.objects.annotate(sections_count=Count("sections"))


class SectionViewSet(viewsets.ModelViewSet):
    serializer_class = SectionSerializer

    def get_queryset(self):
        return Section.objects.select_related("warehouse").annotate(racks_count=Count("racks"))


class RackViewSet(viewsets.ModelViewSet):
    serializer_class = RackSerializer

    def get_queryset(self):
        return Rack.objects.select_related("section", "section__warehouse")
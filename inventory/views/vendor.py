"""Viewsets for suppliers and purchase orders. **Owner: Team C.**"""

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from staff_auth.permissions import IsApprovedStaff

from ..models import Vendor
from ..serializers import VendorSerializer


class VendorViewSet(viewsets.ModelViewSet):
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]

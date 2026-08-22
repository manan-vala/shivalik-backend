"""Viewsets for suppliers and purchase orders. **Owner: Team C.**"""

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from staff_auth.permissions import IsApprovedStaff, IsAdmin

from ..models import Vendor
from ..serializers import VendorSerializer


class VendorViewSet(viewsets.ModelViewSet):
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdmin])
    def block(self, request, pk=None):
        """
        Block a vendor. Only admins can block vendors.
        Blocked vendors cannot be used for new stock movements.
        """
        vendor = self.get_object()
        if vendor.is_blocked:
            return Response(
                {'detail': 'Vendor is already blocked'},
                status=status.HTTP_400_BAD_REQUEST
            )

        vendor.is_blocked = True
        vendor.blocked_at = timezone.now()
        vendor.save(update_fields=['is_blocked', 'blocked_at'])

        return Response(
            {'detail': f'Vendor {vendor.company_name} has been blocked'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsAdmin])
    def unblock(self, request, pk=None):
        """
        Unblock a vendor. Only admins can unblock vendors.
        """
        vendor = self.get_object()
        if not vendor.is_blocked:
            return Response(
                {'detail': 'Vendor is not blocked'},
                status=status.HTTP_400_BAD_REQUEST
            )

        vendor.is_blocked = False
        vendor.unblocked_at = timezone.now()
        vendor.save(update_fields=['is_blocked', 'unblocked_at'])

        return Response(
            {'detail': f'Vendor {vendor.company_name} has been unblocked'},
            status=status.HTTP_200_OK
        )

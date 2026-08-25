"""Viewsets for suppliers and purchase orders. **Owner: Team C.**"""

from django.db.models import Count, Max, Q
from django.utils import timezone
from rest_framework import status, viewsets, filters
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from staff_auth.permissions import IsApprovedStaff, IsAdmin

from django.db import transaction
from rest_framework.exceptions import ValidationError
from ..models import Vendor, PurchaseOrder, PurchaseOrderLine, Rack, MovementType, apply_stock_movement
from ..serializers import VendorSerializer, PurchaseOrderSerializer


class VendorViewSet(viewsets.ModelViewSet):
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_blocked']
    search_fields = ['company_name', 'vendor_name']

    def get_queryset(self):
        return Vendor.objects.annotate(
            purchase_orders_count=Count('purchase_orders'),
            last_delivery_date=Max(
                'purchase_orders__received_at',
                filter=Q(purchase_orders__status=PurchaseOrder.Status.RECEIVED)
            )
        ).order_by('company_name')

    @action(detail=False, methods=['get'])
    def active(self, request):
        """List active vendors only."""
        queryset = self.filter_queryset(self.get_queryset().filter(is_blocked=False))
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def purchase_orders(self, request, pk=None):
        """List purchase orders for this vendor."""
        vendor = self.get_object()
        pos = vendor.purchase_orders.prefetch_related('lines__book').all()
        page = self.paginate_queryset(pos)
        if page is not None:
            serializer = PurchaseOrderSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = PurchaseOrderSerializer(pos, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsAdmin])
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

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsAdmin])
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


class PurchaseOrderViewSet(viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.prefetch_related('lines__book').all()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['vendor', 'status']

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsAdmin], url_path='dispatch')
    def dispatch_po(self, request, pk=None):
        """
        Dispatch a purchase order. Only admins can dispatch.
        """
        po = self.get_object()
        if po.status not in (PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.PLACED):
            return Response(
                {'detail': f'Cannot dispatch order in {po.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        po.status = PurchaseOrder.Status.DISPATCHED
        po.dispatched_at = timezone.now()
        po.save(update_fields=['status', 'dispatched_at'])
        
        return Response(
            {'detail': f'Purchase Order {po.pk} dispatched'},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['patch'], permission_classes=[IsAuthenticated, IsAdmin])
    def receive(self, request, pk=None):
        """
        Receive a purchase order into stock.
        Expected payload:
        {
            "lines": [
                {"line_id": 123, "quantity_received": 10, "rack_id": 5},
                ...
            ]
        }
        """
        po = self.get_object()
        if po.status != PurchaseOrder.Status.DISPATCHED:
            return Response(
                {'detail': f'Cannot receive order in {po.status} status. Must be DISPATCHED.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        lines_data = request.data.get("lines", [])
        if not lines_data:
            return Response({'detail': 'No lines provided to receive.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                for item in lines_data:
                    try:
                        line = po.lines.get(id=item.get("line_id"))
                    except PurchaseOrderLine.DoesNotExist:
                        raise ValidationError(f"Line ID {item.get('line_id')} does not exist on this PO.")
                    
                    try:
                        rack = Rack.objects.get(id=item.get("rack_id"))
                    except Rack.DoesNotExist:
                        raise ValidationError(f"Rack ID {item.get('rack_id')} does not exist.")
                    
                    qty = int(item.get("quantity_received", 0))
                    if qty <= 0:
                        raise ValidationError("Quantity received must be positive.")
                    
                    # Call Team B's engine
                    apply_stock_movement(
                        book=line.book,
                        rack=rack,
                        quantity=qty,
                        movement_type=MovementType.RECEIVE,
                        actor=request.user,
                        vendor=po.vendor,
                        purchase_order=po,
                    )
                    
                    line.quantity_received += qty
                    line.save(update_fields=['quantity_received'])
                
                po.status = PurchaseOrder.Status.RECEIVED
                po.received_at = timezone.now()
                po.save(update_fields=['status', 'received_at'])
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {'detail': f'Purchase Order {po.pk} received successfully'},
            status=status.HTTP_200_OK
        )

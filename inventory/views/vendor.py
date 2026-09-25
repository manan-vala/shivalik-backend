"""Viewsets for suppliers and purchase orders. **Owner: Team C.**"""

from django.db.models import Count, F, Max, Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from auditlog.mixins import AuditLogMixin
from auditlog.models import AuditLog
from staff_auth.permissions import IsAdmin, IsApprovedStaff

from ..models import (
    InsufficientStockError,
    MovementType,
    PurchaseOrder,
    PurchaseOrderLine,
    Rack,
    Vendor,
    apply_stock_movement,
)
from ..serializers import PurchaseOrderSerializer, VendorSerializer


class VendorViewSet(AuditLogMixin, viewsets.ModelViewSet):
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
        pos = vendor.purchase_orders.prefetch_related('lines__book').select_related('vendor', 'created_by').all()
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

        with self.audited(AuditLog.Action.BLOCK, vendor):
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

        with self.audited(AuditLog.Action.UNBLOCK, vendor):
            vendor.is_blocked = False
            vendor.unblocked_at = timezone.now()
            vendor.save(update_fields=['is_blocked', 'unblocked_at'])

        return Response(
            {'detail': f'Vendor {vendor.company_name} has been unblocked'},
            status=status.HTTP_200_OK
        )


class PurchaseOrderViewSet(AuditLogMixin, viewsets.ModelViewSet):
    queryset = PurchaseOrder.objects.prefetch_related('lines__book').select_related('vendor', 'created_by').all()
    serializer_class = PurchaseOrderSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['vendor', 'status']

    def destroy(self, request, *args, **kwargs):
        """
        Only a DRAFT may be deleted. Once an order has been placed it is a
        business document the vendor has seen; from then on the way out is
        cancellation, which keeps the record. Updates were already guarded
        by the serializer's transition table; `destroy` had no check at all.
        Checked before the audit mixin opens its transaction, so a refused
        delete writes nothing. Answers in the same `{"detail": "..."}` shape
        as dispatch and receive's status refusals.
        """
        po = self.get_object()
        if po.status != PurchaseOrder.Status.DRAFT:
            detail = (
                f"Only a draft purchase order can be deleted; this one is "
                f"{po.get_status_display().lower()}."
            )
            if po.status in (PurchaseOrder.Status.PLACED, PurchaseOrder.Status.DISPATCHED):
                detail += " Cancel it instead."
            return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)
        return super().destroy(request, *args, **kwargs)

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
        
        with self.audited(AuditLog.Action.DISPATCH, po):
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

        Every line goes through `apply_stock_movement()` — the one path that
        may write stock (README, "Conventions"). The whole receipt is one
        transaction, audit row included: if any line is rejected, nothing is
        booked in and nothing is logged.

        The order is only marked RECEIVED once every line is fully received.
        A partial receipt leaves it DISPATCHED so the rest can still arrive.
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

        # DRF turns `ValidationError` into a 400 on its own, so these guards
        # are raised, not caught-and-returned. The previous `except Exception`
        # here also swallowed IntegrityError and TypeError and reported them
        # as 400 with the raw exception text — a 500 disguised as user error.
        received = []
        try:
            with self.audited(AuditLog.Action.RECEIVE, po) as audit_extra:
                audit_extra["received"] = received
                for item in lines_data:
                    if not isinstance(item, dict):
                        raise ValidationError("Each entry in `lines` must be an object.")

                    try:
                        line = po.lines.select_for_update().get(id=item.get("line_id"))
                    except PurchaseOrderLine.DoesNotExist:
                        raise ValidationError(
                            f"Line ID {item.get('line_id')} does not exist on this PO."
                        )

                    try:
                        rack = Rack.objects.get(id=item.get("rack_id"))
                    except Rack.DoesNotExist:
                        raise ValidationError(f"Rack ID {item.get('rack_id')} does not exist.")

                    try:
                        qty = int(item.get("quantity_received", 0))
                    except (TypeError, ValueError):
                        raise ValidationError("`quantity_received` must be an integer.")

                    if qty <= 0:
                        raise ValidationError("Quantity received must be positive.")

                    outstanding = line.quantity_ordered - line.quantity_received
                    if qty > outstanding:
                        raise ValidationError(
                            f"Line {line.pk}: cannot receive {qty}, only {outstanding} "
                            f"of {line.quantity_ordered} outstanding."
                        )

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

                    # F() rather than read-modify-write: two receipts landing
                    # at once would otherwise lose one of the increments.
                    PurchaseOrderLine.objects.filter(pk=line.pk).update(
                        quantity_received=F("quantity_received") + qty,
                    )
                    received.append(
                        {"line_id": line.pk, "quantity_received": qty, "rack_id": rack.pk}
                    )

                fully_received = not po.lines.filter(
                    quantity_received__lt=F("quantity_ordered"),
                ).exists()

                if fully_received:
                    po.status = PurchaseOrder.Status.RECEIVED
                    po.received_at = timezone.now()
                    po.save(update_fields=['status', 'received_at'])
        except InsufficientStockError as exc:
            # Cannot arise on an inbound movement today, but the engine owes
            # its callers a translation rather than a 500 if that changes.
            raise ValidationError(str(exc)) from exc

        po.refresh_from_db()
        return Response(
            {
                'detail': f'Purchase Order {po.pk} received successfully',
                'status': po.status,
            },
            status=status.HTTP_200_OK
        )

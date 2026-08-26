"""
Staff identity endpoints: signup, the approval queue, staff CRUD and login.

`POST /register/` is public; everything else here is admin-only or self-only.
The approval flow is the boundary that matters — a self-signup arrives
`Pending` and inactive, and only an admin moves it out of that state.
"""

from django.utils import timezone
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Employee
from .permissions import IsApprovedStaff
from .serializers import (
    CustomTokenObtainPairSerializer,
    EmployeeRegistrationSerializer,
    EmployeeSerializer,
)


class EmployeeRegistrationView(generics.CreateAPIView):
    """
    Self-signup (Task 3, closes `H-5`).

    C-1: one of four deliberately public routes — there is nobody to
    authenticate as yet. It is safe to leave open because the serializer
    cannot set anything that confers access: the new employee lands `Pending`
    and inactive, so a successful signup grants no token and no permissions
    until an admin approves it.
    """

    queryset = Employee.objects.all()
    serializer_class = EmployeeRegistrationSerializer
    permission_classes = [AllowAny]


class PendingEmployeeListView(generics.ListAPIView):
    """The admin approval queue (Task 4). Paginated project-wide, like every list."""

    queryset = Employee.objects.filter(status=Employee.Status.PENDING)
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser]


class EmployeeListCreateView(generics.ListCreateAPIView):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser]


class EmployeeRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    """
    Staff administration. This is where an admin assigns `role` — the real
    one, after reading the `requested_role` a signup asked for.
    """

    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser]


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    # C-1: one of four deliberately public routes. You cannot require a token
    # from the endpoint that issues tokens.
    permission_classes = [AllowAny]


class EmployeeDetailView(generics.RetrieveAPIView):
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]

    def get_object(self):
        return self.request.user


class EmployeeApprovalView(generics.UpdateAPIView):
    """
    Approve or reject a pending employee (Task 4).

    Records who approved and when, so an approval is attributable after the
    fact. A rejection must carry a reason — recording a rejection with no
    explanation is exactly what `rejection_reason` exists to prevent, and the
    rejected employee has no other way to learn what went wrong.
    """

    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser]  # Task 2 replaces this with IsAdmin

    def patch(self, request, *args, **kwargs):
        employee = self.get_object()
        new_status = request.data.get('status')
        rejection_reason = (request.data.get('rejection_reason') or '').strip()

        if new_status not in dict(Employee.STATUS_CHOICES):
            return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)

        if new_status == Employee.Status.REJECTED and not rejection_reason:
            return Response(
                {"rejection_reason": "A reason is required when rejecting an application."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee.status = new_status
        if new_status == Employee.Status.APPROVED:
            employee.is_active = True
            employee.approved_by = request.user
            employee.approved_at = timezone.now()
            employee.rejection_reason = None
        elif new_status == Employee.Status.REJECTED:
            employee.is_active = False
            employee.rejection_reason = rejection_reason

        employee.save()

        return Response({"message": f"Employee status updated to {new_status}"}, status=status.HTTP_200_OK)

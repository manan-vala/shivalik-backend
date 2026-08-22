from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Employee
from .permissions import IsApprovedStaff
from .serializers import CustomTokenObtainPairSerializer, EmployeeSerializer, EmployeeRegistrationSerializer

from django.utils import timezone

class EmployeeRegistrationView(generics.CreateAPIView):
    queryset = Employee.objects.all()
    serializer_class = EmployeeRegistrationSerializer
    permission_classes = [AllowAny]


class PendingEmployeeListView(generics.ListAPIView):
    queryset = Employee.objects.filter(status=Employee.Status.PENDING)
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser]



class EmployeeListCreateView(generics.ListCreateAPIView):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser]


class EmployeeRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser]


class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    # C-1: one of three deliberately public routes. You cannot require a token
    # from the endpoint that issues tokens.
    permission_classes = [AllowAny]


class EmployeeDetailView(generics.RetrieveAPIView):
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated, IsApprovedStaff]

    def get_object(self):
        return self.request.user


class EmployeeApprovalView(generics.UpdateAPIView):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser]  # Task 2 replaces this with IsAdmin

    def patch(self, request, *args, **kwargs):
        employee = self.get_object()
        new_status = request.data.get('status')
        rejection_reason = request.data.get('rejection_reason')

        if new_status not in dict(Employee.STATUS_CHOICES):
            return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)

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

from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Employee
from .permissions import IsApprovedStaff
from .serializers import CustomTokenObtainPairSerializer, EmployeeSerializer


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

        if new_status not in dict(Employee.STATUS_CHOICES):
            return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)

        employee.status = new_status
        if new_status == Employee.Status.APPROVED:
            employee.is_active = True
        employee.save()

        return Response({"message": f"Employee status updated to {new_status}"}, status=status.HTTP_200_OK)

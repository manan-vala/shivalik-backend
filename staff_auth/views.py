from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import Employee
from .serializers import EmployeeSerializer, CustomTokenObtainPairSerializer

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

class EmployeeDetailView(generics.RetrieveAPIView):
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

class EmployeeApprovalView(generics.UpdateAPIView):
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAdminUser] # Only Admin/Staff can approve

    def patch(self, request, *args, **kwargs):
        employee = self.get_object()
        new_status = request.data.get('status')

        if new_status not in dict(Employee.STATUS_CHOICES):
            return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)
        
        employee.status = new_status
        if new_status == 'Approved':
            employee.is_active = True
        employee.save()
        
        return Response({"message": f"Employee status updated to {new_status}"}, status=status.HTTP_200_OK)

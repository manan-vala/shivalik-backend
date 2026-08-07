from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    EmployeeRegistrationView,
    CustomTokenObtainPairView,
    EmployeeDetailView,
    EmployeeApprovalView
)

urlpatterns = [
    path('register/', EmployeeRegistrationView.as_view(), name='employee-register'),
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', EmployeeDetailView.as_view(), name='employee-detail'),
    path('approve/<int:pk>/', EmployeeApprovalView.as_view(), name='employee-approve'),
]

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    EmployeeListCreateView,
    EmployeeRetrieveUpdateDestroyView,
    CustomTokenObtainPairView,
    EmployeeDetailView,
    EmployeeApprovalView
)

urlpatterns = [
    path('staff/', EmployeeListCreateView.as_view(), name='employee-list-create'),
    path('staff/<int:pk>/', EmployeeRetrieveUpdateDestroyView.as_view(), name='employee-detail-update-destroy'),
    path('login/', CustomTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('me/', EmployeeDetailView.as_view(), name='employee-detail'),
    path('approve/<int:pk>/', EmployeeApprovalView.as_view(), name='employee-approve'),
]

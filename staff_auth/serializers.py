from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework.exceptions import AuthenticationFailed
from .models import Employee, WhitelistedIP

class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ['id', 'email', 'name', 'role', 'phone', 'address', 'salary', 'department', 'contract', 'status', 'password']
        extra_kwargs = {
            'password': {'write_only': True, 'required': False}, # Password is not strictly required on creation
            'status': {'read_only': True},
            'contract': {'read_only': True}, # Usually handled separately or multipart
        }

    def create(self, validated_data):
        password = validated_data.pop('password', 'password123')
        # Default status is 'Pending' via model definition
        user = Employee.objects.create_user(password=password, **validated_data)
        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

    def validate(self, attrs):
        request = self.context.get('request')
        ip = self.get_client_ip(request)

        # 1. IP Whitelist Check
        if not WhitelistedIP.objects.filter(ip_address=ip).exists():
            raise AuthenticationFailed(f'IP Address {ip} is not whitelisted. Access Denied.')

        data = super().validate(attrs)

        # 2. Check if Employee is Approved
        if self.user.status == 'Pending':
            raise AuthenticationFailed('Login attempt recorded. Please wait for admin approval.')
        elif self.user.status != 'Approved':
            raise AuthenticationFailed('Your account is not approved.')

        # Custom claims (optional)
        data['email'] = self.user.email
        data['status'] = self.user.status
        data['is_staff'] = self.user.is_staff

        return data

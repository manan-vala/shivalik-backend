"""
Serializers for staff identity: signup, staff administration and login.

Two rules shape this module, and both exist because the same mistake is easy
to make twice:

* **A request never sets what it is allowed to do.** `status`, `is_staff`,
  `is_superuser` and `role` are all decided by an admin, never by the person
  signing up. `EmployeeRegistrationSerializer` therefore records the role the
  applicant *asked for* in `requested_role`, which no permission class reads.
* **Passwords are validated, not merely present.** This path once carried a
  hardcoded default password; requiring a password replaces it only if the
  password has to be worth something, so `AUTH_PASSWORD_VALIDATORS` is run
  here. Django
  applies those validators through forms, and nothing in this API is a form.
"""

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Employee, WhitelistedIP


def get_client_ip(request):
    """
    Best-effort client IP, preferring the first hop in `X-Forwarded-For`.

    Shared by login (allow-list check) and signup (`registered_ip` audit), so
    the two cannot drift into disagreeing about who the caller is.
    """
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def validate_password_strength(value):
    """
    Run Django's configured validators and re-raise as a DRF error.

    `validate_password` raises `django.core.exceptions.ValidationError`, which
    DRF does not recognise — uncaught it becomes a 500 instead of a 400.
    """
    try:
        validate_password(value)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(list(exc.messages)) from exc
    return value


class EmployeeSerializer(serializers.ModelSerializer):
    """
    Admin-facing staff record. Used by the staff CRUD routes and the approval
    queue, so it exposes the audit trail read-only.
    """

    class Meta:
        model = Employee
        fields = [
            'id',
            'email',
            'name',
            'role',
            'requested_role',
            'phone',
            'address',
            'salary',
            'department',
            'contract',
            'status',
            'password',
            'rejection_reason',
            'approved_by',
            'approved_at',
        ]
        extra_kwargs = {
            # No default. An admin creating staff directly must choose a
            # password; there is no longer a shared one to fall back to.
            'password': {'write_only': True, 'required': True},
            'status': {'read_only': True},
            'contract': {'read_only': True},  # handled separately, multipart
            # Decided by the approval flow, never by the request body.
            'requested_role': {'read_only': True},
            'rejection_reason': {'read_only': True},
            'approved_by': {'read_only': True},
            'approved_at': {'read_only': True},
        }

    def validate_password(self, value):
        return validate_password_strength(value)

    def create(self, validated_data):
        password = validated_data.pop('password')
        # Status defaults to 'Pending' on the model.
        return Employee.objects.create_user(password=password, **validated_data)

    def update(self, instance, validated_data):
        """
        Hash a changed password. `ModelSerializer.update()` sets every field
        with `setattr`, so without this a PATCH/PUT carrying `password` stored
        it as plain text — and, since the column is then not a valid hash, the
        employee could no longer log in either.
        """
        password = validated_data.pop('password', None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=['password'])
        return instance


class EmployeeRegistrationSerializer(serializers.ModelSerializer):
    """
    Self-signup — the only write path here reachable without a token.

    `role` is accepted from the applicant and stored as `requested_role`.
    It deliberately does **not** populate `Employee.role`: that field is what
    `RoleBasedPermission` gates on (`permissions.py`), so honouring a
    stranger's answer would let them choose their own privileges and an
    approving admin would see a role that already looks assigned. The admin
    reads the request, then sets `role` themselves via `PATCH /staff/{pk}/`.

    Everything else that confers access — `status`, `is_active`, `is_staff`,
    `is_superuser` — is absent from `fields` and forced below, so a request
    body cannot reach it.
    """

    role = serializers.ChoiceField(
        choices=Employee.Role.choices,
        required=False,
        allow_null=True,
        write_only=True,
        help_text="The role you are applying for. An admin assigns the real "
                  "one on approval; this is recorded as a request only.",
    )

    class Meta:
        model = Employee
        fields = ['email', 'name', 'password', 'phone', 'role']
        extra_kwargs = {
            'password': {'write_only': True, 'required': True},
        }

    def validate_password(self, value):
        return validate_password_strength(value)

    def create(self, validated_data):
        password = validated_data.pop('password')
        requested_role = validated_data.pop('role', None)
        request = self.context.get('request')

        return Employee.objects.create_user(
            password=password,
            requested_role=requested_role,
            registered_ip=get_client_ip(request),
            is_active=False,
            status=Employee.Status.PENDING,
            **validated_data,
        )


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def get_client_ip(self, request):
        """Kept as a method for backwards compatibility; see the helper."""
        return get_client_ip(request)

    def validate(self, attrs):
        request = self.context.get('request')
        ip = get_client_ip(request)

        # 1. IP Whitelist Check
        #
        # Gated on ENFORCE_IP_ALLOWLIST (default: on unless DEBUG). The
        # `WhitelistedIP` table starts empty and nothing seeds it, so enforcing
        # this on a fresh database refuses every login — the superuser's
        # included — and locks the whole API behind a token nobody can obtain.
        if settings.ENFORCE_IP_ALLOWLIST:
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

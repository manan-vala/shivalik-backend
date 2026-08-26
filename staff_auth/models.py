"""
Staff identity, roles and the IP allow-list.

`Employee` is the project's `AUTH_USER_MODEL`: email-keyed, approval-gated, and
the target of every `actor` / `updated_by` foreign key in the inventory app.
"""

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


class EmployeeManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('status', Employee.Status.APPROVED)
        extra_fields.setdefault('role', Employee.Role.ADMIN)

        return self.create_user(email, password, **extra_fields)


class Employee(AbstractBaseUser, PermissionsMixin):
    class Status(models.TextChoices):
        PENDING = 'Pending', 'Pending'
        APPROVED = 'Approved', 'Approved'
        REJECTED = 'Rejected', 'Rejected'

    class Role(models.TextChoices):
        """
        Q10 — roles are a fixed enum, seeded from the documented personas.

        Stored values are stable identifiers; labels are what the Figma role
        dropdown renders. Adding a role is a migration, which is the point:
        a typo'd free-text role used to be silently accepted.
        """

        ADMIN = 'ADMIN', 'Admin'
        INVENTORY_MANAGER = 'INVENTORY_MANAGER', 'Inventory Manager'
        DISPATCH_MANAGER = 'DISPATCH_MANAGER', 'Dispatch Manager'
        FINANCE_MANAGER = 'FINANCE_MANAGER', 'Finance Manager'
        ORDER_MANAGER = 'ORDER_MANAGER', 'Order Manager'
        MARKETING_MANAGER = 'MARKETING_MANAGER', 'Marketing Manager'
        MONEY_COLLECTOR = 'MONEY_COLLECTOR', 'Money Collector'
        BINDING_MANAGER = 'BINDING_MANAGER', 'Binding Manager'
        PRINTING_MANAGER = 'PRINTING_MANAGER', 'Printing Manager'

    # Kept as an alias so existing `dict(Employee.STATUS_CHOICES)` lookups and
    # any frontend enum dumps keep working after the TextChoices refactor.
    STATUS_CHOICES = Status.choices
    ROLE_CHOICES = Role.choices

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150)
    role = models.CharField(
        max_length=50,
        choices=Role.choices,
        blank=True,
        null=True,
        db_index=True,
        help_text="Drives the permission matrix. Null until an admin assigns one.",
    )
    requested_role = models.CharField(
        max_length=50,
        choices=Role.choices,
        blank=True,
        null=True,
        help_text="The role a self-signup asked for. Carries no permissions — "
                  "an admin reads it, then assigns `role` deliberately. Kept "
                  "separate because `role` is what the permission classes "
                  "gate on, so writing a stranger's own answer into it would "
                  "let them pick their own privileges.",
    )
    phone = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    salary = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    department = models.CharField(max_length=50, blank=True, null=True)
    contract = models.FileField(upload_to='contracts/', blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )

    # Approval audit trail — who let this person in, when, and from where they
    # signed up. Previously unrecorded.
    registered_ip = models.GenericIPAddressField(
        blank=True,
        null=True,
        help_text="Client IP captured at signup, for auditing the approval.",
    )
    approved_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='approved_employees',
    )
    approved_at = models.DateTimeField(blank=True, null=True)

    rejection_reason = models.TextField(
        blank=True,
        null=True,
        help_text="Reason for rejecting the employee application.",
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = EmployeeManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        # Every list endpoint is paginated project-wide (M-5), and paginating
        # an unordered queryset lets rows repeat or vanish between pages —
        # DRF warns about exactly this. `id` is the tiebreaker because `name`
        # is not unique, so without it the order within a name is undefined.
        ordering = ['name', 'id']

    def __str__(self):
        return self.email

    @property
    def is_approved(self) -> bool:
        return self.status == self.Status.APPROVED


#: Module-level alias of ``Employee.Role.choices``.
#:
#: `role` and `requested_role` share this one choice set, so drf-spectacular
#: would emit two identically-shaped enums and warn about it. Collapsing them
#: needs an ``ENUM_NAME_OVERRIDES`` entry, and that setting resolves its value
#: with ``import_string``, which cannot traverse into a nested class —
#: ``...Employee.Role.choices`` fails to load. Hence this alias.
#: ``Employee.Role`` remains the canonical definition.
ROLE_CHOICES = Employee.Role.choices


class WhitelistedIP(models.Model):
    ip_address = models.GenericIPAddressField(unique=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Whitelisted IP"

    def __str__(self):
        return f"{self.ip_address} - {self.description}"

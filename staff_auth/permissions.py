"""
Role-based permission classes.

**These are published as stubs.** Every class below currently allows any
authenticated caller through, because the permission *matrix* (which role may
do what) is a whole-team decision that has not been made yet.

Import and apply them anyway, from day one::

    from staff_auth.permissions import IsApprovedStaff, IsInventoryManager

    class BookViewSet(ModelViewSet):
        permission_classes = [IsAuthenticated, IsInventoryManager]

Nothing in a consuming view changes when the stubs become real. Two things
turn them on, and both have to land together:

1. Fill in ``allowed_roles`` on each class from the agreed matrix.
2. Set ``ENFORCE_ROLE_PERMISSIONS=true`` in the environment.

The check logic itself is already written and tested — flipping the flag with
an empty ``allowed_roles`` denies everyone, which is the safe direction to fail
but *will* turn passing views into 403s. Announce it in the group chat before
you flip it.
"""

from django.conf import settings
from rest_framework.permissions import BasePermission

from .models import Employee


class RoleBasedPermission(BasePermission):
    """
    Base class: approved staff, whose role is in ``allowed_roles``.

    Superusers bypass the role check but not the approval check — an
    unapproved superuser is a half-finished account, not an administrator.
    """

    #: Roles allowed through. Empty means "nobody" once enforcement is on.
    allowed_roles: tuple[str, ...] = ()

    #: Message surfaced as the 403 body.
    message = "Your role does not permit this action."

    @staticmethod
    def _is_approved(request) -> bool:
        """Authenticated, and an admin has let them in."""
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        return user.status == Employee.Status.APPROVED

    def has_permission(self, request, view) -> bool:
        if not getattr(settings, "ENFORCE_ROLE_PERMISSIONS", False):
            # STUB behaviour. DEFAULT_PERMISSION_CLASSES still
            # requires authentication, so this is not an open door.
            return True

        if not self._is_approved(request):
            return False
        if request.user.is_superuser:
            return True
        return request.user.role in self.allowed_roles


class IsApprovedStaff(RoleBasedPermission):
    """
    Any approved employee, whatever their role. The weakest real gate.

    Checks approval only — an approved employee whose role an admin has not
    assigned yet must still be able to read. Listing every role in
    `allowed_roles` would look equivalent and would lock those people out.
    """

    message = "Your account is not approved yet."

    def has_permission(self, request, view) -> bool:
        if not getattr(settings, "ENFORCE_ROLE_PERMISSIONS", False):
            return True
        return self._is_approved(request)


class IsAdmin(RoleBasedPermission):
    allowed_roles = (Employee.Role.ADMIN,)


class IsInventoryManager(RoleBasedPermission):
    # TODO: confirm against the agreed permission matrix.
    allowed_roles = (Employee.Role.ADMIN, Employee.Role.INVENTORY_MANAGER)


class IsDispatchManager(RoleBasedPermission):
    allowed_roles = (Employee.Role.ADMIN, Employee.Role.DISPATCH_MANAGER)


class IsFinanceManager(RoleBasedPermission):
    allowed_roles = (Employee.Role.ADMIN, Employee.Role.FINANCE_MANAGER)


class IsOrderManager(RoleBasedPermission):
    allowed_roles = (Employee.Role.ADMIN, Employee.Role.ORDER_MANAGER)


class IsMarketingManager(RoleBasedPermission):
    allowed_roles = (Employee.Role.ADMIN, Employee.Role.MARKETING_MANAGER)


class IsMoneyCollector(RoleBasedPermission):
    allowed_roles = (Employee.Role.ADMIN, Employee.Role.MONEY_COLLECTOR)


class IsBindingManager(RoleBasedPermission):
    allowed_roles = (Employee.Role.ADMIN, Employee.Role.BINDING_MANAGER)


class IsPrintingManager(RoleBasedPermission):
    allowed_roles = (Employee.Role.ADMIN, Employee.Role.PRINTING_MANAGER)


#: Every published class, so consumers can assert the contract exists.
__all__ = [
    "RoleBasedPermission",
    "IsApprovedStaff",
    "IsAdmin",
    "IsInventoryManager",
    "IsDispatchManager",
    "IsFinanceManager",
    "IsOrderManager",
    "IsMarketingManager",
    "IsMoneyCollector",
    "IsBindingManager",
    "IsPrintingManager",
]

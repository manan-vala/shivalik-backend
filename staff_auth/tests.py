"""
Team D's day-1 output: the role enum (Q10) and the permission-class stubs.

The stubs allow everyone through today. What is tested here is that the real
logic *behind* them is correct, so Task 2 is only a matter of filling in
`allowed_roles` and flipping `ENFORCE_ROLE_PERMISSIONS` — not of writing and
debugging the check itself under time pressure.
"""

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from .models import Employee, WhitelistedIP
from .permissions import (
    IsAdmin,
    IsApprovedStaff,
    IsInventoryManager,
    RoleBasedPermission,
)


class RoleEnumTests(TestCase):
    def test_roles_match_the_documented_personas(self):
        self.assertEqual(
            set(Employee.Role.values),
            {
                "ADMIN",
                "INVENTORY_MANAGER",
                "DISPATCH_MANAGER",
                "FINANCE_MANAGER",
                "ORDER_MANAGER",
                "MARKETING_MANAGER",
                "MONEY_COLLECTOR",
                "BINDING_MANAGER",
                "PRINTING_MANAGER",
            },
        )

    def test_status_values_are_unchanged_by_the_textchoices_refactor(self):
        """The stored strings must not move — there is data in this column."""
        self.assertEqual(
            [value for value, _label in Employee.STATUS_CHOICES],
            ["Pending", "Approved", "Rejected"],
        )

    def test_new_employees_start_pending(self):
        employee = Employee.objects.create_user(
            email="new@shivalik.test", password="x", name="New",
        )
        self.assertEqual(employee.status, Employee.Status.PENDING)
        self.assertFalse(employee.is_approved)

    def test_superuser_is_approved_and_admin(self):
        admin = Employee.objects.create_superuser(
            email="admin@shivalik.test", password="x", name="Admin",
        )
        self.assertEqual(admin.status, Employee.Status.APPROVED)
        self.assertEqual(admin.role, Employee.Role.ADMIN)


class PermissionStubTests(SimpleTestCase):
    """Task 0 behaviour: published, importable, and permissive for now."""

    def setUp(self):
        self.request = RequestFactory().get("/")
        self.request.user = Employee(
            email="pending@shivalik.test", status=Employee.Status.PENDING,
        )

    def test_stubs_allow_everyone_through(self):
        for permission in (IsApprovedStaff(), IsAdmin(), IsInventoryManager()):
            self.assertTrue(
                permission.has_permission(self.request, view=None),
                msg=f"{type(permission).__name__} should be a permissive stub",
            )


@override_settings(ENFORCE_ROLE_PERMISSIONS=True)
class PermissionLogicTests(TestCase):
    """
    Task 2 behaviour, tested ahead of the switch being flipped.

    Every check answers two questions: is this person approved, and is their
    role allowed here.
    """

    factory = RequestFactory()

    def _request_for(self, user):
        request = self.factory.get("/")
        request.user = user
        return request

    def _employee(self, **kwargs):
        kwargs.setdefault("email", f"{kwargs.get('role', 'user')}@shivalik.test")
        kwargs.setdefault("name", "Tester")
        kwargs.setdefault("status", Employee.Status.APPROVED)
        return Employee.objects.create_user(password="x", **kwargs)

    def test_approved_manager_is_allowed(self):
        user = self._employee(role=Employee.Role.INVENTORY_MANAGER)
        self.assertTrue(IsInventoryManager().has_permission(self._request_for(user), None))

    def test_wrong_role_is_denied(self):
        user = self._employee(role=Employee.Role.PRINTING_MANAGER)
        self.assertFalse(IsInventoryManager().has_permission(self._request_for(user), None))

    def test_pending_employee_is_denied_even_with_the_right_role(self):
        """The approval gate is the point of the whole signup flow."""
        user = self._employee(
            role=Employee.Role.INVENTORY_MANAGER,
            status=Employee.Status.PENDING,
            email="pending-mgr@shivalik.test",
        )
        self.assertFalse(IsInventoryManager().has_permission(self._request_for(user), None))

    def test_rejected_employee_is_denied(self):
        user = self._employee(
            role=Employee.Role.ADMIN,
            status=Employee.Status.REJECTED,
            email="rejected@shivalik.test",
        )
        self.assertFalse(IsAdmin().has_permission(self._request_for(user), None))

    def test_roleless_employee_is_denied_a_role_gated_action(self):
        user = self._employee(role=None, email="norole@shivalik.test")
        self.assertFalse(IsInventoryManager().has_permission(self._request_for(user), None))

    def test_roleless_employee_still_passes_the_approval_only_gate(self):
        """
        `IsApprovedStaff` asks one question. An approved employee waiting for
        an admin to assign their role must not be locked out of every read.
        """
        user = self._employee(role=None, email="norole2@shivalik.test")
        self.assertTrue(IsApprovedStaff().has_permission(self._request_for(user), None))

    def test_approval_only_gate_still_rejects_the_unapproved(self):
        user = self._employee(
            role=Employee.Role.ADMIN,
            status=Employee.Status.PENDING,
            email="unapproved@shivalik.test",
        )
        self.assertFalse(IsApprovedStaff().has_permission(self._request_for(user), None))

    def test_superuser_bypasses_the_role_check_but_not_approval(self):
        superuser = Employee.objects.create_superuser(
            email="root@shivalik.test", password="x", name="Root",
        )
        self.assertTrue(IsInventoryManager().has_permission(self._request_for(superuser), None))

        superuser.status = Employee.Status.PENDING
        self.assertFalse(IsInventoryManager().has_permission(self._request_for(superuser), None))

    def test_anonymous_is_denied(self):
        from django.contrib.auth.models import AnonymousUser

        request = self._request_for(AnonymousUser())
        self.assertFalse(IsApprovedStaff().has_permission(request, None))

    def test_empty_allowed_roles_denies_everyone(self):
        """
        Fail closed: a class Task 2 forgot to fill in must block, not admit.
        """
        class Unconfigured(RoleBasedPermission):
            pass

        user = self._employee(role=Employee.Role.ADMIN, email="admin2@shivalik.test")
        self.assertFalse(Unconfigured().has_permission(self._request_for(user), None))


class LoginIPAllowlistTests(TestCase):
    """
    The login route, which had no passing-path coverage at all.

    `WhitelistedIP` starts empty and nothing seeds it, so enforcing the
    allow-list unconditionally meant a fresh database could not issue a single
    token — every authenticated endpoint in the project was unreachable, the
    superuser's included. It survived review because the only login test
    (`api.tests`) posts `{}`, which 400s on field validation before
    `validate()` — and therefore before the allow-list — ever runs.

    `ENFORCE_IP_ALLOWLIST` now gates it, defaulting to `not DEBUG`. Django
    forces `DEBUG=False` under test, so the flag is *on* here unless a case
    says otherwise.
    """

    LOGIN_URL = "/api/v1/auth/login/"
    PASSWORD = "not-a-default-password"

    def setUp(self):
        self.employee = Employee.objects.create_user(
            email="ops@shivalik.test",
            password=self.PASSWORD,
            name="Ops",
            role=Employee.Role.INVENTORY_MANAGER,
            status=Employee.Status.APPROVED,
        )

    def _login(self, email=None, password=None):
        return self.client.post(
            self.LOGIN_URL,
            {
                "email": email or self.employee.email,
                "password": password or self.PASSWORD,
            },
            content_type="application/json",
        )

    @override_settings(ENFORCE_IP_ALLOWLIST=True)
    def test_unlisted_ip_is_refused_when_enforced(self):
        response = self._login()
        self.assertEqual(response.status_code, 401)
        self.assertIn("not whitelisted", response.json()["detail"])

    @override_settings(ENFORCE_IP_ALLOWLIST=True)
    def test_listed_ip_gets_a_token_when_enforced(self):
        WhitelistedIP.objects.create(
            ip_address="127.0.0.1", description="test client",
        )
        response = self._login()
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertIn("access", body)
        self.assertIn("refresh", body)
        self.assertEqual(body["email"], self.employee.email)

    @override_settings(ENFORCE_IP_ALLOWLIST=False)
    def test_empty_allowlist_does_not_lock_everyone_out_when_not_enforced(self):
        """The regression this flag exists for."""
        self.assertFalse(WhitelistedIP.objects.exists())
        response = self._login()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("access", response.json())

    @override_settings(ENFORCE_IP_ALLOWLIST=False)
    def test_approval_gate_still_applies_with_the_allowlist_off(self):
        """Relaxing the IP check must not relax anything else."""
        self.employee.status = Employee.Status.PENDING
        self.employee.save(update_fields=["status"])

        response = self._login()

        self.assertEqual(response.status_code, 401)
        self.assertIn("approval", response.json()["detail"].lower())

    @override_settings(ENFORCE_IP_ALLOWLIST=False)
    def test_wrong_password_is_still_refused_with_the_allowlist_off(self):
        response = self._login(password="wrong-password")
        self.assertEqual(response.status_code, 401)

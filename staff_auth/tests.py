"""
Team D's day-1 output: the role enum and the permission-class stubs.

The stubs allow everyone through today. What is tested here is that the real
logic *behind* them is correct, so turning them on is only a matter of
filling in `allowed_roles` and flipping `ENFORCE_ROLE_PERMISSIONS` — not of
writing and debugging the check itself under time pressure.
"""

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

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
    """Stub behaviour: published, importable, and permissive for now."""

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
    Enforced behaviour, tested ahead of the switch being flipped.

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
        Fail closed: a class nobody filled in must block, not admit.
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

class SelfSignupTests(TestCase):
    """
    `POST /register/`, the one public write path.

    The threat these cover is the one the task file names outright: "a
    serializer that blindly accepts request fields is how someone makes
    themselves an admin."
    """

    STRONG_PASSWORD = "quiet-harbour-8261"

    def setUp(self):
        self.client = APIClient()
        self.register_url = reverse("employee-register")

    def _signup(self, **overrides):
        data = {
            "email": "newguy@shivalik.test",
            "name": "New Guy",
            "password": self.STRONG_PASSWORD,
            "phone": "1234567890",
        }
        extra = {}
        if "REMOTE_ADDR" in overrides:
            extra["REMOTE_ADDR"] = overrides.pop("REMOTE_ADDR")
        data.update(overrides)
        return self.client.post(self.register_url, data, **extra)

    def test_happy_path_signup(self):
        response = self._signup(role=Employee.Role.INVENTORY_MANAGER)
        self.assertEqual(response.status_code, 201, response.data)

        user = Employee.objects.get(email="newguy@shivalik.test")
        self.assertEqual(user.status, Employee.Status.PENDING)
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_no_token_is_issued_by_signing_up(self):
        """201 with nothing to authenticate with — approval comes first."""
        response = self._signup()
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertNotIn("password", response.data)

    def test_requested_role_is_recorded_but_grants_nothing(self):
        """
        The applicant's answer lands in `requested_role`, not `role`.

        `role` is what `RoleBasedPermission` gates on, so writing a stranger's
        own answer into it would let them choose their own privileges.
        """
        response = self._signup(role=Employee.Role.ADMIN)
        self.assertEqual(response.status_code, 201, response.data)

        user = Employee.objects.get(email="newguy@shivalik.test")
        self.assertEqual(user.requested_role, Employee.Role.ADMIN)
        self.assertIsNone(user.role)

    @override_settings(ENFORCE_ROLE_PERMISSIONS=True)
    def test_asking_for_admin_does_not_survive_approval(self):
        """
        The regression that matters, end to end.

        Sign up asking for ADMIN, get approved, and still fail `IsAdmin` —
        because approval sets status, not role. Runs with enforcement on,
        since that is when the escalation would have paid off.
        """
        self._signup(role=Employee.Role.ADMIN)
        user = Employee.objects.get(email="newguy@shivalik.test")
        user.status = Employee.Status.APPROVED
        user.is_active = True
        user.save(update_fields=["status", "is_active"])

        request = RequestFactory().get("/")
        request.user = user
        self.assertFalse(IsAdmin().has_permission(request, None))
        # The weaker gate still admits them — they are approved staff.
        self.assertTrue(IsApprovedStaff().has_permission(request, None))

    def test_cannot_set_is_staff_or_status(self):
        response = self._signup(
            email="hacker@shivalik.test",
            status=Employee.Status.APPROVED,
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )
        self.assertEqual(response.status_code, 201, response.data)

        user = Employee.objects.get(email="hacker@shivalik.test")
        self.assertEqual(user.status, Employee.Status.PENDING)
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)

    def test_registered_ip_is_captured(self):
        """The field exists to audit the approval; signup is the only place that can fill it."""
        self._signup(REMOTE_ADDR="203.0.113.7")
        user = Employee.objects.get(email="newguy@shivalik.test")
        self.assertEqual(user.registered_ip, "203.0.113.7")

    def test_missing_password_is_rejected(self):
        """There is no longer a shared default password to fall back to."""
        response = self.client.post(self.register_url, {
            "email": "fail@shivalik.test",
            "name": "Fail",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)

    def test_weak_password_is_rejected(self):
        """
        Requiring a password only helps if the password is worth
        something. Django's validators are configured but are never reached
        from a serializer unless called explicitly.
        """
        response = self._signup(password="password")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)
        self.assertFalse(
            Employee.objects.filter(email="newguy@shivalik.test").exists()
        )


class ApprovalQueueTests(TestCase):
    """The approval queue, and what an approval records."""

    PASSWORD = "quiet-harbour-8261"

    def setUp(self):
        self.client = APIClient()
        self.admin = Employee.objects.create_superuser(
            email="admin4@shivalik.test", password=self.PASSWORD, name="Admin4",
        )
        self.client.force_authenticate(user=self.admin)

        self.pending_user = Employee.objects.create_user(
            email="pending4@shivalik.test", password=self.PASSWORD, name="Pending",
            status=Employee.Status.PENDING, is_active=False,
        )
        self.approved_user = Employee.objects.create_user(
            email="approved4@shivalik.test", password=self.PASSWORD, name="Approved",
            status=Employee.Status.APPROVED, is_active=True,
        )

    def test_pending_list_returns_only_pending_employees(self):
        response = self.client.get(reverse("employee-pending-list"))
        self.assertEqual(response.status_code, 200)
        # List responses are paginated project-wide, so the rows sit
        # under `results` — iterating `response.data` walks the envelope keys.
        emails = [item["email"] for item in response.data["results"]]
        self.assertIn(self.pending_user.email, emails)
        self.assertNotIn(self.approved_user.email, emails)

    def test_approve_employee_sets_metadata(self):
        url = reverse("employee-approve", args=[self.pending_user.pk])
        response = self.client.patch(url, {"status": Employee.Status.APPROVED})
        self.assertEqual(response.status_code, 200)

        self.pending_user.refresh_from_db()
        self.assertEqual(self.pending_user.status, Employee.Status.APPROVED)
        self.assertTrue(self.pending_user.is_active)
        self.assertEqual(self.pending_user.approved_by, self.admin)
        self.assertIsNotNone(self.pending_user.approved_at)
        self.assertIsNone(self.pending_user.rejection_reason)

    def test_approval_does_not_assign_a_role(self):
        """Approval decides admission, not privileges — a role stays an explicit act."""
        url = reverse("employee-approve", args=[self.pending_user.pk])
        self.client.patch(url, {"status": Employee.Status.APPROVED})

        self.pending_user.refresh_from_db()
        self.assertIsNone(self.pending_user.role)

    def test_reject_employee_records_reason(self):
        url = reverse("employee-approve", args=[self.pending_user.pk])
        response = self.client.patch(url, {
            "status": Employee.Status.REJECTED,
            "rejection_reason": "Incomplete application",
        })
        self.assertEqual(response.status_code, 200)

        self.pending_user.refresh_from_db()
        self.assertEqual(self.pending_user.status, Employee.Status.REJECTED)
        self.assertFalse(self.pending_user.is_active)
        self.assertEqual(self.pending_user.rejection_reason, "Incomplete application")

    def test_rejection_without_a_reason_is_refused(self):
        """
        A rejection with no explanation is what `rejection_reason` exists to
        prevent — and the rejected employee has no other way to find out why.
        """
        url = reverse("employee-approve", args=[self.pending_user.pk])
        response = self.client.patch(url, {"status": Employee.Status.REJECTED})

        self.assertEqual(response.status_code, 400)
        self.assertIn("rejection_reason", response.data)
        self.pending_user.refresh_from_db()
        self.assertEqual(self.pending_user.status, Employee.Status.PENDING)

    def test_pending_queue_is_admin_only(self):
        anonymous = APIClient()
        self.assertEqual(
            anonymous.get(reverse("employee-pending-list")).status_code, 401,
        )
        anonymous.force_authenticate(user=self.approved_user)
        self.assertEqual(
            anonymous.get(reverse("employee-pending-list")).status_code, 403,
        )

# Architecture

The rules below are the ones that will bite you if you write code here without
knowing them. Each is a constraint plus the reason it exists — the reason
matters more than the rule, because it tells you when the rule applies to
something new.

---

## PostgreSQL is required, not preferred

The core operation of this system is concurrent stock mutation, guarded by
`select_for_update()`.

**SQLite accepts that call and silently ignores it.** Not an error — a no-op.
So on SQLite the ledger's row locking protects nothing while appearing to work,
and the concurrency tests pass without proving anything. That is worse than
having no tests, because it buys false confidence in the one place this system
cannot afford to be wrong.

`DB_ENGINE=sqlite` still exists for offline schema work. `manage.py check`
warns whenever it is in use and *fails* when `DEBUG` is off, and any test
marked `@pytest.mark.postgres_only` skips itself with a visible reason rather
than passing vacuously.

If you see those tests **skip** rather than run, treat it as a failure.

## Nothing writes stock except `apply_stock_movement()`

`inventory/models/stock.py`. Not a viewset, not a management command, not
another team's module.

The function updates `BookInventory`, calls `Rack.adjust_stock()` and writes
one `StockMovement` row, all inside a single transaction holding a row lock.
Any direct `BookInventory.objects.update()` puts the live balance and the
movement log permanently out of step, and nothing will tell you it happened —
the numbers just stop reconciling weeks later.

The sufficiency check runs *inside* the lock. Checking before the transaction
is a time-of-check/time-of-use race that lets two concurrent stock-outs both
pass a balance check and oversell the rack.

The engine is called from Python with no serializer in front of it, so it
raises `ValidationError` itself for anything a caller got wrong. Database
constraints behind it raise `IntegrityError`, which DRF reports as a 500 — so
guards belong in the engine, not only in a serializer.

## Django is pinned to 5.0

`requirements.txt` pins Django 5.0.14 and Python 3.12 (the newest Python that
Django 5.0 supports). Two consequences:

- **`CheckConstraint` takes `check=`, not `condition=`.** `condition=` only
  exists from Django 5.1; on 5.0 it is a `TypeError` the moment the models
  or migrations are imported. If you run `makemigrations` under a newer
  Django by accident, it writes `condition=` into the migration — install
  from `requirements.txt` in a fresh virtualenv before generating one.
  `UniqueConstraint(condition=...)` is a different, older API and is fine.
- **Library pins are capped by Django 5.0.** DRF 3.18+, django-filter 25.2+
  and pytest-django 4.12–4.13 require a newer Django. Check a release's
  supported Django versions before bumping it.

Django 5.0 is past its end of support (final release 5.0.14, April 2025) and
receives no further security fixes.

## Money is `DecimalField`, never `FloatField`

Currency is INR throughout. `settings.DEFAULT_CURRENCY` records it.

## Deletion protects history

`on_delete=PROTECT` for anything a ledger row points at — a book, a rack, a
vendor. `SET_NULL` for people, so an employee leaving does not erase the record
of what they did.

A delete the database refuses is a **409**, not a 500: `api/exceptions.py`
translates `ProtectedError` project-wide, so a viewset needs nothing extra.
Locations are retired with `is_active = False` instead, and a retired rack —
or one in a retired section or warehouse — takes no new stock (the engine
refuses it). Purchase orders can only be deleted while DRAFT; after that,
cancel them.

## Who counts as an admin

Staff management (`staff/`, `staff/pending/`, `approve/`) uses
`CanManageStaff`: Django's `is_staff` **or** an approved employee with
`role = ADMIN`. It is always enforced, and the role can't modify an
`is_staff` account — only `is_staff` can, or the role would be a way to take
over a superuser. Don't use DRF's `IsAdminUser` for new
routes — it only knows `is_staff` — and don't use the role stubs for anything
that must stay closed while `ENFORCE_ROLE_PERMISSIONS` is off.

## The user model is `staff_auth.Employee`

Never import `django.contrib.auth.models.User`. Use `settings.AUTH_USER_MODEL`
in foreign keys.

`Employee` is email-keyed and approval-gated: a new account is `Pending` and
inactive until an admin approves it, and a `Pending` account cannot obtain a
token however correct its password.

## Self-signup requests a role, it does not choose one

`POST /register/` accepts a role and stores it as `requested_role`, which no
permission class reads. `Employee.role` — the field the permission classes
gate on — stays null until an admin assigns it deliberately.

Writing an applicant's own answer into `role` would let a stranger pick their
own privileges, and the approving admin would see a role that already looked
assigned.

## The API is closed by default

`DEFAULT_PERMISSION_CLASSES` is `IsAuthenticated`. Four routes opt out
explicitly at the view, with `permission_classes = [AllowAny]` so it is
greppable in review:

| Route | Why it is open |
|---|---|
| `api/health/` | liveness probe |
| `api/v1/auth/login/` | you cannot present a token to get a token |
| `api/v1/auth/token/refresh/` | same |
| `api/v1/auth/register/` | there is nobody to authenticate as yet |

`register/` is safe to leave open because its serializer cannot set anything
that confers access — the account lands `Pending` and inactive.

Role-based permission classes exist in `staff_auth/permissions.py` but are
currently **permissive stubs**: they admit any authenticated caller until
`ENFORCE_ROLE_PERMISSIONS` is turned on. Turning it on without filling in each
class's `allowed_roles` denies everyone, so both halves have to land together.

## The login IP allow-list is off in development

`ENFORCE_IP_ALLOWLIST` follows `DEBUG`. When it is on, login refuses any client
whose IP has no `WhitelistedIP` row — and that table starts empty, so enabling
it before populating the list locks out everyone including the superuser.
Populate it through `/admin/` first.

## Derived values are not columns

They live in serializers, or as queryset annotations when they must be filtered
or sorted in SQL. Dead stock, for instance, is computed on read and never
stored.

Two traps, both of which have already cost this repo a bug:

- A read-only `IntegerField` reading a queryset annotation **omits the key**
  when the annotation is absent, rather than failing. An object that never went
  through the annotating queryset answers with a different shape.
- `Field.get_default()` raises `SkipField` whenever `partial=True`, so a field
  with `default=None` survives GET and POST and then **silently vanishes from
  every PATCH response**.

Use a `SerializerMethodField` for both. It has no default machinery and always
emits a value.

## Validation lives in serializers

Except invariants the movement engine must hold, since it is called from Python
and never sees a serializer.

## List endpoints are paginated project-wide

Set once in settings, not per view. Two consequences:

- Responses are an envelope — read `response.data["results"]`, not
  `response.data`.
- Every model needs `Meta.ordering`. Paginating an unordered queryset lets rows
  repeat or vanish between pages, and Django only warns.

## Two logs, two jobs

**The audit trail** (`auditlog.AuditLog`) records who changed which business
object and what changed. It is permanent, lives in PostgreSQL, and each row is
written **in the same transaction as the change**, so a change without an audit
row, or an audit row without a change, cannot exist. It only records writes, so
it grows with business volume, not traffic.

Add `AuditLogMixin` to a viewset and create, update and destroy are covered.
Custom `@action`s skip `perform_*`, so the mixin never sees them. Wrap their
writes in `with self.audited(AuditLog.Action.X, obj):`. If you leave that out,
the change is simply not recorded, and nothing warns you.

**The operational log** covers requests, timings, errors and frontend
telemetry. It is high-volume and disposable, and it **never touches the
database**. It goes to stdout as one JSON object per line (plain text when
`DEBUG` is on), plus `LOG_FILE` if set, which logrotate should rotate.
Every line carries a `request_id`, which is also returned as the `X-Request-ID`
response header. `POST /api/v1/telemetry/` takes frontend events. It requires a
login and is throttled, and it writes to the log only.

---

## Module ownership

Four teams work in this repository at once, so each module name is owned by
exactly one of them and they do not touch each other's files:

```
inventory/…/location.py     Warehouse → Section → Rack      Team A
inventory/…/catalog.py      Book                            Team B
inventory/…/stock.py        BookInventory, StockMovement    Team B
inventory/…/vendor.py       Vendor, PurchaseOrder           Team C
staff_auth/                 Employee, JWT login, IP list    Team D
```

`__init__.py` re-exports everything, so `from inventory.models import Book`
keeps working no matter which module a model lives in.

**Shared files — say so in the group chat before editing:**
`inventory/urls.py`, `config/settings.py`, `requirements.txt`.

Branches are `feat/<team>/<feature>`. One person per team generates migrations.

## Testing

No PR merges without a test. This is money-adjacent concurrent logic.

`pytest -m smoke` is the gate: a handful of checks covering the invariants
every team depends on — the API is closed, stock moves only through the engine,
overselling is a 400, the ledger reconciles, the core routes answer, and the
OpenAPI contract still generates. If that is red, nothing else is worth reading.

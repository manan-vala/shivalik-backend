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

## Money is `DecimalField`, never `FloatField`

Currency is INR throughout. `settings.DEFAULT_CURRENCY` records it.

## Deletion protects history

`on_delete=PROTECT` for anything a ledger row points at — a book, a rack, a
vendor. `SET_NULL` for people, so an employee leaving does not erase the record
of what they did.

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

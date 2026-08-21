# Backend - Shivalik

Django + DRF backend for the Shivalik book-distribution warehouse: catalog,
stock ledger, storage hierarchy, vendors and purchase orders, staff auth.

Four teams work in this repository at once. Before you write anything, read
[`DECISIONS.md`](./DECISIONS.md) — it records which open questions are settled
and how — and your own file in `../teams/`.

---

## Setup

Requires **Python 3.14** and **Docker** (for PostgreSQL).

```bash
# 1. Environment
conda activate main                 # or: python -m venv venv && venv\Scripts\activate
pip install -r requirements-dev.txt

# 2. Configuration
copy .env.example .env              # cp on macOS/Linux
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
#   ...paste that into DJANGO_SECRET_KEY in .env

# 3. Database — PostgreSQL, per Q2
docker compose up -d db
python manage.py migrate
python manage.py createsuperuser

# 4. Run
python manage.py runserver
```

| URL | What |
|---|---|
| `http://127.0.0.1:8000/api/health/` | liveness probe — the only route needing no token |
| `http://127.0.0.1:8000/api/docs/` | Swagger UI |
| `http://127.0.0.1:8000/api/schema/` | raw OpenAPI schema |
| `http://127.0.0.1:8000/admin/` | Django admin |

### Why PostgreSQL is not optional

The core operation of this system is concurrent stock mutation, guarded by
`select_for_update()`. **SQLite accepts that call and silently ignores it**
(finding `H-2`), so the ledger's locking would protect nothing while appearing
to work — and concurrency tests would pass without proving anything.

`DB_ENGINE=sqlite` still exists for offline schema work. `manage.py check`
warns whenever it is in use and *fails* when `DEBUG` is off, and any test
marked `@pytest.mark.postgres_only` skips itself with a visible reason rather
than passing vacuously.

---

## Testing

```bash
pytest                      # whole suite
pytest inventory            # one app
pytest -m postgres_only     # the tests that need real row locking
```

`pytest.ini` points at `config.settings`, so tests read the same `.env` you
do — just against a throwaway database. **No PR merges without a test**; this
is money-adjacent concurrent logic and the repo had zero coverage until
Sprint 0.

CI (`.github/workflows/ci.yml`) runs, on every push and PR, against a real
PostgreSQL service: system checks at `--fail-level WARNING`,
`makemigrations --check` (so a model change without a migration fails the
build), `migrate`, then `pytest`.

---

## Project structure

```text
backend-shivalik/
├── api/                    health probe + project-wide deployment checks
│   └── checks.py           refuses to deploy on SQLite or without a secret key
├── config/
│   ├── env.py              typed accessors over os.environ
│   ├── settings.py         everything environment-driven; no committed secrets
│   └── urls.py             /api/v1/… mounts, schema + docs, dev media
├── inventory/              warehouse, catalog, stock ledger, vendors, POs
│   ├── models/ serializers/ views/ admin/ tests/
│   │   ├── location.py     Warehouse → Section → Rack          (Team A)
│   │   ├── catalog.py      Book                                (Team B)
│   │   ├── stock.py        BookInventory, StockMovement, engine (Team B)
│   │   └── vendor.py       Vendor, PurchaseOrder               (Team C)
│   └── README.md           module reference — endpoints, rules, what is stubbed
├── staff_auth/             Employee, JWT login, IP allow-list  (Team D)
│   └── permissions.py      role permission classes (published as stubs)
├── conftest.py             postgres_only marker, HTTPS off during tests
├── docker-compose.yml      local PostgreSQL
├── DECISIONS.md            answered questions, deviations, known gaps
└── .env.example            every setting, documented
```

Each of those four module names is owned by exactly one team, so four teams
can work in this app without touching each other's files. `__init__.py`
re-exports everything, so `from inventory.models import Book` keeps working no
matter which module a model lives in.

**Shared files — say so in the group chat before editing:** `inventory/urls.py`,
`config/settings.py`, `requirements.txt`.

---

## Conventions

- **Nothing writes stock except `apply_stock_movement()`.** Not Team A, not
  Team C. Any direct `BookInventory.objects.update()` puts the ledger and the
  movement log permanently out of step.
- **Derived values live in serializers**, not the database — unless they must
  be filtered or sorted in SQL, in which case they are queryset annotations.
- **Validation lives in serializers**, except invariants the movement engine
  must hold, since it is called from Python and never sees a serializer.
- **Money is `DecimalField`, never `FloatField`.** Currency is INR (Q5).
- **`on_delete=PROTECT` for anything a ledger row points at**, `SET_NULL` for
  people, so history survives an employee being deleted.
- Never import `django.contrib.auth.models.User` — the user model is
  `staff_auth.Employee`. Use `settings.AUTH_USER_MODEL` in FKs.
- Branches: `feat/<team>/<feature>`. One person per team generates migrations.

---

## Useful commands

```bash
python manage.py check                      # includes the DB-engine guard
python manage.py check --deploy             # HTTPS/cookie hardening
python manage.py makemigrations --check     # what CI enforces
python manage.py spectacular --file schema.yaml
docker compose up -d db                     # start PostgreSQL
docker compose down                         # stop it, keeping data
```

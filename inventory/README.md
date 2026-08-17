# Inventory Module

Django app that owns the warehouse / rack / vendor / book domain and exposes
it under `/api/v1/inventory/`: catalog CRUD, per-rack stock ledger, stock
movements, and a rich inventory report.

---

## Layout

Each file is owned by one team, so four teams can work in this app at once.
`__init__.py` re-exports everything, so `from inventory.models import Book`
works regardless of which module a model lives in.

```
models/ serializers/ views/ admin/
  base.py       shared abstract models
  location.py   Warehouse -> Section -> Rack             (Team A)
  catalog.py    Book                                     (Team B)
  stock.py      BookInventory, StockMovement, the engine (Team B)
  vendor.py     Vendor, PurchaseOrder, PurchaseOrderLine (Team C)
```

## Entity map

```
Warehouse ──< Section ──< Rack ──< BookInventory >── Book
                                        │               │
                                        └── Vendor ──< PurchaseOrder ──< Line
                                        │
                             StockMovement (append-only log)
```

Every model inherits `TimeStampedModel` (adds `created_at`, `updated_at`).

| Model | Notable fields | Notes |
|---|---|---|
| `Warehouse` | `name` (unique) | |
| `Section` | `warehouse`, `name` | Unique per `(warehouse, name)`. **Capacity is not stored here** (Q3) — `max_capacity` / `current_stock` are annotated from its racks by `Section.objects.with_rack_totals()`. |
| `Rack` | `section`, `name`, `max_capacity`, `current_stock`, `last_change_date`, `last_used`, `updated_by` | Unique per `(section, name)`. Stock fields are written only by `adjust_stock()`. `max_capacity = 0` means "unmeasured" and exempts the rack from the capacity constraint. |
| `Vendor` | `company_name`, `vendor_name`, `gst_number` (unique), `contact_person`, `phone`, `email`, `address`, `categories_supplied`, `is_blocked`, … | Blocked vendors are rejected by stock actions. |
| `Book` | `title`, `isbn` (unique), `author`, `class_level` + `board` + `subject` (Q4), `mrp` / `tax_percent` / `default_discount_percent` (INR `Decimal`, Q5), `default_*` location, `min_stock`, `low_selling` | `low_selling` is written by a future analytics job, not by the API. |
| `BookInventory` | `book`, `rack`, `vendor` (nullable), `in_entry`, `out_entry`, `curr_stock`, `last_out_at` | **Unique per `(book, rack)`** — one canonical ledger row per shelf location. |
| `StockMovement` | `book`, `rack`, `movement_type`, `quantity`, `balance_after`, `actor`, `reason`, … | **Append-only** (Q7). Never edited, never deleted; the admin registers it read-only. `quantity` is always positive — direction comes from `movement_type`, which is why adjustments are `ADJUSTMENT_IN` / `ADJUSTMENT_OUT`. |
| `PurchaseOrder` / `PurchaseOrderLine` | header + lines (Q8) | `DRAFT → PLACED → DISPATCHED → RECEIVED`, plus `CANCELLED`. |

Derived values (`deficit`, `needs_reorder`, `rack_location`) live in
`BookInventorySerializer` — kept out of the DB so business rules can move
without a migration. Values that must be *filtered or sorted* in SQL are
queryset annotations instead, because a `SerializerMethodField` is invisible
to the database.

---

## Endpoints

Base URL: `/api/v1/inventory/`

### Location & supplier CRUD

| Method | URL | Body |
|---|---|---|
| GET / POST | `warehouses/` | `{name}` |
| GET / PUT / PATCH / DELETE | `warehouses/{id}/` | |
| GET / POST | `sections/` | `{warehouse, name}` — `max_capacity` / `current_stock` are read-only totals of the section's racks |
| GET / PUT / PATCH / DELETE | `sections/{id}/` | |
| GET / POST | `racks/` | `{section, name, max_capacity}` |
| GET / PUT / PATCH / DELETE | `racks/{id}/` | |
| GET / POST | `vendors/` | `{company_name, vendor_name, gst_number, is_blocked}` |
| GET / PUT / PATCH / DELETE | `vendors/{id}/` | |

### Books

| Method | URL | Purpose |
|---|---|---|
| GET | `books/` | Book catalog (no stock info). |
| POST | `books/` | Create a book. |
| POST | `books/register/` | Explicit registration alias — same payload as POST `books/`. |
| GET / PUT / PATCH / DELETE | `books/{id}/` | Retrieve / edit / delete a book. |
| GET | `books/inventory/` | Rich rows joined across `Book / Rack / Section / Warehouse / Vendor`, including `deficit`, `needs_reorder`, `rack_location`. Consumed by the frontend inventory table. |
| POST | `books/{id}/stock-in/` | Body: `{"rack": id, "vendor": id, "quantity": >=1}` — increases `in_entry` and `curr_stock`. |
| POST | `books/{id}/stock-out/` | Same body — increases `out_entry`, decreases `curr_stock`. Returns **400** if `curr_stock < quantity`. |

### Response shape of `books/inventory/`

```jsonc
[
  {
    "id": 1,
    "book": 1,
    "book_title": "Django Guide",
    "isbn": "978-1",
    "rack": 1,
    "rack_location": "Main WH / A / R1",
    "vendor": 1,
    "vendor_name": "Acme",
    "in_entry": 25,
    "out_entry": 3,
    "curr_stock": 22,
    "deficit": 0,          // max(min_stock - curr_stock, 0)
    "needs_reorder": false  // curr_stock < book.min_stock
  }
]
```

---

## Business rules

* **Every stock change goes through `apply_stock_movement()`** — the single
  write path in `models/stock.py`. Both routes above call it, and so must
  Team C's PO-receive. Nothing else may write `BookInventory` or
  `Rack.current_stock`; a second writer puts the ledger and the movement log
  permanently out of step.
* **Stock-in** — always allowed for an unblocked vendor, within the rack's
  capacity. If no `BookInventory` row exists for `(book, rack)` yet, it is
  created; otherwise the existing row's counters accumulate.
* **Stock-out** — rejected with `400 {"detail": "Insufficient stock on the
  specified rack."}` if `curr_stock < quantity`. The check runs *inside* the
  row lock, so it cannot go stale between check and write.
* **Blocked vendors** — rejected with `400 {"vendor": ["Vendor is blocked."]}`.
  Enforced in the engine as well as the serializer, because the PO-receive
  path runs no serializer at all.
* **Concurrency — guaranteed, on PostgreSQL.** `apply_stock_movement()` locks
  the `BookInventory` row with `select_for_update()` and re-checks
  sufficiency under that lock (finding `H-1`, closed); `Rack.adjust_stock()`
  separately locks the rack, because two movements of *different books* onto
  one rack are not serialised by the first lock. Both are covered by
  `@pytest.mark.postgres_only` concurrency tests, including the insert race
  for two concurrent *first* movements of the same `(book, rack)`.
  `select_for_update()` is a silent no-op unless `DB_ENGINE=postgresql`
  (finding `H-2`) — `manage.py check` warns when it is not, and those tests
  skip rather than pass vacuously.
* **Timestamps** — `Rack.adjust_stock()` stamps `last_change_date`,
  `last_used` and `updated_by` on every movement (finding `M-1`, closed), and
  the engine stamps `BookInventory.last_out_at` on outbound movements. Both
  are single-writer by design.
* **Vendor attribution** — authoritative on `StockMovement` and
  `PurchaseOrder`. `BookInventory.vendor` is a convenience "last supplier
  seen": written only by an inbound movement that names one, never cleared by
  an unattributed receipt, never touched on stock-out (finding `M-7`).
* **Deficit / reorder flag** — computed server-side per row (see the response
  shape above); the frontend just renders it.

---

## Local setup & testing

Backend uses conda env `main` (see project convention).

```bat
:: from backend-shivalik\
conda activate main
pip install -r requirements-dev.txt
copy .env.example .env          :: then fill in DJANGO_SECRET_KEY
docker compose up -d db         :: PostgreSQL, per Q2
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Run the tests with `pytest`. The suite is expected to run against PostgreSQL:
`DB_ENGINE=sqlite` works for schema-level work but silently disables row
locking, so anything testing concurrency proves nothing there.

Authentication is JWT (`rest_framework_simplejwt`). Get a token from
`/api/v1/auth/login/` and pass `Authorization: Bearer <token>`. Every endpoint
requires one — `DEFAULT_PERMISSION_CLASSES` is `IsAuthenticated` project-wide,
and only `login/`, `token/refresh/` and `health/` opt out. Role-based classes
(`staff_auth.permissions`) are applied on every viewset but are still stubs
that admit any authenticated caller until Team D's permission matrix lands.

Browsable API docs: `/api/docs/`. Raw OpenAPI schema: `/api/schema/`.

### Quick Postman sequence

1. Admin: create a Warehouse, Section, Rack, Vendor, Book.
2. `POST /api/v1/inventory/books/{book_id}/stock-in/` with
   `{"rack": <rack_id>, "vendor": <vendor_id>, "quantity": 10}`.
3. `GET /api/v1/inventory/books/inventory/` — expect `curr_stock: 10` and
   `deficit`/`needs_reorder` reflecting `Book.min_stock`.
4. `POST .../stock-out/` with `quantity: 3` — expect `curr_stock: 7`,
   `out_entry: 3`.
5. Retry `stock-out` with `quantity: 999` — expect **400**.

---

## Built, but not yet wired up

Sprint 0 landed the whole schema in one migration so four teams would not
generate conflicting ones. Several models therefore exist with no endpoints
behind them yet — that is deliberate, not an oversight:

* ~~`StockMovement` engine~~ and ~~`Rack.adjust_stock()`~~ — **both landed.**
  Every movement now writes a `StockMovement` row (with `balance_after`) and
  stamps the rack. `models/stock.py` and `models/location.py` carry the
  details.
* `PurchaseOrder` / `PurchaseOrderLine` — no serializers or routes yet.
  **Team C, Tasks 4–6.** The engine they depend on is live, so
  `receive/` no longer needs an `xfail`.
* The new `Book` and `Vendor` fields are in the database but not in their
  serializers; `books/` and `vendors/` still expose the original five each.
* `staff_auth.permissions` classes are permissive stubs. **Team D, Task 2.**
* **No backfill of `StockMovement` from pre-engine `BookInventory` counters
  has run**, so `books/{id}/history/` will not reconcile against `curr_stock`
  for rows that predate the engine. **Team B, Task 7** — along with the
  reconciliation command that would catch a `Rack.current_stock` drifted from
  `Sum(BookInventory.curr_stock)`.

Still unbuilt: vendor block/unblock, rack info and empty-rack reads, the
top-level `stock/` resource (low-stock / in-stock / low-selling / history /
in-entries / out-entries, per Q14), dead stock, and self-signup.

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
| GET | `books/` | Book catalog — full schema (~22 fields incl. 3 derived location names). Filter with `?class_level=&board=&subject=`, search with `?search=` (title / ISBN). |
| POST | `books/` | Create a book. `mrp` is required (nullable at the DB level, but the API enforces it — see model docstring). |
| POST | `books/register/` | Explicit registration alias — same payload as POST `books/`. |
| GET / PUT / PATCH / DELETE | `books/{id}/` | Retrieve / edit / delete a book. |
| GET | `books/inventory/` | Rich rows joined across `Book / Rack / Section / Warehouse / Vendor`, including `deficit`, `needs_reorder`, `rack_location`. **Deprecated alias** — kept for the frontend, superseded by `stock/` below. |
| POST | `books/{id}/stock-in/` | Body: `{"rack": id, "vendor": id, "quantity": >=1}` — increases `in_entry` and `curr_stock`. |
| POST | `books/{id}/stock-out/` | Same body — increases `out_entry`, decreases `curr_stock`. Returns **400** if `curr_stock < quantity`. |
| GET | `books/{id}/history/` | Every `StockMovement` row for this book, newest first. Paginated. |
| GET | `books/{id}/in-entries/` | Same, filtered to `INBOUND_TYPES`. |
| GET | `books/{id}/out-entries/` | Same, filtered to `OUTBOUND_TYPES`. |

### Stock — the top-level ledger read surface (Q14)

| Method | URL | Purpose |
|---|---|---|
| GET | `stock/low-stock/` | Books where total stock — **summed across every rack**, not per-row — is below `min_stock`. Returns `curr_stock`, `deficit`, and a `racks` breakdown. |
| GET | `stock/in-stock/` | Books currently holding stock anywhere. Same shape as `low-stock/`. |
| GET | `stock/low-selling/` | Books flagged `low_selling` (full `BookSerializer`). |

All three are paginated and permissioned the same as everything else
(`IsAuthenticated`, `IsApprovedStaff`).

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
* **Deficit / reorder flag — aggregated per book, not per row.** A title with
  `min_stock = 10` split 4/4/4 across three racks holds 12 and is healthy,
  even though each individual row looks low on its own. `deficit` /
  `needs_reorder` (on `books/inventory/` rows) and `stock/low-stock/` /
  `stock/in-stock/` all compare against `BookInventoryQuerySet.
  with_book_totals()`'s `Sum(curr_stock)` across every rack the book sits on
  — a correlated subquery, so the number cannot be multiplied by another
  join a caller adds later. Computed server-side; the frontend just renders
  it.

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

Already running something else on port 5432 — another project's container, or
a Postgres you installed directly? Publish this one elsewhere rather than
fighting over the port:

```bat
set DB_PORT_HOST=5433 && docker compose up -d db
:: then set DB_PORT=5433 in your .env
```

Run the tests with `pytest`. The suite is expected to run against PostgreSQL:
`DB_ENGINE=sqlite` works for schema-level work but silently disables row
locking, so anything testing concurrency proves nothing there.

```bat
pytest -m smoke     :: ~3s — the fundamental invariants (see below)
pytest              :: everything
```

**`pytest -m smoke` is the gate CI runs first**, and the fastest way to know
a branch is not fundamentally broken: the API is closed to anonymous callers,
a stock movement updates every number it should, overselling is a 400 not a
500, the ledger reconciles against its own log, the core routes answer, and
the OpenAPI schema still generates without warnings. Each one is verified by
mutation — break what it guards and it goes red. It is a gate, not a spec:
keep it small and put new detail in the focused test files next to it.

Authentication is JWT (`rest_framework_simplejwt`). Get a token from
`/api/v1/auth/login/` and pass `Authorization: Bearer <token>`. Every endpoint
requires one — `DEFAULT_PERMISSION_CLASSES` is `IsAuthenticated` project-wide,
and only `login/`, `token/refresh/` and `health/` opt out. Role-based classes
(`staff_auth.permissions`) are applied on every viewset but are still stubs
that admit any authenticated caller until Team D's permission matrix lands.

Browsable API docs: `/api/docs/`. Raw OpenAPI schema: `/api/schema/`.

### Ledger maintenance

Two management commands keep `StockMovement` and the stored stock numbers
honest. Neither writes stock — the first writes *history*, the second writes
nothing at all.

```bat
:: Explain pre-engine stock: one ADJUSTMENT_IN opening-balance row per
:: (book, rack) that has stock but no movement history at all.
:: Idempotent — a second run is a no-op. --dry-run lists without writing.
python manage.py backfill_stock_ledger --dry-run
python manage.py backfill_stock_ledger

:: Verify. Exits non-zero on any drift, so it works as a cron/CI check.
python manage.py reconcile_stock_ledger
```

`reconcile_stock_ledger` checks two stored aggregates independently:

* `BookInventory.curr_stock` vs the signed sum of that `(book, rack)`'s
  movements — proves the backfill worked, and would catch a bug in
  `apply_stock_movement()`.
* `Rack.current_stock` vs `Sum(BookInventory.curr_stock)` for that rack —
  would catch a bug in `Rack.adjust_stock()` specifically.

It **reports only and never auto-fixes**: silently correcting a stock number
outside `apply_stock_movement()` is the second-writer problem the ledger
exists to prevent. A genuine discrepancy is corrected with a human-reviewed
compensating `ADJUSTMENT_IN`/`ADJUSTMENT_OUT` movement through the engine.

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
* ~~The new `Book` fields are in the database but not in the serializer~~ —
  **`BookSerializer` now exposes all of them.** `Vendor` is still the
  original five; **Team C, Task 1.**
* `staff_auth.permissions` classes are permissive stubs. **Team D, Task 2.**
* ~~No backfill of `StockMovement` from pre-engine counters~~ — **done.**
  See *Ledger maintenance* below.

Still unbuilt: vendor block/unblock, rack info and empty-rack reads, dead
stock, and self-signup.

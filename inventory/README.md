# Inventory Module

Django app that owns the warehouse / rack / vendor / book domain and exposes
it under `/api/v1/inventory/`. This first cut delivers the **books slice** of
the guide in [`inventory_backend_task_guide.md`](../../inventory_backend_task_guide.md):
catalog CRUD, per-rack stock ledger, atomic stock movements, and a rich
inventory report.

---

## Entity map

```
Warehouse ──< Section ──< Rack ──< BookInventory >── Book
                                        │
                                        └── Vendor
```

Every model inherits `TimeStampedModel` (adds `created_at`, `updated_at`).

| Model | Notable fields | Notes |
|---|---|---|
| `Warehouse` | `name` (unique) | |
| `Section` | `warehouse`, `name`, `max_capacity`, `current_stock`, `last_change_date`, `updated_by` | Unique per `(warehouse, name)`. `updated_by → settings.AUTH_USER_MODEL`. |
| `Rack` | `section`, `name`, `last_used` | Unique per `(section, name)`. |
| `Vendor` | `company_name`, `vendor_name`, `gst_number` (unique), `is_blocked` | Blocked vendors are rejected by stock actions. |
| `Book` | `title`, `isbn` (unique), `min_stock`, `low_selling` | `low_selling` is written by a future analytics job, not by the API. |
| `BookInventory` | `book`, `rack`, `vendor`, `in_entry`, `out_entry`, `curr_stock` | **Unique per `(book, rack)`** — one canonical ledger row per shelf location. Counters are updated only through the view actions below. |

Derived values (`deficit`, `needs_reorder`, `rack_location`) live in
`BookInventorySerializer` — kept out of the DB so business rules can move
without a migration.

---

## Endpoints

Base URL: `/api/v1/inventory/`

### Location & supplier CRUD

| Method | URL | Body |
|---|---|---|
| GET / POST | `warehouses/` | `{name}` |
| GET / PUT / PATCH / DELETE | `warehouses/{id}/` | |
| GET / POST | `sections/` | `{warehouse, name, max_capacity}` |
| GET / PUT / PATCH / DELETE | `sections/{id}/` | |
| GET / POST | `racks/` | `{section, name}` |
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

* **Stock-in** — always allowed for an unblocked vendor. If no `BookInventory`
  row exists for `(book, rack)` yet, it is created; otherwise the existing
  row's counters accumulate.
* **Stock-out** — pre-flight check rejects the request with `400
  {"detail": "Insufficient stock on the specified rack."}` if `curr_stock <
  quantity`.
* **Blocked vendors** — any stock movement using `vendor.is_blocked = True` is
  rejected with `400 {"vendor": ["Vendor is blocked."]}`.
* **Concurrency** — mutations run inside `transaction.atomic()` using
  `select_for_update()` + `F()` expressions, so simultaneous writes from two
  staff members can't stomp each other's counters.
* **Section snapshot** — every mutation rolls the parent
  `Section.last_change_date` forward via `timezone.now()`.
* **Deficit / reorder flag** — computed server-side per row (see the response
  shape above); the frontend just renders it.

---

## Local setup & testing

Backend uses conda env `main` (see project convention).

```bat
:: from backend-shivalik\
conda activate main
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Authentication is JWT (`rest_framework_simplejwt`). Get a token from
`/api/v1/auth/…` and pass `Authorization: Bearer <token>`. Note: no
`DEFAULT_PERMISSION_CLASSES` is set project-wide, so endpoints currently
default to `AllowAny` — tighten this in a follow-up before shipping.

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

## Explicitly out of scope for this slice

Landed in follow-up PRs so the diff stays reviewable:

* Purchase orders and dispatch action (`POST /purchase-orders/create/`,
  `PATCH /purchase-orders/{id}/dispatch/`).
* Vendor `is_blocked` toggle action.
* `Rack.is_empty` and `empty_for_how_many_days` computed properties.
* `Section.current_stock` auto-recalculation via signals.
* `Book.low_selling` background analytics job.
* Project-wide `DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]`.

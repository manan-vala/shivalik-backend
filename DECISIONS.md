# Decisions taken in Sprint 0

The context pack's change contract says an answered question — *including one
answered implicitly by code* — gets recorded. This file is that record for the
backend.

The matching entries have been written into `context/06-open-questions.md`
(now `v2.0`) and `context/CHANGELOG.md` (`v2.0.0`). If the two ever disagree,
the context pack is the authority for *why* and this file is the authority for
*what the code actually does* — reconcile them in the same PR as the change.

## Answered before Sprint 0 (by the team)

| Q | Decision | Where it shows up in code |
|---|---|---|
| **Q2** | PostgreSQL | `config/settings.py` (`DB_ENGINE`), `docker-compose.yml`, `api/checks.py` warns on anything else |
| **Q3** | Rack owns capacity; Section aggregates | `models/location.py`, migration `0003` |
| **Q7** | Build the `StockMovement` log | `models/stock.py` |
| **Q10** | `role` is a `choices` enum | `staff_auth/models.py`, migration `0002` |

## Answered during Sprint 0

These had to be decided to land the schema in one migration. Each is the
recommendation already argued for in `context/06-open-questions.md` unless
noted.

| Q | Decision | Reasoning |
|---|---|---|
| **Q4** — book category | `class_level` + `board` + `subject`, three indexed `CharField`s | The Figma card renders "CLASS 12 • CBSE" — two dimensions, not one label. The persona's pain point is managing stock *across* categories, which free text cannot support. No `Category` table: nobody has designed the screen that would manage it. |
| **Q5** — currency | INR only. `DecimalField(max_digits=10, decimal_places=2)` | GST fields throughout confirm an Indian business; the Figma `$45.00` is placeholder data. `settings.DEFAULT_CURRENCY = "INR"`. Never `FloatField`. |
| **Q6** — `categories_supplied` | `JSONField(default=list)` | Team C's call to revisit. Chosen over Postgres `ArrayField` only so the test suite can run on SQLite for schema work; on Postgres it is `jsonb` and still queryable. One-line migration to swap. |
| **Q8** — purchase orders | Header + lines | `PurchaseOrder` + `PurchaseOrderLine`. The ERD sketches the relationship, not the document; one PO per title is not how anyone orders. Status: `DRAFT → PLACED → DISPATCHED → RECEIVED`, plus `CANCELLED`. Note `03-data-model.md` says `CREATED` where the team file says `PLACED` — `PLACED` won. |
| **Q9** — dead stock | Computed on read | No `DeadStock` table. Added `BookInventory.last_out_at` and `Book.dead_stock_threshold_days`, with `settings.DEAD_STOCK_DEFAULT_DAYS = 90`. |
| **Q14** — ledger routes | Promote to a top-level `stock/` resource; keep `books/inventory/` as a deprecated alias | The frontend consumes nothing yet, so the rename is free today and expensive in a month. **Not yet implemented** — Team B's Task 6 builds the new routes. Q14 was missing from `teams/README.md`'s open list; it blocks that task. |
| **Q1** — one backend or two | One backend, no `organisation` field anywhere | Taking the recommendation by not building the alternative. Revisit before adding client/order models. |

## Deviations from the team task files

Three places where the written task deviates from what was built. Each is a
correction, not a preference — raise them at the next sync.

1. **`ADJUSTMENT` is split into `ADJUSTMENT_IN` and `ADJUSTMENT_OUT`.**
   `TEAM-B-INVENTORY.md` specifies `IN`, `OUT`, `ADJUSTMENT`, `RECEIVE` with
   "quantity always positive, direction comes from `movement_type`". Those two
   rules contradict each other: a single `ADJUSTMENT` value cannot express
   "correct this down by three", which is the common case. Also added
   `RETURN_IN` and `WRITE_OFF` from `03-data-model.md` — choices are cheap now
   and a migration later. `TRANSFER` was deliberately left out: a rack-to-rack
   move is an `OUT` plus an `IN`, so both racks stay derivable from the log.

2. **`StockMovement.balance_after` was added.** Not in either document. It
   records `curr_stock` immediately after the movement, under the same lock,
   which turns reconciliation into one comparison instead of replaying the
   whole log. Adding a column to a large append-only table later is exactly
   the expensive case.

3. **`BookInventory.vendor` is now nullable** (finding `M-7`). It was
   `NOT NULL`, while the engine signature has `vendor=None` — an outbound
   movement for a `(book, rack)` pair with no existing row would have raised
   an `IntegrityError`. Vendor is a property of a purchase, not of a shelf;
   the authoritative attribution is on `StockMovement` and `PurchaseOrder`.

## Bugs found in review, and what they cost to miss

Recorded because each one is a shape of mistake this codebase will make
again.

1. **`DB_NAME` was shared by both database branches.** Flipping
   `DB_ENGINE=postgresql` in a `.env` written for SQLite would have looked for
   a Postgres database literally named `db.sqlite3`. SQLite now reads
   `SQLITE_NAME`, so the switch is one line and cannot half-apply.
2. **`POST /sections/` silently dropped two fields.** Q3 turned
   `max_capacity` / `current_stock` into annotations; a freshly created
   Section has never been through `with_rack_totals()`, and a read-only
   `IntegerField` *omits* a missing attribute rather than failing. `POST` and
   `GET` answered with different shapes and nothing raised. Now a
   `SerializerMethodField` with an aggregate fallback.
3. **Shrinking a rack's capacity below its stock returned 500.** The
   `rack_stock_within_capacity` constraint raised `IntegrityError`, which DRF
   reports as a server error. Guarded in the serializer, so it is a 400 that
   says what to do. Same shape as the `PositiveIntegerField` underflow trap
   waiting for Team B's engine.
4. **HTTPS hardening broke the entire test suite.** Turning on
   `SECURE_SSL_REDIRECT` for `DEBUG=false` made `SecurityMiddleware` answer
   the test client — which speaks plain HTTP — with 301s. 21 tests failed
   under exactly the configuration CI runs. Fixed with a session fixture in
   `conftest.py`; it cannot be fixed with an environment variable there,
   because pytest-django calls `django.setup()` before conftest is imported.

## Known gaps left open on purpose

* **`H-4`** — the hardcoded `'password123'` default in
  `staff_auth/serializers.py` is untouched. It is Team D's Task 5, and it now
  sits behind an authenticated admin-only route.
* **`H-1`** — the stock-out race is still there. Fixing it *is* Team B's Task
  2/3; Sprint 0 only made the fix possible (PostgreSQL, the engine stub).
* **No `StockMovement` backfill.** `05-implementation-playbook.md` Phase 3
  requires existing counters to be written back as opening-balance rows.
  Unassigned in every team file. Team B should own it with Task 2.
* **Reviewer direction is contradictory.** `teams/README.md` and
  `TEAM-EXECUTION-PLAN.md` §6 say A→B→C→D→A; all four team files say the
  reverse. Pick one.

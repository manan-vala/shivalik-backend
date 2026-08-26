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

## Decisions taken while implementing the movement engines

The two engines landed after Sprint 0 (Team B Tasks 2–3, Team A Task 2).
Four choices were made that neither the task files nor the context pack
specified.

| Decision | Reasoning |
|---|---|
| **`Rack.adjust_stock()` takes its own `select_for_update()`** on the rack | The contract only promised the caller's `BookInventory` row was locked. That does not serialise two movements of *different books* onto the same rack, so the capacity check had the same check-then-update race as `H-1`, one level down. Verified by removing the lock and watching the test go red. |
| **`BookInventory.vendor` is written only by an inbound movement that names a vendor** | Closes the open half of `M-7`. An unattributed receipt no longer erases the supplier on record, and stock-out no longer touches the column at all. The field's `help_text` already described it as "last supplier seen"; the code now matches. |
| **`stock-out` no longer forwards `vendor` to the engine** | `StockMovement.vendor` is documented "set on incoming stock only". The request body still requires the field and still rejects a blocked vendor at the serializer, so the API contract is unchanged — but an OUT row carrying a vendor was attribution noise. |
| **The engine validates `movement_type` and normalises `reason=None` → `""`** | Both were live 500s. `signed_delta` raises `ValueError` on an unknown type and `StockMovement.reason` is NOT NULL; the engine is called directly from Python by Team C with no serializer in front of it, so it has to be the layer that returns a 400. See the trap added to `05` §5.3. |

## Decisions taken finishing Team B's module (Tasks 5–7)

| Decision | Reasoning |
|---|---|
| **`mrp` is `required=True` via `extra_kwargs`, not a manual field override** | Keeps DRF's automatic propagation of the model field's own validators (`MinValueValidator`), which a hand-written `serializers.DecimalField()` would have dropped silently. |
| **`BookInventoryQuerySet.with_book_totals()` — a correlated subquery, not `annotate(Sum("inventory_records__curr_stock"))`** | The same reasoning as `Section.objects.with_rack_totals()`: a joined `Sum` multiplies against any other join a future caller adds, and the bug is invisible until the numbers are quietly wrong. Fixes the low-stock/`needs_reorder` per-row bug the task file called out. |
| **`backfill_stock_ledger` and `reconcile_stock_ledger` are management commands, not a data migration** | Re-runnable, `call_command`-testable, and a bug found later is a code fix rather than a second migration correcting the first. Matches the existing `seed_inventory` convention. |
| **Backfill targets "zero movement history for this `(book, rack)`", not "no row with our specific reason string"** | The narrower definition would re-backfill on top of a `(book, rack)` that already has one real movement but predates a hypothetical future reason-string change. "Zero movements at all" is both the semantically correct definition of "unexplained stock" and what makes the command idempotent for free. |
| **Reconciliation reports only; it does not auto-fix** | Auto-correcting a stock number outside `apply_stock_movement()` is exactly the second-writer problem this whole design exists to prevent. A real discrepancy gets a human-reviewed compensating `ADJUSTMENT` movement. |
| **Every derived/annotated field on `BookSerializer` and `BookStockLevelSerializer` is a `SerializerMethodField`** | Not `CharField(source=…)` or `IntegerField(read_only=True)`. See the two bugs below — this is the third and fourth time the same DRF behaviour has cost this codebase a wrong response shape. |

## Bugs found reviewing Tasks 5–7, and what they cost to miss

Both are the *same* DRF behaviour as recorded bug #2 above (`POST /sections/`
silently dropping two fields), which is why the playbook's §5.3 entry has
been rewritten from "give it a fallback" to "use a `SerializerMethodField`".

1. **`BookStockLevelSerializer` 500'd on any `Book` without the queryset
   annotation.** `curr_stock` was `IntegerField(read_only=True)` reading
   `_books_with_stock_totals()`'s annotation. On a bare `Book` the attribute
   is missing, so DRF *omitted* the key — and `get_deficit`, which computes
   from it, raised `AttributeError` → 500. Both current callers annotate, so
   it was latent; `reorder/` is documented as consuming this exact number and
   would have hit it. Fixed with a method field plus an aggregate fallback,
   matching `SectionSerializer`.
2. **`PATCH /books/{id}/` silently returned three fewer fields than GET and
   POST.** `default_warehouse_name` / `default_section_name` /
   `default_rack_name` were `CharField(source="<fk>.name", default=None)`.
   The `default=None` was added specifically to survive a null FK — and it
   does, on GET and POST. But `Field.get_default()` begins
   `if self.default is empty or getattr(self.root, 'partial', False): raise
   SkipField()`, so on a **partial update the default is skipped entirely**
   and all three keys vanish. Nothing raised; the endpoint just answered with
   two different shapes depending on the verb. A test now asserts
   GET/POST/PATCH produce identical key sets.

## Bugs found running the backend for the first time

Everything green until now came from `pytest` and `manage.py check`. Booting
the app and driving it over HTTP found something neither could:

1. **The IP allow-list locked every deployment out of its own API.**
   `CustomTokenObtainPairSerializer.validate()` refused any client whose IP had
   no `WhitelistedIP` row. That table starts empty and **nothing seeds it** —
   not a migration, not `seed_inventory`, not the README — so on a fresh
   database `/api/v1/auth/login/` returned 401 to correct superuser
   credentials, and every authenticated endpoint in the project was
   unreachable behind a token nobody could obtain.

   It survived review because the login route had **no passing-path test at
   all**. The only coverage, `api.tests.test_login_is_reachable_without_a
   _token`, posts `{}`; that 400s on field validation *before* `validate()`
   runs, so the allow-list was never exercised in the suite.

   Now gated on `ENFORCE_IP_ALLOWLIST`, defaulting to `not DEBUG` — the same
   shape as `ENFORCE_ROLE_PERMISSIONS`. `LoginIPAllowlistTests` covers the
   route properly: enforced-and-listed, enforced-and-unlisted, unenforced, and
   that relaxing the IP check does not relax the approval or password gates.

   The allow-list is still the intended production control. Populate it via
   `/admin/` **before** setting `ENFORCE_IP_ALLOWLIST=true`, or you will
   reproduce the lockout deliberately.

## Known gaps left open on purpose

* **`H-4`** — the hardcoded `'password123'` default in
  `staff_auth/serializers.py` is untouched. It is Team D's Task 5, and it now
  sits behind an authenticated admin-only route.
* ~~**`H-1`** — the stock-out race~~ **closed.** The racy check and
  `_apply_movement` are both deleted; both stock routes call
  `apply_stock_movement()`, which re-checks under its lock.
* ~~**No `StockMovement` backfill.**~~ **Closed.** `backfill_stock_ledger` +
  `reconcile_stock_ledger` (Team B, Task 7) — the ledger now reconciles for
  pre-existing stock too. Team B's module is complete.
* **Reviewer direction is contradictory.** `teams/README.md` and
  `TEAM-EXECUTION-PLAN.md` §6 say A→B→C→D→A; all four team files say the
  reverse. Pick one.
* **`inventory/models/location.py` is Team A's file** by the ownership split,
  but `Rack.adjust_stock()` was implemented alongside Team B's engine because
  the engine could not be exercised end to end without it. The signature is
  unchanged from the published stub, so nothing Team A wrote against it moved
  — but they should review it rather than reimplement it.

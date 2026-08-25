# Team C — Vendor & Purchase Orders (Backend)

**2 people · Backend only · You have no dependencies — you can start first**

You own suppliers and the purchase order flow. Nothing blocks you, and you block
nobody. Start the moment Sprint 0 lands.

---

## Files you own

```
inventory/models/vendor.py
inventory/serializers/vendor.py
inventory/views/vendor.py
```

**Shared files** (`urls.py`, `settings.py`, `requirements.txt`) — tell the group
chat before you touch them.

---

> ### 📌 Status after Sprint 0
>
> **The models for Tasks 1 and 4 are already built** — all vendor fields,
> `PurchaseOrder` and `PurchaseOrderLine` landed in the shared migration set,
> and Q8 is answered. **None of it is exposed**: no serializer changes, no
> routes. That is your work, and it is now most of your work.
>
> **Task 6 (receive) is unblocked** — Team B's engine is implemented and
> tested. Write the real call, not an `xfail`.

## Task 1 — Complete the Vendor fields 🟡 columns landed, serializer is yours

All the fields exist in the database as of `inventory/0002`:
`contact_person`, `phone`, `email`, `address`, `categories_supplied`,
`expected_delivery_days`, `payment_terms`, `notes`.

**`VendorSerializer` still exposes only the original five**, so the *Add New
Vendor* screen cannot be built against it yet. That is Task 1 now — plus the
validation, which **goes in the serializer, not the model**: phone format,
email format, GST number format.

### Q6 — `categories_supplied` is still yours to decide

Landed as **`JSONField(default=list)`** so the Day-3 schema was complete. That
was a placeholder for your decision, not a substitute for it. It is queryable
as `jsonb` on PostgreSQL and keeps the test suite runnable on SQLite for
offline schema work, which `ArrayField` would prevent.

**Swap it for `ArrayField` if you prefer** — it is a one-line migration and
affects no other team. Either way, record the decision in
`context/06-open-questions.md`.

---

## Task 2 — Block / unblock a vendor ⚠️ P0

Two endpoints the spec explicitly requires:

- `PATCH /vendors/{id}/block/` → sets `is_blocked = True`
- `PATCH /vendors/{id}/unblock/` → sets `is_blocked = False`

These drive the Active Vendors / Inactive Vendors views in the UI.

---

## Task 3 — Vendor list endpoints

- `GET /vendors/active/` — vendors where `is_blocked = False`
- Filters on the main list: `?is_blocked=`, `?search=` (company or vendor name)

---

## Task 4 — Purchase Order models ✅ models done, rules are yours

**Q8 is answered: header + lines.** Both models landed in `inventory/0002`:

**`PurchaseOrder`** — `vendor` FK (`PROTECT`), `status`, `order_date`,
`expected_delivery_date`, `dispatched_at`, `received_at`, `created_by` FK →
Employee (`SET_NULL`), `notes`

**`PurchaseOrderLine`** — `purchase_order` FK (`CASCADE` — a line has no
meaning without its order), `book` FK (`PROTECT`), `quantity_ordered`,
`quantity_received` (default 0), `unit_price`, with check constraints for a
positive quantity and a non-negative price

**Status values:** `DRAFT` → `PLACED` → `DISPATCHED` → `RECEIVED`, plus
`CANCELLED`. (`03-data-model.md` said `CREATED` where this file said `PLACED`;
`PLACED` won.)

**What is left is the part that matters: enforce legal transitions in the
serializer** — you should not be able to receive an order that was never
placed. No serializer, viewset or route exists yet.

Two deliberate omissions you may want to revisit: there is **no unique
constraint on `(purchase_order, book)`** — listing a title twice at different
prices is legitimate enough that it seemed wrong to decide for you — and no
constraint stopping `quantity_received` exceeding `quantity_ordered`, since
over-delivery happens.

---

## Task 5 — Purchase Order endpoints

- `POST /purchase-orders/` — create
- `GET /purchase-orders/` — list, filter by `?vendor=` and `?status=`
- `GET /purchase-orders/{id}/` — detail, including its lines
- `PATCH /purchase-orders/{id}/dispatch/` — status → `DISPATCHED` (spec-mandated)

---

## Task 6 — Receiving stock ⚠️ The key integration point

`PATCH /purchase-orders/{id}/receive/` — the vendor's delivery arrives and the
books physically go onto a rack.

**You do not write stock yourself.** You call Team B's engine, once per line:

```python
from inventory.models import MovementType, apply_stock_movement

apply_stock_movement(
    book=line.book,
    rack=target_rack,
    quantity=line.quantity_received,
    movement_type=MovementType.RECEIVE,
    actor=request.user,
    vendor=purchase_order.vendor,
    purchase_order=purchase_order,
)
```

Then update `quantity_received` on each line and move the order status to
`RECEIVED`.

Three things about calling it:

- It returns the updated `BookInventory` row, and raises
  `InsufficientStockError` or DRF's `ValidationError`. Both are importable
  from `inventory.models`. Decide what a partial failure means for a
  multi-line receive — **wrap the whole receive in one `transaction.atomic`**
  so a delivery is not half-recorded.
- **No serializer runs on this path**, so serializer-level rules do not apply.
  The engine enforces blocked vendors, mandatory reasons, unknown movement
  types and `reason=None` internally for exactly this reason — all as DRF
  `ValidationError`, so they reach your caller as 400s, not 500s.
- ~~**It is still a stub**~~ — **it is implemented and tested.** Write the
  real call and a real test; no `xfail` needed. A `RECEIVE` movement will
  write a `StockMovement` row with `balance_after` and stamp the rack.
- **Rack capacity is enforced.** A delivery larger than the target rack's
  free space raises `ValidationError`, so pick the rack deliberately — and
  since your whole receive is one `transaction.atomic`, one over-capacity
  line rolls back every line with it.

> ### 🚨 Non-negotiable
> **Never write `BookInventory.objects.update()` yourself.**
>
> If PO-receive does its own stock write, the movement log will not match the
> real stock, and nobody will notice until reconciliation weeks later. Always go
> through `apply_stock_movement()`.

Team B publishes that function's signature as a stub on day 1, so you can write
this code before their engine is finished.

---

## Task 7 — Vendor detail extras

- `GET /vendors/{id}/purchase-orders/` — that vendor's order history
- On the vendor list, two derived values the mockup shows:
  - **Purchase Orders** — count of that vendor's POs
  - **Last Delivery** — most recent `RECEIVED` order date

Both are calculated, not stored. Use `annotate()` so you do not run a query per
vendor.

---

## How to split the work between 2 people

- **Person 1** — Task 1 (fields + validation) and Task 3 (list endpoints)
- **Person 2** — Task 2 (block/unblock) and, once Q8 is answered, Task 4
- **Both together** — Task 6 (receive). It touches Team B's engine, so both of
  you should understand it.

---

## Rules

- Branch naming: `feat/vendor/<feature>` — e.g. `feat/vendor/block-unblock`
- One feature per PR. One person generates all your migrations.
- **Your reviewer is Team D.** You review Team B.
- Import permission classes from Team D from day one — do not leave views open.

---

## Definition of done (per feature)

- [ ] Model + migration, with sensible `on_delete` and constraints
- [ ] Serializer, with validation in the serializer layer
- [ ] View with explicit `permission_classes` (import from Team D)
- [ ] Registered on the router under `/api/v1/…`
- [ ] `select_related` / `prefetch_related` on list queries
- [ ] Registered in Django admin with a useful `list_display`
- [ ] Filters + pagination on list endpoints
- [ ] Tests: happy path, validation failure, permission denied
- [ ] For Task 6: a test proving receive writes a `StockMovement` row
- [ ] Cross-team review done

**No PR merges without a test.**

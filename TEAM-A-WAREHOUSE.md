# Team A — Warehouse (Backend)

Backend only

You own the physical storage side of the system: Warehouse → Section → Rack.

---

## Files you own

```
inventory/models/location.py
inventory/serializers/location.py
inventory/views/location.py
```

Nobody else edits these. You do not edit anyone else's files.

**Shared files** (`urls.py`, `settings.py`, `requirements.txt`) — tell the group
chat before you touch them.

---

> ### 📌 Status after Sprint 0
>
> **Task 1 is done** — the schema landed in the shared migration set. **Task 2
> is now your P0 and Team B is blocked on it**: nothing in the system writes a
> rack's stock, `last_used` or `last_change_date` until `adjust_stock()` has a
> body. Tasks 3–5 are unchanged.

## The decision that shapes your work

**Q3 is answered: capacity fields live on Rack, not Section.** ✅ Implemented.

---

## Task 1 — Move capacity fields onto Rack ✅ DONE

`Rack` now has `max_capacity`, `current_stock`, `last_change_date`,
`last_used` and `updated_by` (migrations `inventory/0002` and `0003`), and
`Section` no longer stores any of them.

Two things about the data migration you should know, because they are yours to
live with:

- **`max_capacity` was divided evenly** across each section's racks, remainder
  to the first, so section totals are preserved. There was no better guess —
  the source recorded one number per section. **Where a rack already held more
  stock than its share, the observed stock won**, because a capacity below the
  contents is not a fact and would violate the new
  `rack_stock_within_capacity` constraint.
- **`current_stock` came from the ledger**, not from `Section.current_stock` —
  that column was never written by any code (`M-3`) and was 0 everywhere.

Section capacity is still readable: `Section.objects.with_rack_totals()`
annotates `max_capacity` and `current_stock` as sums over racks, and
`SectionSerializer` exposes them under the same names as before. It uses
correlated subqueries rather than a join-based `Sum` so the numbers cannot be
multiplied by a later join.

`max_capacity = 0` means **unmeasured**, not full — it exempts the rack from
the capacity constraint. Keep that meaning in `adjust_stock()`.

---

## Task 2 — Fill in `Rack.adjust_stock()` ⚠️ P0

**Team B will create this method as an empty stub on day 1** so they can write
their movement engine against it immediately. You do not need to create it —
you need to **replace the stub body with the real implementation**.

✅ The stub is merged in `inventory/models/location.py` and raises
`NotImplementedError`. **Read its docstring — it is the contract**, and it is
more specific than the list below in the places that would otherwise cost you
a debugging session.

Your real version must:

- Add `delta` to `current_stock`. **`delta` is signed** — positive inbound,
  negative outbound.
- Refuse to go below 0, or above `max_capacity`, by raising
  **`rest_framework.exceptions.ValidationError`**. Not Django's
  `django.core.exceptions.ValidationError` — that one surfaces as a **500**
  through DRF instead of a 400.
- Treat `max_capacity == 0` as *unmeasured* and skip the ceiling check. The
  `rack_stock_within_capacity` constraint encodes the same exemption; the two
  must agree.
- Set `last_change_date` and `last_used` to now, and `updated_by` to `actor`
  (which may be `None` — `SET_NULL`).
- Use `F()` expressions, never a read-modify-write in Python.
- **Persist the change itself and return `None`.** Callers do not save the rack
  afterwards.
- **Not open its own transaction.** It is always called inside the engine's
  transaction with the `BookInventory` row already locked.

**Do not change the method name or its arguments.** Team B's engine is already
calling it. If you need to change the signature, tell Team B first.

`inventory/tests/test_contracts.py` asserts the signature and that the stub
raises. Those assertions fail when you land the body — that is the signal to
replace them with real behaviour tests, not to delete them.

---

## Task 3 — Start writing `last_used`

The `last_used` field has **never been written to** by any code (audit finding
`M-1`). Every rack has `last_used = NULL`, which makes the "empty racks"
feature impossible.

This got slightly more urgent in Sprint 0: the old `Section.last_change_date`
write was removed along with the field, and deliberately **not** replaced in
the view. So right now *nothing anywhere* stamps a stock timestamp. Your
`adjust_stock()` is the only thing that will — that is the point, one writer of
rack state — so make sure it sets both `last_used` and `last_change_date`.

---

## Task 4 — The rack info block

The spec requires a rack "info" view. These four values are **calculated in the
serializer** — do not store them in the database:

| Field | How to calculate |
|---|---|
| `available` | `max_capacity - current_stock` |
| `is_empty` | `current_stock == 0` |
| `empty_for_days` | days since `last_used`, but only if empty — otherwise `null` |
| `books_stored` | count of `BookInventory` rows pointing at this rack |

Then expose: **`GET /racks/{id}/info/`**

---

## Task 5 — `GET /racks/empty/`

Returns every rack where `current_stock == 0`, with `is_empty` and
`empty_for_days` included. Only works once Task 3 is done — before that,
`empty_for_days` is always null.

---

## How to split the work between 2 people

Do **not** split by layer (one does models, one does views). That leaves one
person waiting.

- **Person 1** — Task 1 (schema + migration) and Task 2 (`adjust_stock`). This
  is the part Team B is blocked on, so it goes first.
- **Person 2** — Task 4 and Task 5 (the read endpoints), end to end:
  serializer → view → test.

---

## Rules

- **Never write stock directly.** All stock changes go through Team B's
  `apply_stock_movement()`, which calls your `adjust_stock()`. If you write
  `Rack.objects.update(current_stock=...)` anywhere, the ledger silently goes
  wrong.
- Branch naming: `feat/warehouse/<feature>` — e.g. `feat/warehouse/rack-info`
- One feature per PR. If your PR touches another team's files, it is too big.
- **Your reviewer is Team B.** You review Team D.

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
- [ ] Cross-team review done

**No PR merges without a test.**

---

## After this is done

You will finish before the other teams. Next you get:

1. The **Dead Stock** module
2. The `in-entries/` and `out-entries/` read endpoints (pure reads over Team B's
   movement log — they will have capacity problems by then)

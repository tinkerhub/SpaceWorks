# Inventory source-review follow-up findings

Status: all three source corrections implemented and independently inspected; central runtime validation pending.
Reviewer: Codex `/root/audit_backend_finish`.

## INV-S01 — Aggregate fix actions diverge from individual units

`inventory/availability_requests.py` exposes aggregate repair, shelving and scrapping
helpers that lock the product and change only its quantity buckets. Neither the product
needs-fix API nor the native control action rejects individually tracked products.
Consequently, an individual maintenance unit can remain in `maintenance` while its
product is reported as available after aggregate repair. Aggregate scrapping can reduce
the total while leaving a unit that a later reconciliation counts again.

The implemented correction refuses individual products centrally after the product lock,
before quantity or audit writes. The existing per-unit fix endpoint remains the path
for actual unit changes. The staff shelf now exposes that existing unit manager for
individual products rather than abstract repair/scrap counts.

## INV-S02 — Fix eligibility is stale after waiting for an asset lock

`admin_api/views_assets.py` validates a fix action's allowed status before entering its
transaction, then passes the freshly locked asset to the general status-moving
primitive without repeating the action-specific check. If issue commits between those
steps, the stale shelving request can move an issued asset to maintenance and remove
its issued bucket while the physical loan remains active.

The implemented correction validates the actual locked row. Both asset edit paths now
use non-key maker locking and asset-only `FOR UPDATE OF self`, preserving the existing
module gate while permitting issue audit foreign-key checks to finish. Four real
PostgreSQL race cases were added, including exact observed asset-row blocking and
module-configuration serialization. Their runtime results remain owned by the root
audit coordinator; source inspection is not a test pass.

## INV-S03 — Explicit zero silently selects the full shelf count

`frontend/src/features/staff/panels/NeedsFixShelf.tsx` computes a quantity with
`Number(input) || needs_fix_quantity`. Explicit zero and invalid numeric input thus
fall back to the entire shelf count, leaving aggregate repair and scrap enabled.
Only an untouched input uses the displayed default. Explicit blank, zero, non-integer,
negative, excessive or nonfinite values remain invalid. Both action controls and the
final mutation revalidate, including an already-open scrap confirmation.

These findings came from reading the actual quantity, image, serializer, public-view,
native admin and caller sources, not from existing flow-map labels. The three production files and 24 added test cases are frozen in
`individual-fix-freeze.json`; the Stage 1/2/3 result files record the bounded gates.
No runtime test pass or live production action is claimed here. The eventual
per-owner decision packet must bind exact file hashes and identify every owner that
remains unexamined or pending correction.

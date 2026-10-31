# HW001 loan return boundary — Stage 3 test handoff

Scope: tests only for the approved loan-return boundary plan and delta. No production
files or existing tests were edited; no staging or commits. No pytest, test collection,
runtime checks, TypeScript checks, builds, or review process that might run tests was
invoked. Execution belongs to the coordinating root on Linux with Python 3.12+,
PostgreSQL 16, and actual `age`. There is no runtime pass claim.

## Files and exact selectors

New files (paths relative to the repository root):

- `backend/tests/loan_return_boundary_helpers.py`
- `backend/tests/test_loan_return_boundary.py` — five test functions, eight expanded cases.
- `backend/tests/test_public_return_ledger_integrity.py` — four test functions, ten expanded cases.
- This handoff document.

Selectors below are relative to `backend/`. Selecting each function includes its
parameter cases; together these select all 18 new cases:

```text
tests/test_loan_return_boundary.py::test_reviewed_return_api_refuses_real_loan_before_promotion
tests/test_loan_return_boundary.py::test_reviewed_return_service_also_refuses_real_loan
tests/test_loan_return_boundary.py::test_reviewed_return_keeps_permission_and_tenant_boundary
tests/test_loan_return_boundary.py::test_reviewed_return_does_not_trust_cached_absent_loan
tests/test_loan_return_boundary.py::test_reviewed_return_rechecks_association_after_real_promotion
tests/test_public_return_ledger_integrity.py::test_public_return_refuses_historical_reviewed_resolution
tests/test_public_return_ledger_integrity.py::test_public_return_service_refuses_inconsistent_backing_ledger
tests/test_public_return_ledger_integrity.py::test_public_return_rechecks_ledger_after_real_promotion
tests/test_public_return_ledger_integrity.py::test_canonical_secondary_qr_returns_whole_batch_exactly_once
```

Existing compatibility selectors to execute centrally alongside the new files:

```text
tests/test_inventory_lending_reconciliation.py::test_public_and_staff_counts_follow_reviewed_lifecycle
tests/test_admin_direct_loans.py::test_admin_direct_manual_handout_and_return_logs_product
tests/test_public_self_checkout_multi.py::test_returning_by_second_qr_closes_the_same_public_loan
tests/test_public_self_checkout.py::test_public_return_report_problem_creates_report_and_keeps_stock_available
```

The reviewed lifecycle selector includes actual partial and final returns across
quantity/individual tracking and assigned/containerless loans. The new direct API
refusal case also follows rejection with a real canonical direct full return using
the same still-unused photo. The new secondary-QR public control returns a two-unit
batch exactly once, with and without a problem report; replay uses a fresh photo and
the primary QR, excluding evidence reuse as an alternative explanation for refusal.

## Fixture validity and assertions

- Public and direct happy setup uses real API checkout/handout endpoints, serializers,
  RBAC, request/item/loan creation, availability services, evidence promotion, and
  audit writes. Initial inventory starts entirely available. No issued/reserved
  quantities are fabricated for these producers. Public API responses are resolved
  through their public request token, since they do not expose an internal loan ID.
- Reviewed setup reuses `submit_request` from `inventory_lending_helpers` for its real
  request submission, then calls actual accept and issue services. It does not use
  `make_lab` or that helper's notification replacement. Notifications remain real.
- Evidence transport reuses `uploaded_images`/`photo` from
  `inventory_lending_evidence_helpers`: only the S3 provider is replaced with the
  versioned image store. Its real decodable PNG bytes pass the actual storage/image
  validators, staging COPY, deletion, and finalization coordination. The helper
  restores the real validators masked by the legacy autouse evidence fixture.
- Tests switch the helper's POST setting to PUT and enable actual managed storage
  accounting through the documented `limits.is_self_host` environment seam, with an
  explicit finite storage limit. This prevents unchanged quota assertions from
  passing merely because self-host accounting is disabled. Checkouts assert their
  actual finalized evidence is charged; the public control asserts a one-image byte
  increase on return.
- Refusal snapshots include complete request, item, product/reservation, asset/link,
  evidence, loan, problem-report, accountability, event/scan, and tenant audit rows,
  plus storage usage and finalization rows. Pre-existing invalid states must refuse
  without any additional provider calls, promotion, consumption, or charge. Member
  permission denial is 403; an authorized manager of another makerspace gets 404.
- The stale-instance case first caches an absent reverse OneToOne on a real reviewed
  issued request, then deliberately introduces a loan association. This association
  fixture changes no stock quantities and is used only to challenge admission.
- The post-promotion callback delegates to real `storage.finalize_upload` and changes
  state only after it completes. It simulates committed state becoming visible before
  the domain transaction; it is deterministic interleaving, not proof of concurrent
  PostgreSQL blocking or deadlock freedom. It never disables either real guard.
  Baselines are captured after the intentional mutation. Finalized bytes may remain,
  but evidence must stay uncharged/unattached and the domain must remain unchanged.
  Captured SQL after that mutation also excludes attempted settlement writes, so a
  debit followed by rollback cannot satisfy the ordering assertion.
- Historical damaged/lost fixtures invoke actual `build_resolutions`,
  `availability.return_items`, and `finalize_return_status` under a transaction to
  reconstruct the old reviewed-route stock/item/status projection while leaving the
  public loan checked out. They deliberately do not manufacture historical photos,
  return events, or accountability records. Both have `returned_quantity == 0`, the
  distinguishing old double-debit condition. They are historical fixture construction,
  not a production bypass or repair path.
- Other corruption cases isolate status-only, returned-only, needs-fix-only, and
  accepted-quantity mismatch states. Item-only variants leave the request issued so
  the status check cannot mask missing item validation. Two interleavings separately
  change status and returned quantity after promotion to require fresh request/item
  reads during settlement.
- Every legacy/corruption fixture retains another real, unrelated checked-out loan
  for the same quantity product with enough issued stock to expose the old bug. After
  refusal, that borrower returns through the actual canonical service. Its complete
  issued quantity is credited once, the bad loan's rows remain unchanged, and all
  physical inventory buckets remain nonnegative and sum to total stock.

## Static verification only

The three new Python files were parsed with `ast.parse`; whitespace and the
300-line ceiling were checked without importing Django or collecting tests. Source
inspection checked serializer response fields, evidence relationship names, and
the actual workflow signatures. Runtime fixture validity and behavior remain to be
verified centrally using the selectors above. Existing assertions, skips, and
runtime policies were not changed.

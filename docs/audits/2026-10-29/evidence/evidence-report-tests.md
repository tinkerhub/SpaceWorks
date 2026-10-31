# EVID-S01 Stage 3 test-writing handoff

Tests written for the approved implemented source. **Not collected or executed.**
No application runtime, DB connection, provider access, build, staging, commit or push
was performed. Source, existing tests and other docs were left untouched.

Owner-corrected durable plan locations, verified byte-identical to the temporary inputs:

- `docs/audits/2026-10-29/evidence/evidence-report-plan.md`
- `docs/audits/2026-10-29/evidence/evidence-report-plan-review.txt`

Also read `/tmp/spaceworks-evidence-report-stage2.txt`, the three implemented source
files, `docs/evidence-reporting.md`, actual retention policy/sweep/state constraints,
report cursor/refresh/fence code, applicable invariants and existing report/retention
fixtures. The sweep itself does not invoke `satisfy_retention_fence`; the tests
establish real rollups explicitly where needed and leave the sweep's real recovery,
tenant-write and policy gates in place.

## Files and static counts

| New path relative to repository root | Lines | Test functions | Expected cases |
| --- | ---: | ---: | ---: |
| `backend/tests/evidence/test_report_object_expiry_scopes.py` | 181 | 5 | 9 |
| `backend/tests/evidence/test_report_object_expiry_rollups.py` | 169 | 4 | 4 |
| `backend/tests/evidence/report_object_expiry_helpers.py` | 168 | 0 | 0 |

**Total: 9 test functions, 13 statically expected cases.** Counts come from AST
inspection of literal parametrization, not pytest collection. All three files parse
and stay below 300 lines. Static whitespace checks passed; no passing-test claim.

## Exact new selectors

Selectors below are relative to `backend/`; bracketed variants are separate selectors.

```text
tests/evidence/test_report_object_expiry_scopes.py::test_unrolled_sweep_changes_only_object_counts[issue]
tests/evidence/test_report_object_expiry_scopes.py::test_unrolled_sweep_changes_only_object_counts[return]
tests/evidence/test_report_object_expiry_scopes.py::test_failed_staging_delete_is_expiring_until_real_retry_completes
tests/evidence/test_report_object_expiry_scopes.py::test_exact_local_date_type_and_tenant_scope[live]
tests/evidence/test_report_object_expiry_scopes.py::test_exact_local_date_type_and_tenant_scope[rolled]
tests/evidence/test_report_object_expiry_scopes.py::test_kolkata_midnight_and_month_fold_use_local_creation_day[live]
tests/evidence/test_report_object_expiry_scopes.py::test_kolkata_midnight_and_month_fold_use_local_creation_day[rolled]
tests/evidence/test_report_object_expiry_scopes.py::test_aggregate_preserves_tenant_rows_and_real_module_visibility_gates[live]
tests/evidence/test_report_object_expiry_scopes.py::test_aggregate_preserves_tenant_rows_and_real_module_visibility_gates[rolled]
tests/evidence/test_report_object_expiry_rollups.py::test_old_rollup_reflects_sweep_without_rewriting_rows_or_report_audit
tests/evidence/test_report_object_expiry_rollups.py::test_reroll_appends_only_changed_metrics_and_never_subtracts_twice
tests/evidence/test_report_object_expiry_rollups.py::test_maintenance_delete_after_expiry_and_reroll_preserves_historical_fallback
tests/evidence/test_report_object_expiry_rollups.py::test_hybrid_cursor_boundary_combines_rolled_expiry_with_unrolled_rows_once
```

ROOT's combined selection, **only after the other DB test lane ends**, from `backend/`:

```text
python -m pytest -q tests/evidence/test_report_object_expiry_scopes.py tests/evidence/test_report_object_expiry_rollups.py tests/operations/test_report_coverage_rollups.py tests/evidence/test_object_retention.py tests/evidence/test_retention_rollup_boundaries.py
```

Use the existing documented DB-owner/encryption-key harness. This command was not run.
Do not run a concurrent DB test process or a review that starts its own tests.

## Behavior covered

- Real sweep before/after unrolled issue and return reports, with exact counts,
  immutable metadata snapshots, attachment relationships, recorded sizes, terminal
  state fields, expiry audit and successful deletion of both provider-fixture keys.
- Partial provider failure leaves `EXPIRING` out of terminal counts despite absent
  final bytes; a real retry finishes staging deletion and emits expiry once.
- Old creation buckets more than seven days behind the cursor change automatically
  on read after expiry, with every original rollup field/revision/checksum, report
  audit entry, cursor, metadata row and attachment unchanged.
- Explicit reroll appends only the two changed object metrics per affected type;
  historical metrics remain unchanged, reads do not subtract twice and an unchanged
  second reroll appends no metric revision/audit.
- Exact inclusive local-date start/exclusive end, neighboring dates, issue/return
  dimensions, another tenant, aggregate per-tenant rows, real module/visibility
  gates, record limit and mixed rolled/live cursor boundaries.
- Asia/Kolkata midnight where the UTC date is January 31 and the local date is
  February 1; daily grouping and January/February month folding on both report paths.
- Maintenance deletion **after expiry and reroll**, using the existing sanctioned
  transaction-local delete GUC for one unattached expired row. Its state cascades
  away; historical creations/attachments/bytes/metadata snapshots survive in rollups,
  retained-expired falls to zero and derived live rises to two. Surviving metadata,
  attachments, rollups and audits remain unchanged. The GUC ends with the transaction.
- `object_count_basis` explicitly describes unknown storage presence, no provider
  probe, recorded bytes rather than current storage/quota, snapshot semantics and
  the maintenance-deletion limitation. A missing unexpired reference still counts
  live; that is not evidence of current physical objects.

## Fixture limits

These are PostgreSQL-only Django SQL tests; the fixture refuses another database.
Normal tests use rollback isolation; the maintenance case uses transaction isolation
so `SET LOCAL app.allow_immutable_delete` expires at commit. No triggers are disabled,
no guard is changed and no photo timestamp is updated. `timezone.now` is controlled
before each photo INSERT and during the sweep; dates do not depend on execution day.
Attachment rows are focused model fixtures, not a replay of issue/return workflows.

Only provider operations (`object_size`, `delete_object_strict`, `object_exists`)
are replaced by a two-key in-memory byte store; unexpected provider-client access
fails. Reports are checked for zero provider-operation calls. The fixture does not
model S3 versions/delete markers, transport behavior, current quota correctness,
public API authorization or concurrency. Real report queries, retention selection,
claim/completion/retry, audit writes, recovery gate and tenant gate are not mocked.
Repository autouse fixtures still provide their existing module defaults and seeded
recovery/audit/PII state; visibility cases modify actual makerspace rows.

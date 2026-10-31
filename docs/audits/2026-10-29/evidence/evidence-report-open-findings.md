# Evidence reporting source follow-up

Reviewer: Codex `/root/audit_backend_finish`.
Status: source-confirmed finding; no production correction or runtime proof yet.

## EVID-S01 — Compliance reports count expired objects as live

`backend/apps/evidence/reports.py::_live_buckets` increments `object_live_count`
for every retained `EvidencePhoto` and unconditionally writes
`object_expired_count = 0`. `backend/apps/operations/report_rollups.py::_finalize_bucket`
bakes the same constants into new report revisions.

The actual retention service, `services_retention.py::_complete`, marks the separate
`EvidenceObjectRetentionState` as `expired`, records its timestamp/size, frees charged
storage and appends an audit entry. It intentionally retains the immutable photo row.
Therefore, after successful expiry, both live reporting and a newly recomputed rollup
still report that object's bytes as live. Existing retained historical rollups need
an explicit meaning: creation-time history and current retained-object state must not
be silently mixed.

The existing report-retention regression deletes photo rows behind the immutable-delete
maintenance gate and checks preservation of old rollup history; it does not exercise
actual byte expiry or the separate retention state. A correction should preserve that
history while adding genuine expiry coverage, live/current metrics, scoped tenant and
issue/return partitions, and append-only rollup revision assertions. No report ledger
or source decision is approved by this finding alone.

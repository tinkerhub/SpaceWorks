# Evidence source findings

Reviewer: `/root/audit_backend_finish` plus the pinned Codex CLI source reviewer.

Status: actual source-confirmed paths; no runtime exploit or correction pass claimed. This packet covers 19 files / 114 recursive AST owners. After its final hash check, the approved box workflow correction changed only the optional no-key quota forwarding in finalization.py; that entry remains explicitly stale pending deliberate rereview. Eighteen other file hashes and all owner names were independently checked. The exact original packet is retained in `evidence-source-decisions-pre-no-key.json`.

## EVID-S01 — P2: Compliance metrics count retained metadata as live objects after byte expiry

A successful services_retention._complete leaves EvidencePhoto intact and writes EvidenceObjectRetentionState.EXPIRED. reports._live_buckets still increments object_live_count for that photo and sets object_expired_count to zero. Newly finalized rollups use the same constants.

Live and recomputed compliance output misrepresents expired bytes as live.

Specify creation-time history versus current retained-object state, including the meaning of bytes. Preserve append-only historical revisions; define how current metrics remain correct for older rolled buckets. Cover actual byte expiry, issue/return partitions and tenant scope.

operations/test_report_coverage_rollups.py:116-149 deletes photo rows through the maintenance gate. evidence/test_retention_rollup_boundaries.py:39-61 exercises mocked expiry but asserts only that an existing rollup is unchanged. Neither establishes correct current live/expired report metrics.

Source evidence: `backend/apps/evidence/reports.py:70-96`, `backend/apps/evidence/services_retention.py:194-236`, `backend/apps/operations/report_rollups.py:69-94`, `docs/audits/2026-10-29/evidence/evidence-report-open-findings.md:1-26`

## EVID-S02 — P1: Expiry claims do not revalidate a newly committed retention policy

The sweep snapshots candidate IDs and policy_days once. Before a later candidate is claimed, a manager can commit update_policy increasing retention, for example from 30 to 365 days. _claim reloads the photo but never reloads policy or checks created_at against a fresh cutoff. The sweep deletes that candidate using the old snapshot.

Evidence bytes can be irreversibly deleted although the longer policy committed before their expiry claim.

The tenant source boundary uses shared coordination; it does not serialize ordinary policy updates against the sweep. No runtime interleaving was executed.

Source evidence: `backend/apps/evidence/retention_policy.py:38-72`, `backend/apps/evidence/retention_policy.py:75-85`, `backend/apps/evidence/services_retention.py:99-126`, `backend/apps/evidence/services_retention.py:154-191`, `backend/apps/tenant_migration/gate_runtime.py:59-98`

## EVID-S03 — P1: Expiry can subtract uncharged, client-declared bytes from unrelated managed storage

An authorized upload-URL request creates a photo with caller-supplied size_bytes before any upload or finalization. If no upload occurs, both object HEADs later return missing. The sweep falls back to recorded_size. With no finalization row, _complete treats quota_was_charged as true even in PUT mode and calls free_storage with that declared amount.

Expiry of an unuploaded photo can reduce storage_bytes_used for other objects, potentially to zero, weakening managed quota enforcement. This requires managed mode and an enabled sweep after the retention window.

Terminal-state idempotence prevents repeated subtraction for one row, but does not prove that the first subtraction corresponds to a charge. No provider or counter behavior was executed.

Source evidence: `backend/apps/evidence/serializers.py:7-15`, `backend/apps/evidence/views.py:68-98`, `backend/apps/evidence/finalization.py:60-76`, `backend/apps/evidence/services_retention.py:111-118`, `backend/apps/evidence/services_retention.py:186-190`, `backend/apps/evidence/services_retention.py:215-221`, `backend/apps/makerspaces/limits_usage.py:191-202`

## EVID-S04 — P2: Skipping an active finalizer leaves a committed expiry blocker

For an eligible photo with a fresh PROMOTING finalization and no retention row, _claim creates an EXPIRING retention row before checking the finalizer. It then returns None normally, committing that new row without a claim token. The finalizer can finish, but the consuming workflow's lock_evidence_for_attachment returns false because any retention row exists.

A sweep that reports the photo as skipped can nevertheless reject the in-flight issue or return attachment and leave it blocked pending subsequent retention processing.

The source-confirmed case uses an already eligible photo being finalized concurrently; no PostgreSQL interleaving was executed.

Source evidence: `backend/apps/evidence/services_retention.py:158-175`, `backend/apps/evidence/retention_models.py:51-62`, `backend/apps/evidence/finalization.py:106-118`, `backend/apps/evidence/finalization.py:151-172`, `backend/apps/hardware_requests/handover_workflow.py:106-128`

## EVID-S05 — P1: Evidence upload and detail omit staff-origin tenant admission

With API_CLIENT_AUTH_REQUIRED false and no opted-in HMAC credentials, an active staff_api actor authorized in spaces A and B can send an Origin-A request targeting B's upload URL or evidence detail. Upload checks HasMakerspaceAction; detail checks active authentication and actor-wide action scope. Neither invokes staff_origin_scope_allows or an equivalent origin restriction. JWT staff_api admission does not apply the staff-social origin validator.

A tenant frontend can obtain another authorized tenant's private evidence URL or create its upload metadata through the same actor session, violating the repository's origin-to-tenant boundary.

This does not bypass the actor's RBAC membership scope. It bypasses the additional browser-origin restriction. Retention settings use IsActiveStaff and do apply that restriction.

Source evidence: `backend/apps/evidence/views.py:40-52`, `backend/apps/evidence/views.py:63-98`, `backend/apps/evidence/views.py:120-145`, `backend/apps/evidence/views.py:186-205`, `backend/apps/accounts/permissions.py:44-63`, `backend/apps/accounts/authentication.py:59-86`, `backend/apps/makerspaces/origin_scope.py:139-161`, `backend/apps/inventory/middleware.py:45-65`, `docs/INVARIANTS.md:44-69`

All five findings remain open. Source decisions are bounded observations and must not be copied into the production review ledger as blanket approvals. Root owns runtime verification and final source-census binding.

## EVID-S06 — P2: Declared upload size lacks an upper-bound validator

`EvidenceUrlRequestSerializer.size_bytes` permits any nonnegative Python integer,
while `EvidencePhoto.size_bytes` is a PostgreSQL positive bigint. An authenticated
upload-URL request with an integer beyond the database range can therefore reach the
photo insert and raise a database error after presign generation. This is a source
trace; no live or runtime overflow attempt was executed.

The bounded candidate is a dynamic configured `EVIDENCE_MAX_BYTES` ceiling at the
serializer boundary, preserving optional/null/zero compatibility and rejecting an
oversized declaration before provider or database writes. This does not make a valid
declaration trusted accounting evidence. The final plan must include this companion
validation explicitly before source implementation.

## EVID-S07 — P2: Persistent early object failures can starve later expiry work

`retention_policy.object_candidates` orders by creation time and primary key, while
`services_retention._sweep_makerspace` always takes the first bounded batch. Failed
provider deletion leaves each photo eligible in its original position. If the first
batch repeatedly fails per object, later deletable photos are never attempted, even
though continuation_required remains true. This is a source trace, not runtime proof.

The candidate follow-up is least-recent-attempted traversal using existing retention
state updated_at, with fresh rows before previously attempted work, keeping all claim,
policy, source/recovery, provider failure and immutable-photo fences. It needs its own
plan review and real bounded two-sweep/provider-failure regression. No fairness source
change is part of the currently active S02–S06 writer.

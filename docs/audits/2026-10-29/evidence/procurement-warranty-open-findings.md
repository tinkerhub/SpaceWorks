# Procurement and warranty source findings

Reviewer: Codex `/root/audit_backend_finish`. Full current source read: all 18 procurement and 13 warranty top-level Python files, excluding migrations. Findings below are source-confirmed reachable traces; runtime reproductions and corrections are pending. No application source in these apps was edited by this reviewer.

## DOC-S01 — managed storage admission misses receipt and warranty bytes

`procurement/views_receipts.py::ToBuyReceiptListCreateView.post` and `warranty/views_documents.py::WarrantyDocumentCreateView.post` validate and publish private object bytes, then create document metadata and audit. Neither calls `limits.add_storage` or `check_quota`. Their storage helpers use the DB-free `object_publication.publish`; `object_storage_lifecycle.storage_lifecycle` owns source/storage exclusion only and adds no quota check. The managed finite storage counter therefore remains unchanged for these accepted documents until an operator runs reconciliation, so successive uploads evade the configured quota. `recompute_storage` explicitly counts both document kinds, confirming they belong to that accounting surface. `INVARIANTS.md` requires the managed counter to be charged at finalize.

Both deletion signals also omit quota release. Do not add credit based merely on a legacy row size or historical object: legacy accepted documents may never have incurred a debit. Any correction must preserve actual-byte validation, current source/storage lock order, no provider calls under row locks, private prefix binding, duplicate attachment idempotency, create-once final objects and conservative legacy credit. Root's exclusive whole-counter reconciliation boundary is separate owned work.

## PROC-S02 — initial ordered/received records omit lifecycle attribution

The writable `ToBuyItemSerializer.status` accepts ORDERED or RECEIVED on creation. `ToBuyListCreateView.perform_create` saves it and records `procurement.item_added` but does not call `stamp_status_change`. In contrast, PATCH and control-plane creation do call that helper. A valid direct create in either state therefore lacks its ordered/received timestamp and purchaser, affecting operator history and procurement performance reports. Correct initial creation through the existing helper, atomically with the write and audit; preserve existing create payload compatibility.

## PROC-S03 — control-plane machine-type retag bypasses provenance validation

`ToBuyDetailView.perform_update` calls both `validate_machine_type` and `validate_machine_type_provenance`; `ToBuyItemAdmin.save_model` only delegates save and stamps status. The existing `machine_type` field remains editable and its normal ModelForm does not implement those procurement invariants. A superuser can select another tenant's type, or retag a row away from `resulting_machine` / machine-bound source/result pool, contradicting the authorization label used by machine-scoped staff. This is a trusted control-plane integrity gap, not an external privilege escalation. Reuse existing validation at the actual admin boundary, keeping global machine types and legitimate unprovenanced retagging.

## WARR-S02 — sparse warranty updates can lose changes and detach their audit

`warranty/views.py::_upsert_warranty` uses atomic `get_or_create`, then mutates submitted keys and performs an unrestricted `warranty.save()` without locking an existing row. Two independent PUTs can read the same version; a later full save overwrites a field changed by the other request even when that later payload omitted it. The caller records `warranty.created/updated` after the helper's transaction has committed, so a failed audit can leave a persisted metadata change without its required entry. Serialize existing updates and keep the actor/audit in the same shared transaction; do not weaken one-host, tenant or machine-scope admission.

## WARR-S03 — control-plane re-hosting moves authority over old private documents

`WarrantyAdmin` permits changing existing `makerspace`, `asset`, and `machine`. `Warranty.clean` checks that a chosen new host matches its newly chosen tenant, so a consistent new host passes. Existing `WarrantyDocument` rows remain attached to that same warranty, retaining keys bound to the old tenant/warranty prefix. The new tenant then passes `warranty/access.py::enforce` and can obtain signed URLs for those old documents. The normal API fixes the host; the control plane bypasses that boundary. Keep tenancy and host fixed on existing records (date/vendor edits remain useful), or require a separately audited transfer with an explicit private-object policy. The bounded correction should prefer immutability.

## Coverage limits

The full reads cover scoped API and control-plane callers, models/serializers, report/status builders, provider helpers, lifecycle signals and route declarations. They do not establish runtime success, exhaustive global owner approval, live provider behavior, or a production-ready verdict. Per-owner decisions and exact file hashes are separate artifacts; changed owners must be re-reviewed after fixes.

## DOC-S04 — native metadata saves omit the append-only application audit

Confirmed independently by root and this reviewer: native `WarrantyAdmin` and `ToBuyItemAdmin` inherit no application audit save hook. `StorageDocumentDeleteAdminMixin` coordinates object cleanup, `SuperuserOnlyModelAdmin` enforces authorization/source boundaries, and ordinary `ModelAdmin` writes Django `LogEntry`; none writes `apps.audit.AuditLog` on add/edit. The repository already provides `config.admin_audit.AdminAuditMixin`, which records actor, target, tenant and changed field names without secret values, and skips no-op edits. The separately reviewed delta adds it after the storage deletion wrapper and before the superuser admin. Actual control-plane add/edit/audit-failure rollback tests remain pending.

Native host immutability must also be tested against a canonical asset-transfer race: a readonly form does not itself stop a stale full ORM save from rewriting old tenant/host values after the transfer. No extra source correction has been assumed or performed without its own reviewed evidence.

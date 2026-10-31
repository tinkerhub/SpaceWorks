# Box and QR source follow-up

Reviewer: Codex `/root/audit_backend_finish`.
Status: source-confirmed; no runtime proof or production correction yet.

## BOX-S01 — Native QR revocation does not share the checkout lock

`boxes/admin.py::QrCodeAdmin.revoke_selected` passes unlocked queryset instances to
`boxes/services.py::revoke_qr_code`. That service checks the instance's status and
queries for an active public/direct loan, then saves the QR and records an audit entry
without its own transaction or fresh row lock. The API revocation view wraps and locks
its own caller, but that does not protect the native control action.

A real checkout holds the QR row while creating its loan. Native revocation can observe
no loan while that transaction is uncommitted, then block at its save; after checkout
commits, revocation resumes and revokes the now-outstanding loan's QR. The relevant
public return path resolves only an active QR, so this can block a legitimate return.

The bounded candidate correction gives the central service its own atomic, freshly
locked QR and repeats both status and active-loan checks there. Its audit write shares
the same transaction. Existing API outer locking remains safe. Checkout's Maker lock
must stay compatible with QR/audit foreign-key checks; its optional no-key quota path
is part of the separately reviewed HW002/HW003 lock plan. Required runtime evidence is
an actual native action versus real checkout under independent PostgreSQL sessions,
with both winner orders and preserved return/evidence/stock/audit behavior.

## BOX-S02 — Create-box QR text lacks database-length validation

`CreateBoxQrSerializer.label` and `location` are explicit CharFields without a
`max_length`. Their `Box` destinations are varchar(200), and `CreateBoxQrView.post`
passes them directly to `Box.objects.create` without model full_clean. Only
IntegrityError is caught. A 201-character value therefore has a source path to a
PostgreSQL DataError/500 rather than a typed validation response. No runtime oversized
request was executed. The bounded correction is max_length=200 on these two serializer
fields plus real API refusal/no-write assertions. This remains a separate open input
finding and is not closed by the passing checkout/QR concurrency groups.
# BOX-S03 — stale generic QR targets produce server errors and failed-read scan writes

Actual source trace, reviewer `/root/audit_backend_finish`, 2026-10-30; runtime pending. `BoxAdmin` inherits delete permission and permits deleting a box with no protected scan rows. `QrCode.target_id` is a generic positive integer, so that box deletion leaves an active QR row. `boxes/serializers.py::qr_target_payload` calls bare `Box/InventoryAsset/InventoryProduct.objects.get(pk=qr.target_id)`; the configured DRF exception handler does not map their `DoesNotExist`, so an authorized scanner resolve, explicit scan or print can return500. Resolve and scan insert immutable `QrScanEvent` before rendering this target payload, so a failed request can also leave a scan behind. `operations/services_qr_assets.py::_target_label` has the same uncaught lookup when adding a stale QR to a print batch.

Bounded correction queued after current source freezes: tenant-qualified canonical target lookup returns deterministic404 for missing or foreign targets; resolve/scan validate it before any scan writes; print and batch labeling use the same boundary. Preserve existing valid payload shapes, durable historical QR/scans, explicit revocation behavior and native deletion eligibility. Do not automatically delete generic targets or historical QR rows. Prove actual native box deletion followed by each HTTP path, all three target kinds, foreign-target corruption refusal and zero new scan/batch/audit writes on failure.


## BOX-S04 — QR creation commits before its audit

`CreateBoxQrView.post` exits its box+QR `transaction.atomic()` before `audit.record`; `CreateToolQrView.post` uses `get_or_create` and then audit without any shared atomic block. The outer source-gate middleware holds an independent advisory boundary, not a Django request transaction; `ATOMIC_REQUESTS` is not configured. Audit insertion failure can therefore leave a successful new box/QR without its required audit, despite the API failing. Keep mutation and its real audit in the same transaction and test rollback through actual endpoints. Source-confirmed, runtime pending; no source fix yet.

## BOX-S05 — native box creation prints a code the scanner cannot resolve

`BoxAdmin` permits standard native add and only overrides display/readonly fields. `Box` has a generated `code` but no save override or QR signal; `BoxesConfig` registers no such receiver. Native creation therefore saves a Box without a matching `QrCode`. Its `qr_preview` prints `Box.code`, while every scanner resolves `QrCode.payload`; that native-created printed code returns404. API container creation and `CreateBoxQrView` create both records correctly. Native add must route through the same scoped/module/audited creation semantics, or explicitly refuse it and direct operators to the working console. Do not claim native flow success without an actual control-plane add→resolve regression.

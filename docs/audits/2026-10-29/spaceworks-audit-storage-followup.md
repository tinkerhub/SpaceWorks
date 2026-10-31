# Storage hardening follow-up — read-only source audit

2026-10-29, shared working tree after seven POST-to-staging changes. No edits to repository, tests, provider actions or environment mutations by this subagent. Parent owns Stage1/implementation/runtime verification. References below are current source lines, not runtime proof.

## 1. Public staging is reachable under the existing bucket policy

`docker-compose.yml:68` and `docker-compose.prod.yml:106` apply `mc anonymous set download` to the entire public-image bucket. All public POST/PUT policies now write `staging/<finalkey>` (`inventory/public_image_storage.py:241-268`; booking implementation parallels it). An anonymous GET of that staged object is therefore permitted by the provisioned policy before attachment/sniff validation. Object UUID secrecy is not an access policy.

### Actual final image namespaces

| Namespace | Owner/reference |
| --- | --- |
| `items/<makerspace_id>/<uuid>.<ext>` | Inventory builder, `public_image_storage.py:53-56`; admin product and bulk/control upload paths |
| `machine/<makerspace_id>/...` | Machine image presign, `admin_api/views_machine_image.py:58-62` |
| `makerspace/<makerspace_id>/...` | Logo/cover, `admin_api/views_makerspace_images.py:64-66` |
| `event/<makerspace_id>/...` | Event cover presign, `events/views_admin_image.py:59` |
| `member/<makerspace_id>/...` | Avatar/project, `makerspaces/profile_image_views.py:76`; `profile_images.py:1-4` |
| `printers/<makerspace_id>/...` | Legacy supported public image kind; retained builder allowlist `public_image_storage.py:54`; regression `test_put_finalize.py::test_public_image_post_finalize_retries_transient_missing_object` uses it |
| `spaces/<makerspace_id>/<space_id>/images/...` | Booking images, `bookings/storage.py:133-141` |
| `event-series/<makerspace_id>/...` | Intended series cover prefix, `events/views_series_image.py:22,47,68`; current builder rejects it (separate bug below) |
| `migrated-objects/<job_id>/<uuid>` | Collision-renamed imported public images, `tenant_migration/object_storage.py:110-118`; `object_fields.py` rewrites image/avatar/logo/cover fields |
| Arbitrary retained/imported/operator-selected keys | Tenant import preserves source key if free (`object_storage.py:110-112`). Organization.logo_key is a plain300-char field (`organizations/models.py:14`), editable by superuser `/control/` ModelAdmin (not in readonly fields `organizations/admin.py:53-60`), and public serializers construct URL directly (`serializers_public.py:27,45`). No organization upload builder or fixed organization prefix exists. Backup registry deliberately includes Organization.logo_key (`backup/object_ownership_registry.py:73`). |

Consequently a fixed current-prefix allowlist is incomplete: it can break legitimate migrated, legacy or organization images. There is no finite prefix catalog enforced for every public-image reference today. `events/` plural also appears in retained-object regression fixtures (`tests/backup/test_storage_versions.py:22`), while current Event writer uses singular `event/`.

### Minimal policy design

Retain anonymous `s3:GetObject` Allow on `arn:aws:s3:::<PUBLIC_IMAGE_BUCKET>/*`, and add a targeted Deny for `s3:GetObject` plus `s3:GetObjectVersion` on `arn:aws:s3:::<bucket>/staging/*`, conditioned on `StringEquals: {"aws:principaltype": "Anonymous"}`. The condition is essential: an unconditional staging Deny would override signed backend reads/copy source access. No anonymous bucket listing grant is necessary for public image URLs.

Primary source verification: MinIO's condition key is exactly `aws:principaltype` and its values distinguish Anonymous from signed users: https://github.com/minio/pkg/blob/main/policy/condition/keyname.go ; its server assigns the value from authenticated credentials: https://github.com/minio/minio/blob/master/cmd/bucket-policy.go . The repo's pgsty/silo fork has the same credential-derived values in https://github.com/pgsty/silo/blob/main/cmd/bucket-policy.go (`getConditionValuesWithTags`, lines178-185 and221). These are source confirmations, not proof of the pinned container image's effective policy.

Provision through one checked-in policy generator/file shared by dev/prod setup, substituting the actual configured public bucket; use `mc anonymous set-json` instead of `download`. Preserve separate private/public buckets and versioning. Verify on the actual pinned local object server: anonymous GET and HEAD staged=>403; anonymous version-id staged=>403; valid authenticated backend GET/HEAD/copy of staged succeeds; final keys under every ordinary namespace, booking, migrated-objects and arbitrary organization/legacy prefix remain anonymously readable. Include forged principaltype header/query attempts as negative checks. No anonymous list or private-bucket read should be added. Fresh uploads and upgrades of an already-created bucket must both apply the policy.

## 2. Promotion race: actual public entry points and existing locks

HEAD-then-COPY in the seven storage helpers does not itself provide destination create-once semantics. The relevant question is whether a caller already serializes one key **before** storage access.

| Caller | Actual boundary | Conclusion |
| --- | --- | --- |
| Evidence (control) | `evidence/finalization.py:79-103` briefly locks EvidencePhoto and EvidenceUploadFinalization, stores PROMOTING token; S3 outside transaction; completion reuses canonical state | Existing dedicated canonical finalization row/claim. Do not generalize this as an evidence race or remove it. `test_put_finalize.py::test_concurrent_post_finalization_promotes_exactly_once` covers evidence, not other seven helpers. |
| Staff machine-service attachment finalize | `admin_api/views_machine_service_files.py:123-129` calls `service_storage.finalize_file` without earlier lock. That function checks unattached snapshot, then S3 finalize and byte validation `service_storage.py:222-241`, only afterwards locks request/file `:243-246` | **Reachable duplicate-finalizer race.** ServiceRequestFile is the pre-existing canonical row, but has no promotion claim state. Late DB lock prevents duplicate attachment metadata but cannot undo an earlier S3 overwrite. |
| Public typed service submission | `machines/public_service_intake.py:45-65` locks makerspace and `lock_attachments` before calling finalize_file | Same-file submissions are already serialized by outer locks. This is not the unlocked staff race. Storage I/O under those locks is a separate invariant concern. |
| Public legacy printer submission | `machines/public_printer_service.py:121-141` locks makerspace, queue and staged files before finalize_file | Same conclusion as public typed intake. |
| Machine manual/SOP attach | `machines/services.py:202-215` atomic wrapper, duplicate query then finalize/validate before inserting MachineDocument; no parent row lock | **Reachable concurrent same-key finalize.** Unique document key prevents second insert, not second S3 copy. MachineDocument does not exist at presign time. |
| Maintenance log document | `maintenance/services_documents.py:12-30` locks machine then log before finalize; key restricted to exact machine `maintenance/storage.py:55-76` | Same-key/same-machine promotion is already serialized. Different machine cannot legally claim that key. Do not claim this as an exposed duplicate-finalizer race. Existing network-under-row-lock shape violates INVARIANTS:287 and needs deliberate boundary redesign if touched. |
| Warranty document | `warranty/views_documents.py:85-111` duplicate query, promotion/validation then insert, no lock/atomic boundary | **Reachable concurrent same-key finalize**, unique key stops duplicate row only. |
| Procurement receipt | `procurement/views_receipts.py:127-138` duplicate query and S3 promotion, then transaction only around receipt insert | **Reachable concurrent same-key finalize**, caught IntegrityError stops duplicate row only. |
| Inventory public image | `admin_api/views_inventory_images.py:89-108` finalizes/sniffs before product row lock | Same key can enter two promotions. Per-product lock is too late for S3 and does not serialize a key shared across different product IDs. |
| Machine/makerspace/event/series/member images | Respective view calls shared finalize before later service/holder locks (`views_machine_image.py:108`, `views_makerspace_images.py:123`, `events/views_admin_image.py:108`, `views_series_image.py:77`, `profile_image_views.py:121`) | Same promotion gap. Profile service lock protects its profile/project metadata afterwards, not S3. |
| Booking space image | `bookings/views_admin_spaces.py:256` finalizes before `services_images.set_space_image` later row lock `:75` | Same-holder duplicate promote is reachable. Key embeds spaceID, so cross-space reuse is rejected; distinguish it from tenant-only public-image prefixes. |

### Concrete staff service-file reproduction schedule

1. Owner has one still-valid staging upload and unattached ServiceRequestFile; submit two staff finalize requests with the same file ID.
2. Both read the unattached row and observe final missing. Pause B immediately before its COPY.
3. A copies original bytes, validates, attaches file and commits.
4. Replay the still-valid presign to staging with different valid bytes (same allowed MIME/size). Resume B.
5. B copies replacement over the accepted final, validates it, then its late request/file lock notices the file is already attached and refuses. Exception cleanup explicitly avoids deleting an already-attached file (`service_storage.py:269-274`), leaving the accepted final replaced while immutable file metadata still records A's size/content.

A unique row or late holder lock cannot prevent this schedule. Receipt/manual/warranty unique-key failure likewise occurs only after object promotion. An even simpler race can turn the losing finalizer's cleanup into deletion of a winner's still-uncommitted final; fix compensation along with publication ownership rather than only avoiding duplicate metadata.

### Bounded design recommendation

Do not move S3 beneath a holder `select_for_update` to fix this: `docs/INVARIANTS.md:287-294` explicitly forbids network I/O while holding row locks. The existing EvidenceUploadFinalization is evidence-specific (one-to-one EvidencePhoto), not a generic object journal that can simply be reused.

The smallest cross-helper storage fix is destination conditional create-once publication, followed by validation of the winner on conflict. Current AWS docs support destination `If-None-Match: *` for CopyObject/PutObject, returning412 when final already exists: https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html . **Do not confuse `CopySourceIfNoneMatch` with destination protection.** Repo boto3 lower bound1.36 and arbitrary S3-compatible deployments do not prove current CopyObject destination support. Validate the actual supported SDK model and pinned Silo server before using it. If conditional CopyObject unavailable, a bounded staged read/conditional PutObject is an established concrete alternative (MinIO primary test source: https://github.com/minio/minio/blob/master/cmd/erasure-object-conditional_test.go ). Preserve size limits/metadata, handle412 by reading existing final, and fail closed if conditional creation unsupported. Never fall back to unconditional copy after a conflict/error.

If storage-level conditionals cannot be guaranteed, a durable per-object claim with owner token/stale recovery is necessary, modeled on evidence. That requires an explicit schema/scope decision: only ServiceRequestFile is already a presign-time row; manuals/warranty/receipts/public images have no presign-time canonical object row. Avoid pretending per-holder locks are equivalent. A claim cannot be reclaimed while an old owner can still blindly overwrite; publication still needs fencing or conditional create.

Additional source concern: tenant-only image prefixes and per-holder metadata locks permit two different products/machines/events to pass `public_image_key_in_use` concurrently and claim one key. A shared DB key ownership boundary, or short common tenant lock covering final in-use check+attach (after S3, including self-host) would close that separate metadata race. This is distinct from publication; parent should decide whether it is in this hardening delta. Booking per-space key prefixes exclude cross-space reuse.

Tests needed: two real callers + deterministic barriers around missing-final check/copy; committed A, replay staging, B retry must preserve A bytes and one quota/attachment; concurrent same-key different-holder attach must yield one owner; failed loser cleanup must not delete winner; unsupported conditional capability must never copy unconditionally. Existing sequential POST/PUT tests alone do not cover these schedules.

## 3. Backup capture fallback currently masks non-missing final failures

`backup/storage.py:175-188::download_object` catches **every** BackupStorageError from `_download_object` and tries staging. `_download_object:236-275` wraps AccessDenied, timeouts, version-list failures, missing version IDs and streaming/local-file OSError in that same type. Therefore a readable staging replay can replace a present-but-unreadable authoritative final in a successful backup. Backup's content hash proves captured bytes, not that they are the right final bytes.

Minimal fail-closed rule: staging fallback only when final object absence is explicitly established. Introduce a narrow typed missing-object subclass/result; ordinary errors remain BackupStorageError and propagate. For versioned capture preserve retained-version behavior: HEAD404 -> list retained versions -> use newest exact-key version; only no current object **and** no retained version allows staging. HEAD success with missing VersionId, retained-version lookup error, or GET of a pinned final VersionId failing are integrity/storage failures, not permission to downgrade to staging. Unversioned GetObject404/NoSuchKey/NotFound can classify missing; 403/5xx/network/stream/local-I/O cannot. Existing `key.startswith(STAGING_PREFIX)` guard must continue preventing staging/staging fallback. Keep output record key as original final key for a genuine staged capture.

Focused regression expectations: final403 plus valid staging=>raise/no staged GET; final5xx/network/read OSError=>raise/no staging; versioned final HEAD missing but retained version exists=>pin retained version; no final/current/retained version + valid staging=>capture staging under final logical key; successful HEAD without VersionId=>raise; pinned final version vanishes=>raise; staging also missing=>fail; already-staging key=>no double fallback.

Existing source coverage: `tests/backup/test_storage_versions.py::test_versioned_capture_pins_retained_bytes_behind_a_delete_marker`; `tests/backup/test_evidence_retention_objects.py::test_expired_evidence_is_captured_as_intentional_absence`, `::test_expiring_evidence_refuses_backup_capture`, `::test_intentional_absence_requires_version_listing`. These do not exercise the non-missing-error fallback branch. No tests executed here.

## 4. Additional confirmed endpoint bug found while enumerating prefixes

`events/views_series_image.py:22` defines PREFIX=`event-series`; presign at47 passes it to `public_image_storage.build_object_key`, whose allowlist at54 omits it. A valid authorized EventSeries image presign raises ValueError before contacting storage, producing500. Minimal fix include intended kind, plus a real presign view regression. Existing event image tests concern `event/`; `tests/events/test_event_series.py` has no series-image presign coverage found in this bounded pass. This does not require a new bucket-policy prefix if targeted anonymous-staging denial is used.

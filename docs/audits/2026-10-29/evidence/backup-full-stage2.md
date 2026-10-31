# Signed full deployment backup — bounded Stage 2 handoff

Implemented from `/tmp/spaceworks-backup-full-stage2-prompt.txt`, the approved base
plan, both superseding deltas, and the three Stage 1 reviews (final review: APPROVED).
This is implementation and static inspection evidence, **not production-readiness or
runtime restore evidence**. Parent/root owns Stage 3 tests, Stage 4 review, final owner QA,
and any later staging/commit. Nothing was staged, committed, or pushed.

## Scope and design

- `full_capture.py` wraps the existing `CompoundCapture`. Selection happens in
  `prepare_from_snapshot`, inside `_snapshot_payload`'s exported REPEATABLE READ
  transaction used by the actual `pg_dump --snapshot`. Missing/divergent activation
  refuses; only every retained flag=True/state=ON permits full custody. Sovereign
  capture delegates to the existing B1 producer, projection and verifier unchanged.
- `full_population.py` freezes all retained makerspaces, their access/activation and
  lifecycle facts, the separate canonical servable cohort, predecessor success, and
  the related run's exact ID/holder/status/typed flags. Run relation caches are not
  trusted. Capture checks the fully-restored guard again inside the snapshot.
  No-run archives still freeze both populations.
- `full_manifest.py`, `full_manifest_validation.py`, and `full_format.py` introduce
  `spaceworks-deployment-full-v1` with its own length-framed Ed25519 domain. The
  signature binds the canonical complete manifest and the exact complete content
  ledger. Dump hash, database/server identity, capture UUID and an independently
  captured population/run/object-reference digest bind source provenance. All
  dump, continuity and live-object members are included; expired evidence remains
  a no-byte tombstone. The manifest contains no private signing key or raw
  continuity value. Real source hash and OCI identity are required, never invented.
- Full custody has no B1 partition proof, reservation, source projection catalog,
  reconstruction-pass claim or tenant user-closure proof. Its main semantic digest
  explicitly hashes full-format source facts. The independently frozen empty-slice
  closure digest exists solely for the existing common success audit contract.
  Common component fields retain their existing names, including
  `ciphertext_sha256` for the root dump component; this is not a new B1 proof.
- `manifest_dispatch.py` dispatches full and B1 verifiers explicitly at common
  ledger callers. Normal `verify_outer_manifest`, B1 signatures, protocol range,
  source verifier and proof allowlists were not edited by this work.
- `artifact_ledger.py`, `promotion.py`, and `promotion_validation.py` retain the
  existing durable staging/upload/readback/conditional-final/readback/publication
  protocol and reconciliation entry point. Full publication first takes
  `LOCK TABLE makerspaces_makerspace IN SHARE MODE`, then locks the related
  `BackupRun` with SELECT FOR UPDATE, then follows existing makerspace/recipient/
  activation/artifact/component/association/archive/settings ordering. The signed
  run binding and persisted archive binding must agree before archive row locks.
  Complete population, lifecycle, access, activation, servable cohort, run holder,
  permitted run status and exact typed flags are checked through commit. Run drift
  uses `ArtifactLedgerMismatch`, so reconciliation fails closed. No remote I/O was
  added to publication. Prior success is preserved on refusal.
- `full_bundle.py` checks signature, every tar member's type/name/size/hash, duplicate
  aliases, exact membership, embedded/extracted canonical manifest identity and
  exact continuity bytes. Extracted-root verification additionally rejects links,
  special files, unexpected files/directories and changed bytes. Source object
  paths are validated before full capture writes them to local disk.
- `import_preflight.py`, `full_preflight.py`, and `backup_preflight.py` validate
  exact continuity names/types, then apply the existing setting policies to a
  read-only prospective mapping: permitted continuity values from the verified
  payload, everything else from the target. Signature trust is always the current
  configured host key. Source/build, exact source/client/target PG major, runtime
  OCI, settings and object-storage capability must pass before host configuration
  effects. The import command and raw import service repeat admission against
  actual installed settings after recreation and before intent/registration.
  The raw service requires bundle/manifest/continuity inputs and adopts only the
  verified manifest; an unchecked manifest/digest call cannot register an archive.
- `backup_control_preflight.py` selects from registered archive identity and requires
  canonical manifest equality for signed full/B1 before proceeding. Removing or
  relabeling signature/format/protocol cannot select unsigned legacy. Full verifies
  both the tar and extracted root before advancing preflight, then uses the existing
  supervised full restore primitives. Only registered historical unsigned v1/v2/v3
  can use legacy compatibility; cross-host unsigned import stays refused.
- `request_restore` and both shipped import commands reject known B1, including
  partial=False, with `compound_host_unsupported` before recovery state, intent,
  audit, environment or service effects. Static B1 library admission remains
  available with `require_host_support=False` (the library default).
- Producer capability marker v2 explicitly requires
  `full_formats: ["spaceworks-deployment-full-v1"]`; v1/missing/malformed claims fail
  closed. Existing installed-script/entrypoint/migration hashes and private/public
  signing identity equality remain required before capture. The existing standalone
  installer calls the updated payload builder, so no separate installer change was
  needed. The new vocabulary module remains settings-free.
- `scripts/import-backup.sh` now invokes preflight with `backend --role management`.
  Its preflight still precedes `.env` copying/install, service recreation and import.
  `scripts/restore.sh` was inspected and left unchanged by this work.
- The three owned UI files distinguish signed full, B1 compound and historical
  legacy archives, hide unsupported restore controls and explain the reason.
  Disaster confirmation describes data replacement/authority reset; the all-table
  decision promise remains only on rollback. Mutation success says intent recorded,
  and both toast and pending-intent callout give the privileged host supervisor
  instruction with a validated UUID. TanStack Query still refreshes restore server
  state through the existing invalidation/polling keys.

No endpoint/response fields, models or migrations changed; existing manifest JSON
carries the format. No generated schema changes are necessary. No authorization
implementation was moved and no model was added, so authority-source/model registry
additions were unnecessary. No sourceprimitive scanner or ledger was edited; its
independent owner must refresh/review source attestation for these changed/new units.
Existing dirty edits were preserved, including the separate rollback-cleanup work.

## Independent verification performed

Each approved base point (1–6), first-delta point (1–5), its full-vs-B1 clarification,
and final-delta run-lock requirement was reconciled against the final source, not
only against the proposed interfaces. In particular, capture uses the same exported
snapshot; full has the complete payload ledger; the population fence precedes the
retained run lock and ordinary promotion locks; registered signed routing cannot
fall back to legacy; and both import entry points use installed-settings admission.

Static checks only:

- Python AST parsing passed for all 22 changed/new Python source files.
- A TypeScript compiler program with `noEmit: true` and no incremental output
  reported zero diagnostics across the existing frontend workspace. Parsing the
  three owned TS/TSX files also reported zero syntax diagnostics.
- `bash -n` passed for import and existing restore scripts.
- `git diff --check` passed; `diff CLAUDE.md AGENTS.md` was empty.
- Every touched source file is at most 300 lines (largest: existing import bundle
  helper, 288). Git's staged-file list was empty.
- Baseline-relative diffs were inspected to distinguish this implementation from
  pre-existing dirty changes; the source hash list below identifies final bytes.

No tests were written or run, no application imports/runtime were executed, and no
Docker, restart, migration, provider or production action was performed. No `.env`
or secret file was read. These checks do not establish PostgreSQL concurrency,
real encrypted restore correctness, host/provider compatibility, or UI runtime QA.

## Stage 3 tests parent/root must provide and run

1. Real full capture with zero, one and multiple all-ON retained makerspaces; archived
   vs servable cohorts; no-run and scheduled-run capture. Missing/divergent activation
   fails. Sovereign population delegates to actual B1 unchanged. Opaque not-restored
   state present in the exported snapshot refuses even if the earlier guard passed.
2. Prove the exact exported snapshot is supplied to actual pg_dump. Real age +
   pg_dump/pg_restore roundtrip, schema and rows compared to the snapshot, all object
   classes, continuity secrets and expired evidence tombstones included. A mocked
   dump is not acceptable restore evidence. Root controls all DB/age runtime.
3. Create/delete/access/activation/lifecycle/servable/run-cohort changes during dump
   or remote upload refuse publication. Independently frozen dump/source/ownership
   facts must not be replaceable by altered final manifest values. Recipient changes
   and predecessor changes refuse without changing prior last_success.
4. Separate PostgreSQL connections prove the makerspace SHARE fence blocks INSERT
   through commit; an insertion committed first causes refusal. A failed/replaced
   run refuses. A competing run failure waits on publication's SELECT FOR UPDATE;
   failure-first ordering is observed and refuses. Holder and exact typed flag
   mismatch (including noncanonical keys and bool-vs-int values) refuse. Verify lock
   order and no network/storage operation under publication locks.
5. Wrong/unpinned signer, missing signature, modified manifest or complete ledger,
   payload tampering in dump/keys/each object class, extra/missing files, duplicates
   and ./ aliases, traversal/absolute paths, links/devices/FIFOs and undeclared
   directories refuse before effects. Changed extracted manifest/keys/objects also
   refuse. Reject unknown/B1-only schema fields, invalid nested types and boolean
   substitutions in mirrored component facts. Cover provider Expires headers.
6. Registered signed full and B1 cannot downgrade by removing/relabeling
   format/protocol/signature; canonical registered/extracted mismatch refuses.
   Registered true unsigned v1/v2/v3 compatibility remains supported with its
   existing declaration/ledger rules. Unknown formats and unsigned cross-host import
   refuse. Direct raw import without authenticated bundle inputs creates nothing.
7. Same-host and cross-host prospective settings validate only exact permitted
   continuity names/types, never mutate os.environ, and retain target values for
   every other policy. Source verification key is externally pinned, never adopted
   from continuity. Non-continuity security/build/OCI/PG/storage mismatch refuses
   before effects. Import after recreation checks actual environment again before
   registration/intent, including a changed installed secret.
8. B1 partial=True and partial=False are refused by request_restore, preflight CLI,
   import CLI and raw import service with no restore/audit/state/env/service effects.
   Static B1 library validation remains usable for coordinator tests. Shell tests
   inspect exact `backend --role management python manage.py preflight_backup_import`
   argv and ordering; no real Docker/provider invocation in such tests.
9. Shared ledger tests cover every upload/crash/reconcile/cleanup boundary, immutable
   final verification, recipient-use retention and exact full source equality.
   Full run drift during reconciliation becomes a failed artifact, never available.
   Re-promoting an already available artifact remains idempotent after run completion.
10. Marker v2 explicit full claim, old marker refusal, bad claims, source script /
    entrypoint / migration drift, signing-private/public mismatch, and settings-free
    standalone installer import closure. UI tests cover format labels, unsupported
    controls, disaster vs rollback wording, intent toast/callout and safe UUID text.

After focused regressions, root must run the appropriate full backup/migration suite,
frontend checks, independent Stage 4 review and final owner QA. No skip/xfail should
replace missing real roundtrip or concurrency evidence.

## Operator wording root must merge into the permitted operator/invariant docs

> Deployment backups use signed `spaceworks-deployment-full-v1` only when every
> retained makerspace, including archived makerspaces, permits platform access and
> its activation is ON. Otherwise production remains B1 compound. The shipped host
> restore/import commands currently refuse B1 because no concrete sovereign host
> coordinator is shipped. A partial=False label does not make B1 a full restore.
>
> After installing these scripts/image, refresh the existing root-installed producer
> capability marker: version 2 must explicitly attest the full format and match the
> installed script, entrypoint, migration and signing identities. Old markers fail
> closed. Source build hash, OCI identity and supported PostgreSQL majors must be
> real compatible values; the producer never substitutes an unsigned fallback.
>
> Before cross-host import, pin the source archive verification public key through
> the target's trusted `BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY` host setting out of band.
> An archived key cannot establish trust, and continuity installation never sets the
> trust key or private signing key. Initial preflight checks a read-only prospective
> environment using only verified permitted continuity names; all other security
> settings, image/build, PostgreSQL and storage remain target-owned checks. Import
> repeats validation against actual installed settings after service recreation.
>
> A console restore request records an intent. A privileged operator must invoke
> `scripts/restore.sh <restore-uuid>` on the deployment host. Disaster restore replaces
> deployment data and resets authority into quarantine; only rollback provides the
> bounded all-table diff/decision flow. Downloaded copies remain outside purge
> guarantees.

## Limits / deferred work

The missing sovereign **concrete host coordinator remains a material production
limit**. This change does not invent a launcher/adapter or claim the whole backup
subsystem is ready. No implementation plan point was intentionally weakened or left
unimplemented in the bounded source correction. Runtime/roundtrip/concurrency tests,
sourceprimitive re-attestation, operator-document merging and final review/QA are
explicitly deferred to their owners under this Stage 2 prompt's constraints.

## Final source SHA-256

Hashes cover final complete source files, including preserved pre-existing edits.
The handoff itself is excluded to avoid a self-referential hash.

| Source | SHA-256 |
| --- | --- |
| `backend/apps/backup/archive_builder.py` | `3abe10119ab96994d687f1215a906ea8b850fdb25165dc05fb1945b78dedc46e` |
| `backend/apps/backup/archive_import.py` | `8e9cfe3571effb34923b2f387f8d235263f458bf93ed8ab2e253714572422cce` |
| `backend/apps/backup/archive_payload.py` | `c7d0a74b34a0bec7c293882f74c78d168f8855e261944c6a0e185331f80df3e6` |
| `backend/apps/backup/artifact_ledger.py` | `cff024075d94b85d23fcbbc85a5dffe06c99d1b8b27eb22760e0fb19f4252019` |
| `backend/apps/backup/backup_control_preflight.py` | `f0dc5f2ec2f862e0fc5a30da6d787a503b89776c3ce89ea9ed8dbbf4d90a184e` |
| `backend/apps/backup/full_bundle.py` | `62950632573274ad3ccc7f3e1d15cdecfb1cff62d4cf772588d1d83646ce1352` |
| `backend/apps/backup/full_capture.py` | `00d08c745dc1059e1a388b45e63bbd94c2105c1bdaff96fb65728e1e8907715f` |
| `backend/apps/backup/full_format.py` | `8d059952308193480ae5acb21625dbb9cd898c94a23f98f46567d9f7326743de` |
| `backend/apps/backup/full_manifest.py` | `9bbad1d57757d93fb48fad5c3c4f610d728f145e14f697c7f18b30b7b9b3a076` |
| `backend/apps/backup/full_manifest_validation.py` | `d545de6c4eee804fe5f9793a5929036c5e66025853665630f2152915605f1810` |
| `backend/apps/backup/full_population.py` | `1603afce74c8885e3c7c5608a69bc46b90197764347610af9e16a36a93405732` |
| `backend/apps/backup/full_preflight.py` | `82e70b9752199a5751c8b17a1c50b1f143bdaad2bdd052858a83295244c17d19` |
| `backend/apps/backup/import_preflight.py` | `0199a23d3205e18e2f9ae383f241984cbaa880669b691ba4f84176724cf64332` |
| `backend/apps/backup/import_preflight_bundle.py` | `7b02c891d4f39c4528c959bd68223ea6b54f2255601f75fee6183ed0beec0d1e` |
| `backend/apps/backup/management/commands/backup_preflight.py` | `8bdd5a637c7fd48d9f0b469e6ced01919955a7499594909e153dda234e9f5cfd` |
| `backend/apps/backup/management/commands/import_backup_archive.py` | `16d600aa6dced932c96b86e03814d0565a35b3690315a281050c3be2f0b0c53b` |
| `backend/apps/backup/management/commands/preflight_backup_import.py` | `773461282c8eb65b444d0a7df1616b8d20be7d7e49d0dfe6cbe2f803bd198fa4` |
| `backend/apps/backup/manifest_dispatch.py` | `2dee80dc57fc3f8c287c0ce25137bfb15c89aafe692280174cc49fa049e9f191` |
| `backend/apps/backup/producer_capability.py` | `e5d9b126319b668979e645b2ab57f36581461f55a08d486f1db3fb4588b08f05` |
| `backend/apps/backup/promotion.py` | `b57a66a2cc13647db12f5d928aad34638108d13b485d1ed0280722a25e3b466b` |
| `backend/apps/backup/promotion_validation.py` | `66b6fc1b8f9670c30ffe4172acab406eda0aff70cba40b0a3cad80ce063da1a0` |
| `backend/apps/backup/restore_services.py` | `9577490a0897d2628e08594c9dc59b435dbdba23f7a9061f594a6f191a40e1d2` |
| `frontend/src/features/staff/BackupArchiveTable.tsx` | `c7a772d8976a14a23a33040f501b0602fe0498609d81691ae1c2c23525fe0da5` |
| `frontend/src/features/staff/BackupRestorePanel.tsx` | `394fc0176b7aa94d634f3d53f7dab90e8d3f1d0f5f60656b6afc8afcf5facd96` |
| `frontend/src/features/staff/backupApi.ts` | `3c99ae2ac2ed0d54cff94a010848bf1464c6fcb33de0d0c00ca92e022ba7ca2e` |
| `scripts/import-backup.sh` | `c484a85534875c161e9b939fdff89e9d1a5b4b1fda70119e73828d52647525b0` |

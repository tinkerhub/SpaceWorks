# Signed full backup — bounded Stage 3 test-writing handoff

Written against `/tmp/spaceworks-backup-full-stage3-prompt.txt`, the approved signed-full plan and both deltas, Stage 2 handoff, operational follow-up/deltas, and the final identity-companion/selected-archive corrections in the prompt. Current production interfaces were read before tests were written.

**No tests were run or collected. No application imports, Docker, database commands, migrations, network actions, staging, commits or pushes were performed.** Static source parsing, file inspection, hashing and scoped whitespace checks are the only verification in this handoff. Node counts below are static parameter expansions, never pass counts. Parent/root owns runtime, review, fixes and QA. This does not establish production readiness; the concrete sovereign host coordinator remains absent.

## Changes and boundaries

Added 16 backend test modules (78 test functions, **223 statically expanded nodes**), nine bounded helpers, and one frontend module (four parameterized test definitions, **14 static nodes**). Three legacy files have surgical contract/fixture adapters; their complete files contain 13 static nodes. Every owned Python file is at most 300 lines; new test/helper files remain below 210 lines. No production source or other documentation was edited.

All 34 paths in `backup-full-source-freeze.json` matched their recorded SHA-256 at final static inspection. Other dirty sources/tests, frontend auth/session work, rollback cleanup/progress, X13 tests and the pre-existing fixture edits were preserved. The two independently written runtime-login files observed during this turn were read and left untouched; they are identified separately below.

## Meaningful coverage

- Separate Ed25519 full domain with real host test keys, actual B1 signature transplantation, external trust-key mismatch, signature algorithm/shape/bytes, closed schema, UUID/quantity booleans, exact operational omission registry, source dump binding and every complete-ledger payload class. Helpers call the production builder/validators and never patch schema, crypto or source/role guards.
- Actual `DeploymentCapture` selection in exported repeatable-read snapshots: zero/one/multiple retained spaces, archived consent, actual compound delegate selection, missing/divergent activation, servable-only scheduled cohort, exact typed flags, holder and binding, immutable source references and late preparation refusal. Synthetic unit dumps are labeled as such and are not restore evidence.
- Real tar/extracted validators: dump/continuity/private/public-image tamper or omission, extras, duplicate and `./` aliases, traversal/noncanonical paths, exact case, tar symbolic/hard links/special files, extracted links and extra directories/files, changed extracted manifest, same JSON with different continuity bytes, duplicate JSON keys, expired no-byte evidence and hardlinked extracted payloads.
- Raw import requires authenticated bundle inputs and repeats installed settings admission. Real full signature/ledger/settings policies exercise read-only prospective continuity, target-owned noncontinuity security settings, build/PG/OCI/storage refusal, exact continuity names/types, registered full/B1 downgrade refusal, historical legacy routing, active eligible import principal, no premature state/audit/upload and successful intent/audit recording. Full supervised preflight has a positive distinct-token path and stage/state/audit refusal checks.
- Shared durable upload, real stream verification and create-only final code over an in-memory S3 transport: remote calls assert no surrounding database transaction; crash boundaries, conditional-final conflict, verified-final reconciliation, corrupt final refusal, retry/cleanup, recipient-custody retention, prior success and failed-run reconciliation. Full publication compares complete retained/servable/lifecycle/activation/run facts and the independently frozen source digest. Available artifacts remain idempotent after scheduled run completion.
- Four real separate-connection PostgreSQL races use `pg_blocking_pids` barriers: population SHARE blocks INSERT through commit; insertion committed first refuses; the actual run failure service waits for publication's run lock; failure owns the lock first, then promotion observes failure and refuses. No sleep-only race inference.
- Two real pg_dump → age → decrypted tar → pg_restore scratch roundtrips, parameterized over NORMAL and ACKNOWLEDGED_NORMAL. These use matching local PostgreSQL binaries and the configured real local S3/MinIO client, including private evidence, a public image and provider Expires headers. A separately committed row update before the real dump proves exported-snapshot bytes. Exact operational schemas survive with zero rows; source identity/receipts remain. Continuity bytes, source dump digest, target UUID/lineage/timestamp, mismatched physical target, unexpected source row, real fixed-bootstrap role/grant transaction rollback, unchanged root marker and actual readiness are asserted. BUILD/OCI metadata in these tests is explicitly synthetic fixture metadata; this is not deployed-image attestation.
- An additional real restricted-role identity regression uses NOCREATEDB/NOSUPERUSER/NOINHERIT and no pg_monitor membership, proves pg_control_system permission denial, then calls the production source identity helper and verifies the transaction remains usable. No elevated app grant is added. The independent parent's exact runtime-login roundtrip supplements this path.
- Target control grammar, oversize identity input, missing/malformed/mismatched facts, ready-state policy, intent/candidate/quarantine rejection, optional system corroboration, large report export with a separately bounded mode0600/fsynced companion, selected archive identity/tamper/changed-valid-manifest rejection, available SHA/size/locator/dates restoration, download-token reset and a valid second export.
- Real copied import/restore shell scripts in a temporary Linux deployment with deterministic compose/docker transports. They inspect management-role argv, preflight-before-env/service/intent effects, recreation-before-installed import, two admitted preflights, changed-token refusal and identity-only fixed bootstrap before any postreplacement Django management. These transports never invoke Docker; Python tests separately exercise actual admission. Frontend tests cover supported full/historical legacy vs B1 (including partial=false)/unknown, retained download, confirmation copy, recorded intent, privileged supervisor instruction and unsafe UUID fallback.

## Static findings the parent must resolve or confirm

Two strict regressions appear likely to fail against the frozen source; neither is skipped or weakened:

1. `test_import_command_requires_active_eligible_superadmin_before_upload` includes inactive and suspended superadmins. The current import command checks superadmin identity but does not visibly enforce `is_active`/`access_status` before upload and intent. Parent must run and assess this boundary, then own any production correction and renewed freeze/review.
2. `test_extracted_hardlinked_payload_refuses_even_when_bytes_match` expects extracted hard links to be refused. The current root verifier checks symlinks/file bytes but does not visibly inspect hard-link count. Parent must resolve the required extracted-file policy and the production guard; a tar hard-link entry is already separately refused.

These are source-inspection observations, **not observed runtime failures**. Missing clients, age, local object storage, CREATEROLE/CREATEDB authority or Linux host semantics must be reported as environment blockers, not converted to skips/xfails or assertion weakening. Exact runtime outcomes, collection/import compatibility and frontend compilation remain unverified here.

## Legacy fixture adapters

- `test_archive_digests.py`: `_manifest` now registers the exact constructed historical manifest on the archive row. Its v1 success and altered-ledger refusal therefore reach the intended legacy validator instead of failing on an empty registered identity. The raw-import digest negative now supplies a real signed-full fixture plus bundle/manifest/continuity inputs; it still requires digest refusal before any upload/registration. The message follows the new `outer_digest_mismatch` admission reason. File remains below 300 lines.
- `test_archive_manifest_v3.py`: likewise registers the same historical v2/v3 manifest before preflight. The unsigned partial-looking negative still refuses, now at `format_unsupported`; it cannot claim an installed compound host handoff. Signed registered downgrade negatives are covered separately in new tests.
- `test_import_preflight_commands.py`: malformed B1 input now explicitly expects the shipped CLI's earlier `compound_host_unsupported` refusal from both commands, preserving no-registration/no-intent assertions. Existing static-library success, digest computation and malformed-member tests remain available. The already-dirty `host_restore_gate` structured expectation was preserved; it was not authored by this turn.

No fixture disables real immutability, receipt schema, signing or runtime-role guards. No existing oversized test was expanded.

## Exact static inventory

Counts are determined from Python AST function/decorator literals; stacked parameter sets multiply. Frontend arrays expand to 4 + 6 + 2 + 2 nodes by source inspection. Pytest/Vitest collection was not invoked.

| Test file | Definitions | Static nodes | Lines |
| --- | ---: | ---: | ---: |
| `backend/tests/backup/test_signed_full_admission.py` | 8 | 17 | 157 |
| `backend/tests/backup/test_signed_full_bootstrap.py` | 2 | 5 | 30 |
| `backend/tests/backup/test_signed_full_bundle.py` | 10 | 38 | 143 |
| `backend/tests/backup/test_signed_full_capability.py` | 3 | 9 | 52 |
| `backend/tests/backup/test_signed_full_capture.py` | 8 | 15 | 147 |
| `backend/tests/backup/test_signed_full_concurrency.py` | 4 | 4 | 105 |
| `backend/tests/backup/test_signed_full_control.py` | 4 | 12 | 132 |
| `backend/tests/backup/test_signed_full_host.py` | 4 | 6 | 77 |
| `backend/tests/backup/test_signed_full_identity.py` | 6 | 22 | 122 |
| `backend/tests/backup/test_signed_full_least_privilege.py` | 1 | 1 | 50 |
| `backend/tests/backup/test_signed_full_manifest.py` | 10 | 45 | 138 |
| `backend/tests/backup/test_signed_full_preflight.py` | 4 | 16 | 92 |
| `backend/tests/backup/test_signed_full_promotion.py` | 5 | 16 | 118 |
| `backend/tests/backup/test_signed_full_restore_preflight.py` | 2 | 6 | 72 |
| `backend/tests/backup/test_signed_full_roundtrip.py` | 1 | 2 | 198 |
| `backend/tests/backup/test_signed_full_upload.py` | 6 | 9 | 103 |
| `frontend/src/features/staff/BackupArchiveFormat.test.tsx` | 4 | 14 | 109 |
| `backend/tests/backup/test_archive_digests.py` | 5 | 5 | 294 |
| `backend/tests/backup/test_archive_manifest_v3.py` | 4 | 5 | 212 |
| `backend/tests/backup/test_import_preflight_commands.py` | 3 | 3 | 114 |

## Root commands — execute sequentially from repository root

These commands are instructions for the parent, not executed evidence. Use only the disposable local stack and never run two pytest processes on the same database. The owner DATABASE_URL is required for pytest database creation; the real role tests additionally require owner CREATEROLE. PostgreSQL clients must match server major 16, age/age-keygen must exist, and both local MinIO buckets must be usable/versionable. Do not run the host and Docker app stacks together.

Core validators/services plus narrow historical adapters (no shell-script lane or real binary roundtrip lane):

```bash
./scripts/dev-docker.sh exec -T backend sh -c '
  export DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager
  export API_CLIENT_ENC_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  python -m pytest -q --create-db \
    tests/backup/test_signed_full_manifest.py \
    tests/backup/test_signed_full_bundle.py \
    tests/backup/test_signed_full_capability.py \
    tests/backup/test_signed_full_bootstrap.py \
    tests/backup/test_signed_full_capture.py \
    tests/backup/test_signed_full_preflight.py \
    tests/backup/test_signed_full_admission.py \
    tests/backup/test_signed_full_restore_preflight.py \
    tests/backup/test_signed_full_promotion.py \
    tests/backup/test_signed_full_upload.py \
    tests/backup/test_signed_full_identity.py \
    tests/backup/test_signed_full_control.py \
    tests/backup/test_archive_digests.py \
    tests/backup/test_archive_manifest_v3.py \
    tests/backup/test_import_preflight_commands.py \
    tests/backup/test_import_preflight_refusals.py \
    tests/backup/test_producer_capability_gate_p1.py
'
```

Real separate-connection races, least-privilege identity and pg_dump/age/pg_restore/local-object proof lane. The last file is the independently authored parent supplement; it performs a whole capture and restore as the exact non-owner runtime login.

```bash
./scripts/dev-docker.sh exec -T backend sh -c '
  export DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager
  export API_CLIENT_ENC_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  python -m pytest -q --create-db \
    tests/backup/test_signed_full_concurrency.py \
    tests/backup/test_signed_full_least_privilege.py \
    tests/backup/test_signed_full_roundtrip.py \
    tests/backup/test_signed_full_runtime_role_exact.py
'
```

Linux host-script lane needs the **whole checkout mounted**, because an ordinary backend-only bind mount makes repository-root script paths resolve outside the checkout. Native macOS does not supply the required Linux flock/sync semantics; the tests assert Linux instead of skipping. The copied scripts use fake transports and cannot start real Docker/services.

```bash
./scripts/dev-docker.sh run --rm --no-deps -T \
  -v "$PWD:/workspace" -w /workspace/backend \
  backend --role management sh -c '
    export DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager
    export API_CLIENT_ENC_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
    python -m pytest -q tests/backup/test_signed_full_host.py
  '
```

Frontend focused test on Node 20 with an isolated dependency volume:

```bash
docker run --rm -v "$PWD/frontend:/app" \
  -v spaceworks-node20-test-deps:/app/node_modules -w /app node:20 sh -c \
  'npm ci && npx vitest run src/features/staff/BackupArchiveFormat.test.tsx'
```

After resolving focused findings, parent owns the full backup/tenant-migration suite, full frontend checks, host-only existing test split, independent Stage 4 review, refreshed source attestation/freeze and final owner QA. Do not infer any passing result from this handoff. The existing `test_host_orchestration_surface_h1a.py` and `test_host_update_boundary.py` still require the documented host-checkout topology.

```bash
./scripts/dev-docker.sh exec -T backend sh -c '
  export DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager
  export API_CLIENT_ENC_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  python -m pytest -q --create-db tests/backup tests/tenant_migration \
    --ignore=tests/backup/test_signed_full_host.py \
    --ignore=tests/backup/test_host_orchestration_surface_h1a.py \
    --ignore=tests/backup/test_host_update_boundary.py
'
docker run --rm -v "$PWD/frontend:/app" \
  -v spaceworks-node20-test-deps:/app/node_modules -w /app node:20 sh -c \
  'npm ci && npx tsc -b && npm test && npm run build'
diff CLAUDE.md AGENTS.md
```

## Final SHA-256 of owned test and helper files

Hashes cover complete final bytes, including preserved pre-existing changes in the adapted command-test file. This document is excluded from its own table to avoid a self-referential hash.

| File | SHA-256 |
| --- | --- |
| `backend/tests/backup/full_backup_bootstrap_helpers.py` | `8599ec55e8b2c7e6f2efb55bb9f2daea775141a0a4b3ef1945eed8e2219bd015` |
| `backend/tests/backup/full_backup_capture_helpers.py` | `be60719239b950fe01dee50c50035e4e8593787416dc6bbe551b43c1175cbad5` |
| `backend/tests/backup/full_backup_fixture_helpers.py` | `6249ff11c60af5c9b6457e541b2e2ee47e9cff5a36b5425329e9271ddcdfc39f` |
| `backend/tests/backup/full_backup_host_helpers.py` | `eab3165c4b094290ac68057237cb60067174502835d937d7a209c2328bb0639d` |
| `backend/tests/backup/full_backup_identity_helpers.py` | `26793c92f5fe6fdf7a2e96f8e08257ad5a20382949ab345321508e43df1e920f` |
| `backend/tests/backup/full_backup_preflight_helpers.py` | `ebbc2353acd43d93b5bd50673d880132920c49bfd192b3b5fbde6cfa9467f2e7` |
| `backend/tests/backup/full_backup_race_helpers.py` | `f0e4e31b85871b1b54e0cbaed232effa4f2ef47a1cb767c8f4661a9eb784b969` |
| `backend/tests/backup/full_backup_roundtrip_helpers.py` | `4f3f5a2d21650884bcb728f1c802f20eac26d87455b40b075647c65b352b3a9e` |
| `backend/tests/backup/full_backup_storage_helpers.py` | `6af8ca3c3d7f56404c30cd020620f38223237d5b1f2f9f56d621404ecb2e73a9` |
| `backend/tests/backup/test_signed_full_admission.py` | `4b0a10e516321e7877e516ef9254ad3290a8b1cd76f3d85ce56784d8bc11584e` |
| `backend/tests/backup/test_signed_full_bootstrap.py` | `ba5a7888b39d07aff3170c80e3f53351dd93924b45f3be0493415df0574b1d53` |
| `backend/tests/backup/test_signed_full_bundle.py` | `660b892d7ceb24ad8f562911636ba71511fa956d0716c91eb520e7950e8d25eb` |
| `backend/tests/backup/test_signed_full_capability.py` | `3e8b9f321ad3f7a30b25b742d39abd95fc84c0a6ec4a4a7a028e3df54496d5ca` |
| `backend/tests/backup/test_signed_full_capture.py` | `5adc62ee7b2e42d9ddaad07552a16aa1bb2d4378fcb36215f740be6690e5410c` |
| `backend/tests/backup/test_signed_full_concurrency.py` | `58955511c7f483407ba1ddf346effb9ebbbd7d794e6bb093654cfcf161631097` |
| `backend/tests/backup/test_signed_full_control.py` | `17a8bf4210231942b27bd25debfd742d81f93c045a9c1b2be84930019ad5b618` |
| `backend/tests/backup/test_signed_full_host.py` | `cd81d6766a5170e3da6c3c12d3c0cf5da8d40bb67751f3a6613e61c6527df804` |
| `backend/tests/backup/test_signed_full_identity.py` | `0f62eebdcbe0ad135561f09b962b78ca47760ff938c5f8c43a32fe2f656df7c7` |
| `backend/tests/backup/test_signed_full_least_privilege.py` | `eae989950bf2110f62ea1ecc6b506028a242cca61ee37260321aabdf72f598ab` |
| `backend/tests/backup/test_signed_full_manifest.py` | `5e635e06c00312d58684d544461dcaf082d69f44257d213306be7c195b59fd87` |
| `backend/tests/backup/test_signed_full_preflight.py` | `30fa13b374c0f7c6b3c25972361cdfc22619895c0a045286a1bfbe608931bdc0` |
| `backend/tests/backup/test_signed_full_promotion.py` | `2ce628039c6fb0e183ee07c5f2d765ff9bb182c1e60f54ad5ac4588b06cb0596` |
| `backend/tests/backup/test_signed_full_restore_preflight.py` | `b9a8dd1263bd892071c1ef0e53196c6c322f38c73a5a56f6427119fea445b8b1` |
| `backend/tests/backup/test_signed_full_roundtrip.py` | `bd7997cc3b3422c45f4b2b4fc0d6ac84bd5a6c74198517bf076366a8ceb6aa8c` |
| `backend/tests/backup/test_signed_full_upload.py` | `1c4bd72462c5b97563937afe2986c67b5fb999cad51b30b223c9594a4fb65941` |
| `backend/tests/backup/test_archive_digests.py` | `fc9f6bdfb678741282a07d9dae37d72770bbdb2197f32f6d009c2cc1248d0bcf` |
| `backend/tests/backup/test_archive_manifest_v3.py` | `7f3a3bdd46e6ae8b8055118e0b945ae6a3aade39dac2c3cf33f1eb84aa5e9676` |
| `backend/tests/backup/test_import_preflight_commands.py` | `0b47063daf82ab6cfd3e94c8ec5b16b73cb2e2a6741bdce608e671e68825ee25` |
| `frontend/src/features/staff/BackupArchiveFormat.test.tsx` | `c5933823bc84b59fda49f185cbd2f047091f1598db4c39b2b71e939f3559da38` |

## Independently authored parent supplement — observed, not edited

These appeared in the shared workspace during this task. They contribute one additional static backend test node and use the helper interfaces above. They were statically parsed/read only; their authorship and any future changes remain the parent's responsibility.

| File | Static nodes | SHA-256 at handoff |
| --- | ---: | --- |
| `backend/tests/backup/full_backup_runtime_role_exact_helpers.py` | 0 | `ce86173851f25c9467335a70fc662be125a27480721ed28e5e79859dcf822257` |
| `backend/tests/backup/test_signed_full_runtime_role_exact.py` | 1 | `c0d7dc4e9397d78de68e92ca93a277292704abe01b9b39215d2a2a4b5a43216d` |

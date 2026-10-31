# Recovery Stage3 test-writing handoff

2026-10-30. Separate Stage3 executor for the approved source-only recovery, trusted import and installed bundle group. **Tests written, not run. This is not deployment certification.** Parent owns execution, Stage4 review and owner QA. No staging/commit/push, production-source/shared-doc changes, original signed-full test changes, conftest/task_gate/parent-guard edits, or runtime/drill occurred in this lane.

Read AGENTS/global CLAUDE workflow, DEV-WORKFLOW, relevant backup/container invariants, the recovery plan and both superseding deltas, final-corrections plan/delta, packaging plan, approval reports and Stage2/independent-correction reports. This writing invocation is the separate Stage3 handoff; the explicit user restriction defers the workflow's runtime step to the parent. No extra CLI, doctor, test collection, application import, Django setup, Docker, DB, migrations or build was invoked.

## Static evidence and source scope

- New files: **20 test modules + 8 private helpers, 2,857 lines**, maximum file 198 lines. All parsed as AST data; no modules imported. No skip/xfail. Raw whitespace/final-newline checks passed.
- `bash -n` only: five private shell transport/harness snippets, and existing restore.sh, import-backup.sh, install-host-bundle.sh, install.sh. No checker/guard/wrapper/helper was executed, including help.
- Embedded guard AST/data check: exact 25 dependency paths and SHA256 values match. Final 60 source entries and all 59 copied-file entries match current authoritative source freeze. AGENTS/CLAUDE remain byte-identical. Scoped whitespace/index reads only; index remains empty.
- Initial source-freeze hash was `ae0b33b91984817085ab414254d3ce3be7970b90c2c4ba921a5ad1cb07591c76`. During writing three Compose sources briefly differed. A concurrent refresh reconciled their source/copy entries; Compose-refresh source-freeze hash was `6b1602b7237921e5386cdc089e8a099db0ef28480b707ff65d70d483efb76f97`; the independently corrected path-conflict source freeze now has hash `47d6ece60b36f5ba67409ae8aecef9417e6000aa2c2377865b9974166dec8148`. This executor changed neither those sources nor their freeze. Historical freezes were not edited here.
- New test freeze: `recovery-tests-freeze.json`, SHA256 **4c415da2ed88e649d77ba751ba7002028d614f9772261da74b5da7b520848c23**. It freezes every new Python test/helper path and records the source revision/static scope. This report is its explanatory companion, not a runtime attestation.

## Behavior covered by written tests

| Area | Actual behavior and limits |
| --- | --- |
| Controller/lock | main() encloses admission, inputs and terminal dispatch in actual host_operation_lock. Separate child flock contends; root-owned0666 inode accepted. Real fd identity/link/owner drift refusals. RestoreTransport.execute and fixed recover-principal child close even deliberately inheritable authority FDs. Actual nobody process refuses root lock/controller; protected compound target refuses before admission. Existing negative cleanup dispatcher guards remain untouched. |
| Root lifecycle | Actual marker/pointer/capability journal/RunLedger helpers; ordered operation/config/topology/pointer/target proofs; management-only block, backend-only quarantine, ack-normal, failed launch reblock; missing/unfinished/misordered root receipts refuse. Actual recovered-principal DB service and fresh fixed SQL proof drive root acknowledgement; API acknowledgement alone leaves host marker quarantined. |
| Tasks/queue | Actual TenantGateTask and real DB state reads before resolver/effects for normal, exempt and internal names; missing/read-error/unknown/non-normal deny without synthesizing NORMAL. Actual fail management command preserves mode/active operation. Canonical generation, blank legacy queue, memory-transport retry/beat publication, target-only continuity exclusion; live child workers additionally verify actual Django queue/exchange/routing settings. |
| Input admission | Actual RestoreInputs and real sealed plain tar. Registered describe/UUID/scope/protocol/exact boolean/stored hash precede export/decrypt/parsing. Changed outer hash or forged metadata prevents full extraction. Real externally configured Ed25519 signature and full tar ledger precede full extraction; synthetic age bytes/SQL are explicitly labeled. Registered disaster forwards canonical restore UUID to real root delegation; initial import omits it. Rollback remains strict installed-key admission. Actual import command/services register/audit under OLD env only after static proof, before any provider mutation; stored principal eligibility runs. |
| Tar/caps | Actual file screening/projection/extraction: genuine producer PAX including harmless sparse-looking long path values, length framing, malformed/truncated/nested/global/sparse headers, links/specials, duplicates/unsafe paths and file/ancestor conflicts in both orders, valid explicit/implied directories, negative/out-of-file extents, compression, physical PAX cap, real64MiB/1MiB serialized metadata cap and cap+1. Sparse disk fixtures avoid allocating huge tar payload buffers. Actual builder file-size guard executes before encryption/publication, with small boundary caps; real recovery/capability checks retained and original producer ACL restored locally. |
| Configuration/failures | Actual InplaceRestore constructor/decision/dump/restore/retain_failure/abort and ConfigurationTransition, with genuine marker/ledger/env files. Synthetic Docker/SQL/provider responses exercise OLD stop before env, strict NEW admission before SQL, source closure before new copies, no old-env or SQL rollback, retained copies/current env, stop writers after injected control/SQL/grant/journal/ledger/marker/config/launch faults and cancellation. Exact old proof is required for harmless abort. Synthetic success reaches backend-only quarantine; fresh resume reloads original private Redis receipt and requires exact ack/config/phase bindings. These are ordering/failure tests, not host attestation or a real SQL diff/restore. |
| Redis admission | Actual configuration/inventory validator over synthetic read-only Docker responses. Only redis:7-alpine with exact declared/data shape and one local RW64lowerhex actual volume accepted; name/backing/options/driver/scope/bind/extra mount/image changes refused. Fresh transport reads actual root-private admission-old.json and binds original identity. No volume create/migrate/purge. Unknown/candidate/duplicate/one-off writers and command/env/image/mount drift, DB endpoint/table identity disagreement and unexplained sessions refuse. |
| Object closure | Actual DB ownership scanner, object apply, root block, complete private journal/row proofs. Archived rollback copies remain source checked; only exact current operation row/site/outcomes can be extras. Unknown prefix/current-model extra refs refuse before new effects. Synthetic S3 wire exercises streamed size/SHA/metadata/type/headers and stream closing; expired final+staging retained history refuses. Separate actual S3 tests use a uniquely created disposable bucket for GET/header/history/delete-marker proof. No source-signature claim is attached to local recovery copies. |
| Installed layout | Actual bounded installer copies the exact59-file snapshot, verifies each25-dependency failure plus checker/original fixed entries structurally before any target replacement/backup creation, retains private env/keys/ops/data/backups and previous wrapper, rejects malformed guard contract. Actual root-owned copied shell -> isolated Python help, missing.env no-effects refusal, valid poisoned bytecode ignored/no cache writes, ownership/link/nonregular/writable ancestry denial, actual nobody refusal. Actual fresh installer extraction/checker/move and UID0/nobody ownership modes execute under synthetic download/Docker/setup transport. Parsing/layout only; setup/host restore not certified. |
| Live broker | Separate slow file starts actual private Celery solo worker processes, uses real Redis messages/retry/ETA/late-unacked crash, and real committed reused EmailLog ID with distinct replacement identity. Real normal-state Task fence blocks under quarantine; new default/retry/beat execute only against replacement identity/new queue. Old IDs must remain in old queue/unacked storage; no purge/delete is performed. Generation/row replacement is a test simulation, not pg_restore or a host restore drill. |

## Parent command matrix — not executed

Run sequentially in the parent's disposable Linux UID0 backend environment with full checkout mounted at `/repo` and working directory `/repo/backend`. Use the already assigned dedicated PostgreSQL test DB owner URL and the same valid API_CLIENT_ENC_KEY, PII/audit keys and test settings as the parent. Never run a second pytest process against that DB. Set:

```sh
cd /repo/backend
export SPACEWORKS_TEST_REPO_ROOT=/repo
export PYTHONDONTWRITEBYTECODE=1
```

The helper validates an explicit root and never silently accepts `/`; backend-only mounts need `/repo`. Commands below use `--reuse-db` to reuse the parent's dedicated DB, not create a second test runner. No command below was executed in Stage3. No xdist/parallel runs. Private-namespace tests need a fresh disposable container with **no** `/run/spaceworks-host` mount/path; they refuse an existing authority directory rather than delete/reuse it.

| Lane | Prerequisites |
| --- | --- |
| Fast pure | Linux UID0, protected pytest temp ancestry, full checkout, ordinary backend test dependencies. No DB/broker/S3 actions in test bodies. Real64MiB metadata cap case can write64MiB private projection; allow disk/memory headroom. |
| DB | Dedicated PostgreSQL owner/test DB and parent encryption keys; transactional cases exercise real commit/constraints. No triggers or immutable guards disabled. Producer cap case restores actual producer ACL over the existing capability fixture. |
| Private import | Above plus SPACEWORKS_TEST_PRIVATE_HOST_STATE=1 in a fresh disposable container; fixed /run authority namespace must not exist. These tests model the real readonly Docker mount with real root0444 delegation bytes, without patching its validator. |
| Root installed | Linux UID0, /tmp root-owned1777, readable full checkout/current source freeze, bash/python3/tar/id. Fresh-install synthetic harness needs no listeners on80/9000/9001 and supported Linux distribution metadata; uses private PTY, actual nobody IDs, no sudo/network/daemon. |
| S3 | Explicit disposable local MinIO endpoint/credentials in Django settings and SPACEWORKS_TEST_S3_DISPOSABLE=1. Unique bucket only; no implicit AWS endpoint. |
| Live broker | Dedicated Redis service or DB explicitly owned by this proof, URL plus confirmation flag, exact effective pytest DB name, TCP PG endpoint, full repo, redis/Celery packages; permission to start/kill private child process groups. No external worker/beat on its prefix. Old queue data intentionally retained. |

Fast pure (excludes live broker, S3, private namespace and DB files):

```sh
python -m pytest -q --reuse-db \
  tests/backup/test_recovery_queue_and_command.py \
  tests/backup/test_recovery_tar_screen.py \
  tests/backup/test_recovery_marker_authority.py \
  tests/backup/test_recovery_controller_lock.py \
  tests/backup/test_recovery_input_order.py \
  tests/backup/test_recovery_lifecycle_synthetic.py \
  tests/backup/test_recovery_configuration_crashes.py \
  tests/backup/test_recovery_redis_admission.py \
  tests/backup/test_recovery_resume_synthetic.py \
  tests/backup/test_recovery_installed_preflight.py \
  -k 'not prospective_real_root_binding'
```

Real DB:

```sh
python -m pytest -q --reuse-db \
  tests/backup/test_recovery_task_fence_db.py \
  tests/backup/test_recovery_acknowledgement_db.py \
  tests/backup/test_recovery_object_closure_db.py \
  tests/backup/test_recovery_producer_caps.py
```

Private root binding plus actual OLD-env import registration (same dedicated DB):

```sh
SPACEWORKS_TEST_PRIVATE_HOST_STATE=1 python -m pytest -q --reuse-db \
  tests/backup/test_recovery_input_order.py::test_prospective_real_root_binding_for_disaster_or_initial_import \
  tests/backup/test_recovery_trusted_import_db.py
```

Root copied installation and synthetic fresh install:

```sh
python -m pytest -q --reuse-db \
  tests/backup/test_recovery_installed_layout.py \
  tests/backup/test_recovery_bundle_install.py \
  tests/backup/test_recovery_fresh_install_synthetic.py
```

Separate actual S3 proof:

```sh
SPACEWORKS_TEST_S3_DISPOSABLE=1 python -m pytest -q --reuse-db \
  tests/backup/test_recovery_object_readback_s3.py
```

Separate live Redis/Celery proof. Provide the actual dedicated URL and actual effective pytest DB name in the environment; there is no default broker/shared DB fallback:

```sh
export SPACEWORKS_TEST_REDIS_URL='redis://DEDICATED-TEST-REDIS:6379/TEST_DB'
export SPACEWORKS_TEST_REDIS_DEDICATED=1
export SPACEWORKS_TEST_LIVE_DB_NAME='EXACT_EFFECTIVE_PARENT_PYTEST_DB_NAME'
python -m pytest -q --reuse-db tests/backup/test_recovery_live_generation.py
```

The executable private worker is `python -B -m tests.backup.recovery_live_tasks worker`; the test orchestrates it with exact DATABASE_URL, SPACEWORKS_TASK_GENERATION, SPACEWORKS_TEST_REDIS_PREFIX and continuity values in its environment. Do not start it against the application database. It starts two private processes sequentially, kills the old unacked one, then shuts down the new one in finally. No production worker/service is stopped. Test temp artifacts retain private worker logs and live-generation-proof.json on success. Redis keys under that unique evidence prefix remain after success/failure for inspection; no expiry/purge/delete cleanup is issued.

## Source findings and withheld assertions

1. **Resolved during writing: plain-tar file/ancestor conflict screening.** Initial source inspection found that exact-name tracking permitted a regular `objects/private/a` and descendant `objects/private/a/b` through project_metadata, with private extraction later failing with filesystem FileExistsError. The source author independently corrected `_plain_members` to reject parent/regular-file conflicts in either archive order and refreshed the25 guard hashes/source freeze. This executor changed no production source. After reading that correction, tests were added for file-first, child-first and directory-child-first refusal, plus valid explicit directory/implied parent cases. They remain unexecuted. The previous failure was before config/service/SQL; no escape or authentication bypass was demonstrated.
2. **Fixed-file hash contract boundary.** The approved checker hashes the25 guarded dependencies and structurally checks the checker/original fixed entries. It does not pin arbitrary changed checker/other fixed-file content independently of the authenticated release. Tests cover changed guarded bytes, malformed checker syntax, every missing/link/nonregular fixed path, and malformed literal guard declarations. They do not invent refusal of arbitrary changed fixed/checker bytes that current code intentionally does not implement. If that broader refusal is required, parent must review a source-contract extension; no self-mirroring assertion or production-check weakening was added.

## Remaining verification

Every new test is **unexecuted and uncollected**; there is no pass count. Runtime/API compatibility, crypto/PG/age/object round trips, all real Docker inventory/one-off/env/volume behavior, actual destructive restore/cancellation/operator-recovery drill and production deployment remain unverified. Synthetic transport success is not host attestation. The prior reported226 signed-full PostgreSQL/age/crypto/object cases predate this group; they were not rerun or edited here and cannot certify these new sources. Parent must run the above lanes, reconcile failures and the fixed-file hash contract boundary, rerun the historical real suite, then Stage4 and owner QA. No automatic failed-restore rollback/unblock or deployment readiness claim is made.

## Frozen files

| Path | Lines | Whole-file SHA256 |
| --- | ---: | --- |
| `backend/tests/backup/recovery_bundle_support.py` | 66 | `5b23ab001d44a029b43e15ad4c101b4a1d283309039637688f9412b77a1125e3` |
| `backend/tests/backup/recovery_fresh_install_support.py` | 92 | `f7d94b47e96e57921d72ff22df903a2f4be6441c3d3e66839b618dad752712ab` |
| `backend/tests/backup/recovery_input_support.py` | 108 | `8ef61c03e1f232f437bc9b7d78ca867126def2505f03508bbe50f160b983fb06` |
| `backend/tests/backup/recovery_live_support.py` | 94 | `aadcda13c93a0d7b3dcfc9623b6a062301b47b6d5d6b5634c2be9e2a774fd2c3` |
| `backend/tests/backup/recovery_live_tasks.py` | 83 | `5dd3a2bd57af9d58e2332b6177f00f490e1704c424603eaac3fdea64b78b6d35` |
| `backend/tests/backup/recovery_object_support.py` | 56 | `af491664a7305dbe466fdb814bd71d58862daa7ad64d5435e19254d89ec7d63d` |
| `backend/tests/backup/recovery_test_support.py` | 123 | `7ab7f02af9626cb7df02ed2f5897a740f1e8715476afd3631527500725d17653` |
| `backend/tests/backup/recovery_transport_support.py` | 198 | `82c2bb963f48a2e4685974f55572c283f066778b66e1682f765a55b62ec30211` |
| `backend/tests/backup/test_recovery_acknowledgement_db.py` | 41 | `996c7db6ec6e145366edd7e6f09cec487611efdf04399e094f20cb5550a9c96a` |
| `backend/tests/backup/test_recovery_bundle_install.py` | 132 | `c89ae4f07b2c5b539d624655e8437db8a1bca1741ce81fb6344a8478af7854e0` |
| `backend/tests/backup/test_recovery_configuration_crashes.py` | 67 | `54b56054948f9868c16be982453b0432fae7de48b2e6624ecdbd2f9ad606ffcc` |
| `backend/tests/backup/test_recovery_controller_lock.py` | 146 | `d7ff77d6161623a95117488a901590ec67e8f39caae908f604ee52db4395e5f8` |
| `backend/tests/backup/test_recovery_fresh_install_synthetic.py` | 49 | `d0907b70ef80f7030f7e07abdd4eb49948399a22213490bde8950ffdaef1fcb5` |
| `backend/tests/backup/test_recovery_input_order.py` | 116 | `010dfde858f26598cd23fd3d1ac9b84e9c8b463250ae023538d787d2e3fa5604` |
| `backend/tests/backup/test_recovery_installed_layout.py` | 107 | `5112cf21b9f6b0358db5ea574d93ab74645fd6eb322350370b7b10813de822d2` |
| `backend/tests/backup/test_recovery_installed_preflight.py` | 54 | `a8e446e8ee9b36cb987eb24c79581ffff4acc793cf53ad90d0146134ef2b7e3b` |
| `backend/tests/backup/test_recovery_lifecycle_synthetic.py` | 155 | `1f323e0a96b6631d4a51f964cc1b229df4cb5eb135f3ac9d4f0046e7de21a9e2` |
| `backend/tests/backup/test_recovery_live_generation.py` | 100 | `930bd1812d8ef5e88b33362b4dda05f475a709ac8eb5e8c8a160d3e3c878dc07` |
| `backend/tests/backup/test_recovery_marker_authority.py` | 118 | `a210e9831914c2817fb9c18a097e1948daff1f00294f7f775ba0e70ef35cbde3` |
| `backend/tests/backup/test_recovery_object_closure_db.py` | 149 | `0964363a62804a0eca877ac13e623e58bd00b3365d067d97ebd63f50cbac35b5` |
| `backend/tests/backup/test_recovery_object_readback_s3.py` | 66 | `28052d7328d9356b7d6f15da3d95d338a415d8579ae6dab2ab913d4e55fd7a7f` |
| `backend/tests/backup/test_recovery_producer_caps.py` | 84 | `d3da57d992fb4ab0e62f258e1a0732a24df55cb8cc5f06afdbb6b9c517fa7dbe` |
| `backend/tests/backup/test_recovery_queue_and_command.py` | 102 | `b882a88094ca9a045aabd25d1cdc697e77c4edc021ac9489dc8d2b128f357b9f` |
| `backend/tests/backup/test_recovery_redis_admission.py` | 104 | `197fce41e531986b32cc77c6ee14234eb762665e372a112d32d7258201630eb4` |
| `backend/tests/backup/test_recovery_resume_synthetic.py` | 76 | `ec23483be514ae50027d1154f19864f9da9edc97d18ad0ebe03767ae945e3b88` |
| `backend/tests/backup/test_recovery_tar_screen.py` | 186 | `cbd4786b812677726c29110a5d9b3cf6c512ca4fb40155b002622352483fbbe1` |
| `backend/tests/backup/test_recovery_task_fence_db.py` | 95 | `8da9ff43475bb0feb89c13cc9c8d8eecbc773e4d53a330db5f301eefa050e2da` |
| `backend/tests/backup/test_recovery_trusted_import_db.py` | 90 | `63f4734b6a4856a7f40e1a2b7795f219c43c667ca1cdc767f1b655ef172650ec` |

## Parent-lane final reconciliation (supersedes the withheld path assertion)

All three Stage3 CLI invocations closed successfully, with no runtime run by this lane. Independently inspected new fixtures and behavior boundaries, parsed all31 test/helper paths as AST data and verified every frozen test/helper hash plus all60 source and59 installed-copy hashes. The author corrected archive fixtures through archive_row: actual expiry and unique object keys at INSERT, preserving immutable and SQL guards. The original28-file test snapshot remains in files; reviewed followup entries add the two rewritten legacy host files and seven-case tar path file. Historical signed-full freezes remain untouched.

Parent approved and implemented the tiny tar file/ancestor screening correction; the earlier finding describes previous source behavior and is now resolved in current source. Separate seven genuine tar tests cover both conflict orders, keys directory conflicts and legal explicit/implied directory orders. The legacy six host cases now use the actual controller/lifecycle, pinned crypto and real root files. Every observed transport phase proves cross-process contention on the held operation lock and rejects cleanup-rollback dispatch. Fake provider/SQL/age responses remain explicitly synthetic.

The private finite parent runtime entrypoint is /tmp/spaceworks-run-recovery-tests.sh, with lanes fast, db, private, installed, compat, paths, s3 and live. Its exact hash is in the current test freeze. Add --tmpfs /run:rw,mode=755 to a fresh disposable Linux UID0 test container: the backend image normally creates an empty fixed namespace, while these tests must create/remove only their own namespace and must never adopt or delete actual authority. Mount full checkout /repo read-only and backend /app; use the assigned isolated PostgreSQL URL/continuity and explicit dedicated S3/Redis opt-ins. Never run two pytest processes against one DB.

Current source freeze SHA256: `47d6ece60b36f5ba67409ae8aecef9417e6000aa2c2377865b9974166dec8148`. Current test freeze SHA256: `e6b8034952b2af24006a7664c4156e7b1c22ffc37529248ea5e8975ca99013d8`. Source/control hashes and CLI syntax are static evidence only. No runtime pass count is claimed; actual host feasibility passed separately under parent execution, while the full topology/restore and live broker tests remain pending. No further source/test writers remain in this lane.

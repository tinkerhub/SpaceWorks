# Signed-full operational correction — Stage 2 handoff

Implemented on `dev` under the approved operational delta and final correction
(`/tmp/spaceworks-backup-full-operational-delta.md`,
`/tmp/spaceworks-backup-full-operational-final-delta.md`, final review `APPROVED`).
This supersedes `backup-full-stage2.md` as the current signed-full Stage 2 handoff.
The previously approved cryptographic/cohort base remains in place.

The source correction removes deployment-local authority from the full payload and
preserves the target identity before any post-replacement Django entrypoint:

- `DeploymentCapture.select_from_snapshot` freezes custody, retained population,
  complete servable cohort, run/holder and queried source identity in the exported
  REPEATABLE READ transaction before `pg_dump`. Preparation only binds the actual
  dump hash; it refuses late selection. Direct legacy `CompoundCapture` and probes
  without selection still use their existing preparation interface. Frozen object
  references are checked again before manifest/publication snapshot use.
- Full-only dump data exclusions resolve actual tables from the existing exact
  `OMITTED_OPERATIONAL_MODELS` registry. Schema/triggers and domain/global rows
  remain. The signed manifest requires its exact sorted model list. Full source
  facts use authoritative queried endpoint/TLS/immutable UUID and coherent server
  version; `pg_control_system` is optional corroboration through the existing
  savepoint-aware query. Missing UUID refuses; no extra grants or scratch CREATEDB.
- Only registered, signature-verified full export adds exact target singleton
  UUID/lineage/timestamp plus queried name/OID/endpoint/TLS/system facts to the
  outside-DB control record. Full control files are bounded to 64 KiB, mode 0600,
  fsynced, and never supplied by the archive.
- Signed-full preflight returns `full-preflight-ok`; legacy returns `preflight-ok`.
  The supervisor requires the same admitted token twice. Immediately after final
  `pg_restore`, full restore pipes private control JSON over stdin to the existing
  fixed `orchestration-ready` grants bootstrap with `SPACEWORKS_GRANTS_ONLY=1` and
  `SPACEWORKS_RESTORE_IDENTITY=1`, before rehydrate or later management commands.
- The settings-free helper validates strict typed target facts against the unchanged
  root-owned BOUND NORMAL marker and actual physical endpoint/name/OID/TLS, with
  available system corroboration. It requires zero identity rows under a table lock,
  inserts the exact target immutable row using fixed parameterized SQL, then checks
  the complete queried identity and exact row. Insertion and existing grant
  reprovisioning share the maintenance connection transaction. Any refusal or grant
  failure rolls insertion back. Unknown identity modes and alternate-database
  selection refuse. Rehydrate only verifies identity; it never repairs/adopts it.
- Legacy/pre-DB rollback/temp-diff grants remain ordinary grants-only calls. Existing
  destructive rollback remains the failure path. B1 remains refused; its source
  proof/producer rules, default dump arguments, models/migrations, root marker and
  pointer behavior are unchanged. Existing run-holder, terminal-promotion idempotence,
  timestamp/header normalization and rollback-cleanup work were preserved. Authority
  registry changes only append the three approved paths, preserving prior additions.

Verification was bounded to these owners: Python AST syntax parsing, `bash -n`
for `scripts/restore.sh`, scoped `git diff --check`, and source inspection of routing,
SQL/transaction order and the helper's import closure. No application imports,
startup, test writing/runs, Docker/provider/DB execution, migrations, staging,
commit or push occurred. All changed source files are at most 300 lines. These are
static findings, not runtime success claims.

## Exact source snapshot (SHA-256)

| Changed file | Lines | SHA-256 |
| --- | ---: | --- |
| `backend/apps/backup/full_capture.py` | 143 | `f84a843a7788a8f2428aef5d3cd9c3ff5b088efb23d215e7a8425b0c9f57710e` |
| `backend/apps/backup/full_source_identity.py` | 79 | `713a1fb31bca6c05a5806f3842c9400695a868b5252aecebe789b11b8d2bffe1` |
| `backend/apps/backup/full_manifest.py` | 106 | `ae95e0d04782d25152a000327c9f58d00baf7b125436fd79f176a6ef036fc2cc` |
| `backend/apps/backup/full_manifest_validation.py` | 235 | `2c011881caae4d996fd5b45acd3f057b00eb5fbc8a15a48c5a5e04aca54734ca` |
| `backend/apps/backup/archive_payload.py` | 228 | `a5817836393d8a565aabf306a8170355671cd1ef498841e1ff85a89d5dfea102` |
| `backend/apps/backup/full_restore_identity.py` | 215 | `ac9d9bb0baf4092f2c207a3965ec9d1ee6f7c826042bed2e337e9cbd49d6646f` |
| `backend/apps/backup/restore_control_records.py` | 155 | `d9ebccd90886b6b20c373ff244b83c5065868401cc82b8e9b4067d831875a20c` |
| `backend/apps/backup/backup_control_preflight.py` | 180 | `e39dcf19d4220183a4f7091f49180368cc4876845536ce048c3cb30163a9f15e` |
| `backend/apps/backup/settings_policy.py` | 185 | `5610610f92ca73ccfddd048c9a5c2b0fc482296615da8021683545394460b708` |
| `backend/scripts/bootstrap_host_orchestration.py` | 170 | `36b45bc09deb26654e936d1bbba9bad6acfdde48abe68f11c86bf1685e7d28d5` |
| `scripts/restore.sh` | 266 | `a4fe630683c9bf2b5be6a17a3b6d9a88036b1b01e6b1efe94fe12eb8f0b42110` |
| `backend/apps/tenant_migration/authority_guards.py` | 204 | `e89eb12ece9d16502d66de1c5c916e7e678b88b69f490a71f9f791419c999241` |

Reviewed, unchanged owner: `backend/apps/backup/full_population.py`, SHA-256
`1603afce74c8885e3c7c5608a69bc46b90197764347610af9e16a36a93405732`. Hashes describe whole working-tree files, including pre-existing
approved work; they do not attribute that earlier work to this correction.

## Parent-owned Stage 3 requirements (not written or run here)

- Actual least-privilege PostgreSQL source capture without pg_monitor/extra grants or
  CREATEDB succeeds when the immutable UUID exists; missing UUID fails. Prove one
  snapshot selects full/cohort/run/source before dump and no later live read replaces
  those facts. Cover drift in frozen run/holder/cohort/population/source/object refs.
- Inspect actual full custom dump and restored scratch DB: all three exact operational
  tables have zero rows, retained schema/triggers remain, domain/global rows survive,
  and source UUID/receipts remain unchanged. Reject omitted-registry downgrade/drift,
  malformed source shape/version and altered dump bytes/signatures. Preserve B1 and
  default legacy dump behavior/proof semantics.
- Prove ordinary management refuses a restored empty identity table, while the fixed
  maintenance bootstrap restores the exact target UUID/run/hash/capture/timestamp
  before any later Django entrypoint. Check unchanged root marker/readiness identity,
  actual endpoint/name/OID/TLS and available system corroboration, including fallback.
- Cover missing/malformed/oversized/duplicate-key/wrong-format control records,
  endpoint/OID/UUID/TLS/system or marker mismatch, non-BOUND/non-NORMAL/missing marker,
  unexpected source/existing identity rows, unknown mode/alternate database, and
  refused post-query. Each must leave no inserted identity. Exercise parameter binding
  and transaction rollback on post-query and grant failure; no private payload/DSN logs.
- Prove exact two-token/second-preflight matching, stdin/fixed command/role shape and
  final replacement -> identity/grants -> rehydrate -> validation order. Ordinary
  legacy, pre-DB rollback and temp-diff grants must remain unchanged. Exercise real
  destructive rollback and host readiness after bootstrap failure. Retain the base
  promotion concurrency/idempotence and provider timestamp-header coverage.
- Verify settings-free standalone bootstrap import and existing environment-policy
  totality guards with `SPACEWORKS_RESTORE_IDENTITY` classified ordinary EXCLUDED.

## Operator wording for parent integration

“Signed-full deployment backups omit deployment database identity and purge receipt
rows while retaining their schema. In-place signed-full restore preserves the target
physical database's exact immutable identity against its existing root-owned NORMAL
marker. The supervisor supplies private pre-restore state to the fixed maintenance
identity/grants bootstrap before starting a Django management command. Do not set
`SPACEWORKS_RESTORE_IDENTITY` for normal startup or use it to adopt an archive UUID;
it is an internal, grants-only restore mode, excluded from settings compatibility.
Missing or mismatched target facts refuse restore and use the existing rollback path.”

Parent separately owns forwarding real `SPACEWORKS_OCI_DIGEST` through Compose and
operator/release documentation. Strict OCI checks remain; no digest was synthesized.
No production-ready claim: the absent concrete sovereign host coordinator remains a
limit, and B1 restore is still unsupported on this host. Parent owns tests/review/QA.

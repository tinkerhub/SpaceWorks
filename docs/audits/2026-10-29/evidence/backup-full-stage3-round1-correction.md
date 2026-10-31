# Signed-full Stage 3 round-one fixture correction

Status: test/helper correction only; runtime verification belongs to the parent.
The supplied parent evidence reports **224 cases, 209 passed, 15 failed**.
Those are the previous run's results, not results of this correction.

## Scope and evidence

Read repository `AGENTS.md`, `~/.claude/CLAUDE.md`, `docs/DEV-WORKFLOW.md`,
the backup/restore/tenant-migration section of `docs/INVARIANTS.md`, exact failure
traces in `/tmp/spaceworks-signed-full-round1.log` and
`docs/audits/2026-10-29/evidence/signed-full-round1.xml`, and relevant source.
This is the parent's explicitly scoped Stage 3 correction, not a new build or
approval of later workflow gates.

No production source, environment files, other tests, index or commits changed.
No tests, collection, database connections, Docker commands, migrations,
providers, builds, or review processes were run. The parent's runtime and
production freeze remain untouched.

Relevant source inspected includes `full_population.py`, `full_capture.py`,
`promotion.py`, `promotion_validation.py`, backup migrations 0023/0024,
`models_runs.py`, `models.py`, makerspace lifecycle constraints,
`full_control_record.py`, `restore_control_records.py`, `services_archives.py`,
`full_bundle.py`, `import_preflight_bundle.py`, `import_preflight.py`,
`full_source_identity.py`, `database_identity.py`, `full_restore_identity.py`,
`database_grants.py`, `projection_databases.py`, and the fixed
`backend/scripts/bootstrap_host_orchestration.py`.

## Fixture corrections and protected behavior

1. **Captured run snapshot / immutable flags.** A nested Django atomic savepoint
   now requires the database's specific `InternalError` on changing nonempty
   `flag_snapshot`. Persisted flags and holder are checked after rollback.
   Only the mutable holder is subsequently rotated. The frozen snapshot must
   remain identical; changing nested fields in its returned dictionary must
   also leave subsequent snapshots intact. No trigger is bypassed.

2. **Archived cohort / missing holder.** Two independent parametrized cases
   insert their own run before admission. The archived-cohort input contains
   the extra archived ID; the missing-holder input has exactly valid cohort
   flags and `holder=None`. Both require the real run validator's rejection.
   This avoids rewriting immutable flags or creating two open runs together.

3. **Stale cached binding.** First prove the database refuses unbinding an
   already-bound archive inside a savepoint. Then change only the caller's
   in-memory `backup_run_id`, require the real persisted-binding check to
   refuse, refresh the object, and require the original valid binding facts.

4. **Promotion drift.** Keep the eight reachable drift cases, including an
   update setting both `archived_at` and `purge_started_at`, which satisfies
   `makerspace_purge_requires_archive`. Separate four impossible mutations:
   protected deletion, empty flags, integer-instead-of-boolean flags, and
   archive unbinding. Each must raise its specific refusal inside an
   independent atomic savepoint. Compare full persisted makerspace, run,
   archive and ledger rows after refusal, including the independent freeze.
   Then require real successful publication, the unchanged frozen snapshot,
   valid binding and exactly one completion audit. A scheduled archive keeps
   the previous global success timestamp; the scheduler owns run completion.
   No deletion of `PiiMakerspaceWriteFence`, constraint bypass or fabricated
   accepted capture is introduced. These cases prove refusal plus consistent
   publication, not rejection of an impossible persisted drift.

5. **Rehydrate source RUNNING fixture.** Prove nonnull expiry cannot be cleared
   in a savepoint and verify the original control record remains unchanged.
   Preserve that valid expiry when clearing only mutable status, manifest,
   SHA, size and completion facts. Retain available-metadata, download-token
   clearing and second-export assertions.

6. **Real B1 signature domain.** Add `django_db` to the actual B1-signature
   cross-domain case: its real reservation validation reads the PostgreSQL
   catalog. Signature-rejection assertions remain intact.

7. **Malformed extracted manifest.** Both extracted-root and companion/tar
   validation must raise exactly `ImportPreflightError` with
   `reason == "component_policy"` for invalid manifest JSON. The production
   parser raises that stable refusal before the bundle's `BackupBuildError`
   path. Other changed payloads still require `BackupBuildError`.

8. **Real privilege denial.** PG16's observed PUBLIC EXECUTE means role flags
   alone cannot prove denial. A shared test-only context first verifies the
   exact active database has a `test_` name and the connection has function
   owner authority. Before mutation it records raw `proacl` plus normalized
   `(grantor, grantee, privilege, grant-option)` tuples. It rejects unsupported
   PUBLIC grant provenance before changing anything. As the function owner,
   it revokes only PUBLIC EXECUTE on that database's
   `pg_catalog.pg_control_system()`. Every non-PUBLIC grant must remain exact,
   including pg_monitor. In `finally` it restores only the removed grant as
   the original grantor, including its grant option, and asserts equality of
   the entire normalized ACL. NULL/default ACL and an explicit default ACL
   have equal grant semantics; raw catalog representation is not claimed to
   remain byte-identical. Unsupported boundaries/restoration errors fail
   rather than producing a false pass. No direct catalog update occurs.

   Both the owner SET ROLE test and the whole-capture fresh LOGIN test now
   query `has_function_privilege(..., 'EXECUTE') == False` before requiring a
   real `InsufficientPrivilege`. The fallback must still return the persisted
   UUID and leave the transaction usable. The LOGIN denial check uses its real
   driver cursor, avoiding Django's translation to `ProgrammingError` while
   retaining the surrounding Django transaction and real savepoint. Whole
   capture keeps the same real
   LOGIN, no memberships/elevated flags, runtime ORM and pg_dump credentials,
   exported snapshot, real encrypted artifact and restore. No extra runtime
   privileges or mocked identity/query/cursor are added. Provisioning begins
   only after the test database boundary has been verified.

9. **Both real roundtrips / bootstrap.** The fixture passed
   `database.connection.dsn` to `_grant_only`; Psycopg masks its password.
   That is an unsuitable transport for a new maintenance connection. The
   replacement constructs a DSN from the existing Django connection parameters,
   removes Python-only factory options, and requires the expected uniquely
   named scratch target. It never prints the DSN or password.

   The fixed production bootstrap still runs on its own real connection.
   Delegating wrappers record only helper stage labels and exception class
   names. The required sequence is identity restore enter/complete, role
   provision enter/complete, grants enter/complete, then the injected final
   RuntimeError. The wrappers require all helpers to share the same real,
   non-autocommit connection. The fresh role must exist after provisioning;
   the exact target identity must exist after real grants. Earlier real helper
   errors cannot satisfy the sequence. The roundtrip still proves the role
   was absent before bootstrap, both identity and role disappear after its
   rollback, and marker bytes remain unchanged.

   Retained end-to-end assertions include actual pg_dump -> age -> decryption
   -> pg_restore, omitted operational tables existing with no source rows,
   target identity preservation, live private/public object bytes and expiry,
   the committed post-export source mutation versus snapshot-original dump
   contents, rejection of wrong/occupied identities, both ready states and
   real target readiness.

## Static verification only

AST parsing (without project imports or pytest collection) succeeded for all
28 matching test/helper files. They contain 80 test functions and **225
statically expanded cases**. The net +1 case separates archived-cohort and
missing-holder admission. Splitting the promotion cases preserves their count.
Every matching file is at most 183 lines. The report is also below 300 lines.
`git diff --check` completed without whitespace errors. Untracked corrected
files additionally receive `git diff --no-index --check` against `/dev/null`.
Static checks establish syntax/size/whitespace only, not passing behavior.

## Exact files changed in this correction

All Python paths below are relative to `backend/tests/backup/`:

| File | Lines | Purpose |
| --- | ---: | --- |
| `test_signed_full_capture.py` | 167 | Freeze refusal, independent malformed runs, stale caller binding |
| `test_signed_full_promotion.py` | 154 | Legal lifecycle drift; refused writes and intact publication |
| `test_signed_full_control.py` | 140 | Preserve immutable expiry in RUNNING simulation |
| `test_signed_full_manifest.py` | 139 | Database mark for real B1 signature fixture |
| `test_signed_full_bundle.py` | 156 | Exact invalid-manifest refusal class/reason |
| `test_signed_full_least_privilege.py` | 58 | Hardened real SET ROLE denial |
| `test_signed_full_roundtrip.py` | 183 | Real bootstrap witnesses and rollback checks |
| `full_backup_bootstrap_helpers.py` | 100 | Unmasked test transport and real helper sequence |
| `full_backup_runtime_role_exact_helpers.py` | 174 | Hardened ACL around fresh runtime LOGIN capture |
| `full_backup_privilege_helpers.py` | 83 | New bounded ACL capture/hardening/restoration context |

Also created this report:
`docs/audits/2026-10-29/evidence/backup-full-stage3-round1-correction.md`.
Other pre-existing worktree changes and untracked signed-full files belong to
the parent and were not edited by this correction.

## Remaining parent runtime proof and source concerns

The parent must rerun the corrected suite when its database is available;
no post-correction pass count is claimed. In particular, the original failing
families now need 16 cases checked: four capture cases, one rehydrate case,
five promotion cases, two privilege cases, two ready-state roundtrips, one
invalid-manifest case and one actual B1-signature case. Successful previously
passing cases remain subject to the parent's full rerun.

The exact original bootstrap exception is not recoverable from the supplied
trace because `_grant_only` deliberately replaces driver errors. The masked
DSN is a statically identified fixture defect and a strong explanation, not
a runtime-confirmed diagnosis. New witnesses will expose earlier real helper
failures through stable labels/classes and must not be relaxed to accept them.
No unexpected production defect has been established by this static review.

ACL behavior/restoration on this parent's exact PG16 image, genuine runtime
EXECUTE denial, complete runtime credential continuity, grants and identity
rollback, and target readiness remain unexecuted proof. The ACL helper fails
before hardening on a non-`test_` database, insufficient owner authority or
unsupported PUBLIC grant provenance; those conditions must be reported to the
parent rather than worked around. Normal failure paths restore grants in
`finally`; process termination cannot be made recoverable by Python `finally`,
so the context is strictly confined to the disposable test database.

## Follow-up correction: actual fresh source-row expiry (2026-10-30)

This append supersedes item 5's source-state explanation above; all earlier
corrections and assertions remain preserved. `services_archives.create_archive`
inserts `expires_at=NULL`. Promotion assigns retention expiry only after the
exported snapshot, so a newly built archive's authenticated source dump contains
a RUNNING row without final expiry. The retained-expiry variant is useful
compatibility coverage, not the normal fresh source state. No production defect
is established by the corrected create/capture/promote ordering.

`backend/tests/backup/test_signed_full_control.py` now parametrizes the existing
rehydration test for `fresh-snapshot-null-expiry` and
`already-retained-same-expiry`. Both retain the specific database-trigger refusal
when clearing an existing nonnull expiry, plus the unchanged selected-control
facts after that refused write.

For the fresh case, the fixture saves both UUIDs and the outside-DB control file,
requires no rollback objects, deletes the simple target `RestoreOperation`, then
deletes its archive. It inserts a fresh same-UUID RUNNING archive with NULL expiry,
empty manifest/hash, zero size and no completion timestamp, asserting those source
facts before rehydration. The retained case keeps the prior legal update and
checks the same nonnull expiry. Both require the original restore UUID, selected
AVAILABLE archive metadata and target retention, cleared download tokens, restored
report, and a valid second export with the original captured target identity.

Inspected FK/guard definitions: `models_restore.py` protects the archive through
`RestoreOperation.archive`; deleting the simple operation first releases that
reference. Its rollback-object CASCADE is empty and is explicitly checked before
deletion. Migration 0017's restrictive FKs and deletion guards protect separate
compound restore-state tables, which this fixture does not create. Artifact-ledger
and run-coverage archive references also have no rows in this fixture. Migration
0024 guards expiry UPDATEs, allows a RUNNING NULL-expiry INSERT and requires an
AVAILABLE row to have expiry. No trigger disabling, catalog edits or rollback
evidence deletion is introduced. This is an explicit SQL-row replacement
simulation, not new pg_restore evidence; the existing real roundtrip tests retain
coverage of actual omitted-source operational tables. Legal deletion remains
subject to the parent's runtime check; any blocker must be reported, not bypassed.

Static AST parsing only: **28 files, 80 test functions, 226 expanded cases**
(previously 225). The control file has **173 lines and 13 cases**; the matching
Python maximum remains 183 lines. Syntax and whitespace checks establish no
runtime pass. Only this test file and this appended report were edited in this
follow-up; no production source, other tests, staging or commits changed.

Runtime remains entirely with the parent. The previously failing families now
need **17 cases** checked, including both rehydrate variants instead of one;
all previously passing cases still need the full rerun. No tests or collection,
database connections, Docker, providers, builds or review processes were run.

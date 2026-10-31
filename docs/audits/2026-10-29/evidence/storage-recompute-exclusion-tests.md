Stage 3 tests-only handoff: real PostgreSQL storage recomputation exclusion.

Tests were independently authored after reading the repository/global instructions,
[Stage 2 handoff](storage-recompute-exclusion-stage2.md), its
[source freeze](storage-recompute-exclusion-source-freeze.json), and all four linked approved
plan/review/delta inputs. Root supplied the fresh host doctor/auth/network preflight.
**No tests, collection, Django/application imports, database/provider calls, Docker, builds,
network, staging or commits were run. Runtime validation belongs to root.**

[Test freeze JSON](storage-recompute-exclusion-tests-freeze.json) records every authored Python
file's exact SHA-256, byte/line counts, the five dirty pre-edit adapter hashes, static parameter
counts, retained input hashes and this document's hash. All ten Stage 2/approval hashes were
rechecked and match. No production or child-evidence test file was edited.

Four new test modules contain **18 test functions / 50 statically expanded parameter cases**.
These are AST-derived counts, not pytest collection or execution results. Two small helpers
support only this suite; every new Python file is below 300 lines.

| New test module | Functions | Static cases | Required observations |
| --- | ---: | ---: | --- |
| `makerspaces/test_storage_recompute_races.py` | 4 | 8 | Both producer orders, accepted upload/deletion, fresh logo/cover reload, tenant isolation/read progress, queued real migration claim. |
| `makerspaces/test_storage_recompute_commit.py` | 5 | 10 | Actual setter/holder PID equality through UPDATE and COMMIT, backend death at both gaps, lost commit acknowledgement, real SQL/scan/zero-row failures, ended-owner refusal. |
| `makerspaces/test_storage_recompute_ownership.py` | 6 | 15 | Six nesting refusals, real nested shared reuse, wrong namespace/key/mode/objsubid, actual different-backend substitution, continuity substitutions, acquisition failure. |
| `makerspaces/test_storage_recompute_admission.py` | 3 | 17 | Fresh initial/final admission, recovery absence/all nonnormal modes, source/not-restored/servable/purge/module barriers and command skip/warning behavior. |

The producer is the actual `MakerspaceLogoImageView` / `MakerspaceCoverImageView` PUT/DELETE
lifecycle. Real users, DRF serializers/permissions, publication validation of PNG bytes,
metadata transactions, quota debits, post-commit version deletion, quota credits and audit
writes remain active. Only `_client` provider transport uses the existing versioned
`tests.atomic_publication.store.Store`; there is no successful fake source/storage guard,
admission, quota or accounting operation. Managed mode comes from real settings and finite
storage limits, rather than replacing `is_self_host` or `add_storage`.

The concurrency cases start separate Django thread connections, coordinate with bounded
events, and inspect real `pg_locks` plus `pg_blocking_pids`. A writer-first pause retains the
canonical shared source boundary while recompute is an observed exclusive waiter. Releasing
the writer lets the scan include its committed metadata and exact charge; upload covers both
makerspace image fields selected before draining. Deletion pauses in actual post-commit
cleanup while its charge still exists. Scan-first pauses retain exclusion and observe the
producer waiting before provider/metadata/accounting/audit effects; its later increment or
decrement survives the committed SET. Another tenant's accepted producer and an ordinary
same-tenant ORM read finish while the scan stays paused. Real `source_gate.claim` is observed
holding global key 0 while queued for N; the command never takes 0 and both operations finish.

The SQL probe delegates acquisition and every verification query to PostgreSQL. It records
the real UPDATE backend, pauses after the actual uncommitted UPDATE, observes the original
exclusive lock still granted and the old counter visible to an independent reader, then
observes the lock again immediately before actual COMMIT. It also verifies that recompute
adds no audit entries. Failure injection is limited to these explicit faults:

- Terminate the actual retained backend during HEAD, or immediately before the real UPDATE
  after the final real ownership verification. Require no committed counter change, success,
  reconnection, reacquisition or backend adoption.
- Raise acknowledgement loss **after real COMMIT**. Require the actual changed counter and
  the truthful uncertain/fresh-rescan error, without an unchanged promise or automatic retry.
- Execute real division-by-zero SQL, remove/change the recovery singleton after the last
  verification so the real setter returns zero rows, or raise a provider scan failure.
  Require rollback/close, released ownership, preserved counter and no success output.
- End transactions or replace actual lock/backend observations with real wrong locks or a
  real impostor backend. No verifier result or private production owner flag is fabricated.

Admission fixtures retain the normal migration/conftest recovery singleton. Not-restored
state uses existing E7 operation/component constructors with their actual frozen identity
facts. Module intent uses the existing validated receipt constructor after supported module
profile removal. Purge intent uses `commit_intent`, including the required archive and audit
proof. Tests never clear/rewrite immutable intent, recovery identity or restore-state fields,
disable triggers, or enable an immutable-write bypass. Late admission changes are deliberate
committed fault inputs inside the scan, not a claim that an independently admitted migration
writer can pass the held exclusion; the separate claim race proves it waits.

Five permitted compatibility adapters changed:

- `test_managed_limits_enforcement.py`: only recompute gains committed setup and two evidence
  cases. Unproven declared bytes with no observed object now total zero. Actual observations
  of 17 and 23 bytes still total 40, independently of declarations of 40 and 60.
- `test_storage_reconciler_gaps.py`: only the maintenance recompute test gains committed setup;
  maintenance's existing recorded-size fallback and positive total remain.
- `events/test_recompute_event_artifacts.py`: its six recompute cases gain committed setup;
  all image/certificate/category assertions remain.
- `makerspaces/test_module_cleanup_boundaries.py`: only the recompute case gains committed
  setup and an actual exclusive owner for its direct scan call.
- `tenant_migration/test_module_cleanup_source_contract.py`: adds 14 actual-command structural
  mutation inputs for exclusive opt-in, reload/admission, recovery, real setter connection,
  bound SQL, rowcount and commit. Its owner-file mutation group now has 20 cases, including
  the two prior recompute cases. The actual production guard must reject each mutation.

The existing managed-limits adapter already exceeded 300 lines (345 at handoff). It received
only the explicitly permitted recompute-case adapter; unrelated tests were preserved rather
than moved. Every other edited/new Python file is below 300 lines. Child
`evidence/test_evidence_recompute_provenance.py` remains unchanged and transactional.

**Outstanding continuity defect from static inspection — keep the two strict tests.**
`_BoundaryExclusiveLock._verify` records/checks the original backend PID and matching
`pg_locks` row but retains no transaction identity. After the original transaction ends,
a real matching session lock or a matching lock in a new transaction on that same backend
satisfies those checks. The two cases in
`test_ended_transaction_cannot_be_hidden_by_same_pid_exact_substitute_lock` require refusal
and are predicted to fail against the frozen source. They have no skip/xfail and were not
weakened. This is a deliberately injected continuity fault, not evidence of an ordinary
production reconnect/reacquire path. Root must run them and resolve the required uninterrupted
transaction guarantee before claiming validation. No source repair was made in this stage.

Proof limits: a synchronous psycopg2 backend waiting on an ungranted lock cannot also execute
its own verification query. The suite therefore observes real `granted=false` waiters in both
producer orders and real granted wrong-identity/mode/subid locks, rather than inventing a
successful verification response with `granted=false`. Production-role grants, transaction
pooler behavior and actual provider behavior remain root/environment checks; fake transport
does not prove those deployment properties.

Static verification performed: AST parsing of all 11 authored/edited Python files; static
expansion of test parameters; all structural mutation target strings present and every
mutated file parses; adapter-scope AST comparison against dirty pre-edit snapshots; no
skip/xfail in the new suite; whitespace checks including new files; scoped `git diff --check`;
all Stage 2/approved-input hash comparisons. None executes an application or guard function.

Pending root execution, sequentially in the already approved PostgreSQL/encryption host
environment, with one pytest process at a time (commands below were **not run**):

```bash
cd backend
python -m pytest -q tests/makerspaces/test_storage_recompute_*.py
python -m pytest -q tests/test_managed_limits_enforcement.py tests/test_storage_reconciler_gaps.py tests/events/test_recompute_event_artifacts.py tests/makerspaces/test_module_cleanup_boundaries.py tests/tenant_migration/test_module_cleanup_source_contract.py tests/evidence/test_evidence_recompute_provenance.py tests/tenant_migration/test_source_gate_guards.py
```

Run the new group first and report its actual results, including the predicted continuity
failures, before the compatibility group. Later independent review and owner QA remain root's
workflow; this handoff makes no runtime-pass, production-readiness or commit claim.

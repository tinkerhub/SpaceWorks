Stage 2 source-only handoff: bounded storage recomputation exclusion and same-backend counter commit.

Implemented the independently approved plan and delta. This handoff records source inspection and
static verification only; it does not claim passing concurrency tests or production readiness.
Root supplied the fresh doctor/host credentials/network preflight. This Stage 2 run did not repeat it.
No tests, collection, Django/application imports, database/provider calls, Docker, builds, network,
staging or commits were performed. Separate Stage 3 writes the tests; root owns runtime validation.

Approved inputs copied byte-for-byte into this directory:

- [Plan](spaceworks-storage-recompute-exclusion-plan.md)
- [Plan review: APPROVED](spaceworks-storage-recompute-exclusion-review.txt)
- [Same-backend delta](spaceworks-storage-recompute-exclusion-delta.md)
- [Delta review: APPROVED](spaceworks-storage-recompute-exclusion-delta-review.txt)

[Source freeze JSON](storage-recompute-exclusion-source-freeze.json) contains actual post-edit SHA-256,
pre-edit SHA-256, byte/line counts, copied approval hashes and preserved calculation hashes. The
pre-edit baseline includes the dirty working-tree edits present when this run began, rather than HEAD.

Exactly these existing files were changed by this Stage 2 run:

| Path | Post-edit SHA-256 | Lines |
| --- | --- | --- |
| `backend/apps/tenant_migration/gate_locks.py` | `15f887d69327fc62ff347fe99ffafecebeb7dbb6507466a7050486b2da8f0a07` | 244 |
| `backend/apps/tenant_migration/gate_runtime.py` | `698de047e07cc027d2dc52cc52913e441e498df4bb952aff968f99be4c6c4332` | 200 |
| `backend/apps/tenant_migration/source_gate_module_guards.py` | `01956bb3f42775844d321e79f3df23b61304d12d118c19bf8ed50a57762afd46` | 257 |
| `backend/apps/makerspaces/management/commands/recompute_storage.py` | `7606ddad0c8f59dcba622cad504b9080591f9339408db318cd0164110fc30825` | 213 |
| `docs/self-hosting.md` | `dd53240d6a3e077e23dc05a1f08de7f4af7103f370d6ac5872d8a67f010bad7b` | 930 |
| `docs/SOURCE-MAP.md` | `6250b95c4562d8a93f04820f4d41795b9876f8fb67488091920b515b2becb1eb` | 351 |

The only new repository files are this handoff, its source freeze JSON and the four approved input
copies above. No production helper file, model, migration, ledger, alias or framework was added.
The 300-line ceiling applies to the edited Python files; the existing long documentation files
received only the requested unreleased paragraph and source-map addition.

Implementation and approved-constraint reconciliation:

- `boundary_tenant_write` and `fanout_tenant_write` have keyword-only `exclusive=False` defaults.
  The command explicitly opts into `exclusive=True`. Exclusive admission refuses retained tenant
  shared/exclusive owners, retained unscoped shared ownership, caller atomic blocks and disabled
  autocommit before the reuse shortcut. Nested shared guards/assertions reuse the exclusive owner.
- A fresh direct psycopg2 connection retains the transaction-scoped tenant lock in namespace 734310.
  Acquisition and subsequent verification require the original backend PID, tenant key, advisory
  type, `objsubid=2`, `ExclusiveLock` and `granted`. The owner is registered only after acquisition.
  Continuity failure invalidates it; the code never reconnects, reacquires or adopts another backend.
- No existing lock helper was relocated or modified. Migration-exclusive APIs, claim's global key 0
  then tenant ordering, archive-owner behavior and ordinary readiness/read paths remain unchanged.
  The command acquires only its tenant key and never later acquires key 0.
- The lock drains admitted shared writers and excludes new tenant writers through the scan and
  counter commit. ORM and provider reads use the normal application connection outside a new
  application transaction. No application row lock is held across provider I/O.
- `_admit` reloads the servable makerspace after exclusion, protecting logo/cover keys from a stale
  loop instance. It freshly checks retained source ownership, source/restored/purge-intent state,
  unfinished module purge, servability and the existing recovery singleton's NORMAL mode. Missing
  recovery rows refuse. `_commit` repeats admission before acquiring its verified connection.
- The private `_exclusive_boundary_connection` requires the matching context-owned exclusive
  owner and verifies continuity. `_commit` executes constant SQL with bound `[total, makerspace_id]`
  on that connection. Its WHERE requires the existing recovery singleton at ID 1 in `normal` mode;
  anything other than exactly one affected row refuses success.
- Counter UPDATE and COMMIT use the same retained backend and uninterrupted transaction as the
  advisory lock. Backend loss between verification and UPDATE cannot leave an independently
  committed setter. The final UPDATE takes its row lock only after all provider reads finish.
  Commit acknowledgement precedes success output; there are no further domain writes afterward.
- Every exit attempts rollback and close. Cleanup preserves the original error. A commit exception
  reports an uncertain outcome and requires a fresh rescan; it never promises an unchanged counter.
  Source-closed/not-restored fanout skips, module-purge warnings and scan-error/no-SET behavior remain.
- `_sum_evidence`, `_sum`, `_public_image_keys` and the complete category-calculation assignment are
  byte-for-byte unchanged against the dirty pre-edit baseline. The `proven_charge_bytes` evidence
  correction remains intact. Frozen sibling limits bool/source-affinity work was not edited.
- The command still emits no AuditLog writes, preserving its prior behavior. The explicit class-method
  guard requires literal exclusive opt-in, fresh admission/reload and the actual same-backend constant
  setter/rowcount/commit path. The general fanout scanner and its top-level registry remain untouched.
- Operator documentation describes the tenant write pause, maintenance recommendation, top-level
  non-atomic/autocommit requirement and uncertain-commit rescan. Helpers and SQL stay implementation
  details; this change does not assert a full billing or provider audit.

Post-edit inspection reread the affected source and the delta against the pre-edit snapshots. Static
AST parsing passed for all four Python files; scoped `git diff --check` passed. Source-segment
comparison confirmed the preserved command calculations and every pre-existing `gate_locks.py`
declaration. These checks did not execute application modules or coverage-guard functions. Runtime
behavior and the strengthened guard itself still need Stage 3/root execution.

Remaining Stage 3/root test matrix (real PostgreSQL, committed fixtures; provider transport only mocked):

| Scenario | Required proof |
| --- | --- |
| Writer first | A real accepted upload/file-counter producer holds the shared boundary; actual `pg_blocking_pids` shows recompute waiting; after producer commit the fresh scan includes its metadata and exact charge. |
| Recompute first | Pause provider scan under exclusion; the real producer waits before its metadata/provider/accounting effects; after counter commit the producer's increment survives. |
| Deletion counterpart | Real deletion/free-storage producer in both orderings; exact canonical final total and no lost decrement. |
| Same backend | Observe the setter's actual backend PID and exclusive lock holder PID; require equality through commit. |
| Backend lost before write | Terminate the retained backend during scan and after final verification but before UPDATE; no setter and no success, no reconnect/reacquire/adoption. |
| Transaction continuity | Lost lock, ended transaction, changed PID or incorrect namespace/key/mode/objsubid/grant refuses final write; context cannot be reused after commit. |
| Commit acknowledgement loss | Failure after actual server commit reports uncertain/fresh-rescan, without an unchanged promise or automatic retry. |
| Scan/acquisition/SQL failure | Every failure releases ownership/connection; storage scan failures leave counter unchanged; zero affected rows refuses success and rolls back. |
| Nesting and callers | Same/different-tenant shared nesting, exclusive nesting, unscoped shared owner, atomic and non-autocommit callers refuse before provider I/O; nested ordinary assertions/shared guards reuse the acquired owner. |
| Fresh admission | Closed source, unrestored tenant, archive/inactive tenant, purge intent, unfinished module purge, absent/non-NORMAL recovery refuse before provider reads and again before final write; final SQL independently refuses a changed recovery mode. |
| Stale loop instance | Commit changed logo/cover keys in a draining producer; command uses the reloaded keys after exclusive acquisition. |
| Migration interaction | Queued migration claim retains global-0-before-N ordering, command completes without later requesting 0, migration progresses after release; normal migration owners/readiness remain unchanged. |
| Isolation/progress | Another tenant's normal producer and ordinary read-only progress continue while this tenant is excluded. |
| Existing categories/contracts | All-category and evidence-provenance recompute coverage remains valid, typed skips/warnings remain, no AuditLog writes appear, and original shared defaults remain valid. |
| Static guard regressions | Run actual source/fanout guards; mutation coverage should reject removed exclusive literal, admission/reload, recovery predicate, wrong connection, missing rowcount or missing commit. |

Adapt existing atomic command fixtures to committed/transactional setups; do not disable source locks,
substitute successful lock mocks or run multiple pytest processes against the same database. Root should
verify production-role UPDATE permissions and transaction-pooler behavior in its runtime environment.
The NORMAL predicate is admission at the write statement, not a new host-restore coordination protocol:
host restore still requires real writer quiescence. Complete Stage 3, root runtime checks and the later
independent review gates before claiming the concurrency fix validated or committing.

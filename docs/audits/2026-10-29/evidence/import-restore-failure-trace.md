# Import/restore failure trace — read-only verification

Status: confirmed control-flow defects; no runtime failure injection performed in
this pass and no production-source changes made. This report qualifies the earlier
environment-rollback concern with the actual shipped topology validator.

## Reachability: normal different-key import currently stops before SQL

`import-backup.sh` validates the artifact at lines67–68, copies current `.env`, merges
verified continuity values into a work file, then installs that file as `.env` at114.
Its EXIT trap only removes the temporary work directory; it never restores `.env`.
At116 it tries the committed Compose wrapper to recreate backend/worker/beat.

`spaceworks-compose.sh` invokes `validate-compose-wrapper.py`, whose
`host_topology_record.configuration_facts` hashes the complete static environment
file (`static_environment_sha256`). `validate_compose_wrapper` compares those facts
with the root-installed topology record and refuses drift. Import never updates
that record. A different-key import therefore normally fails at116, before archive
registration, restore intent or SQL replacement. Reformatting identical values into
single-quoted assignments can change the raw digest too.

The existing containers retain their old environment, so this immediate failure does
not prove they are serving the old database with new keys. It does leave host `.env`
changed, the old private backup retained, and supported future Compose operations
refused until the operator resolves the configuration record/environment mismatch.
If the resulting `.env` bytes happen to be identical, the path can proceed. A later
SQL/old-key mismatch requires a separately admitted configuration transition, a
bypass or a future correction; it is not the ordinary current different-key path.

## Four restore outcomes

| Outcome | Exact current behavior | Proven state / risk |
| --- | --- | --- |
| Failure before SQL replacement | Before claim, cleanup has no state action. After claim, `destructive=0` calls `control pause` with failure ignored (`restore.sh95–98`). `prepare_restore_resume` resets QUIESCED to PREFLIGHT and RecoveryState to NORMAL, clearing active restore. Any stopped workers are restarted; backend was normally never stopped. | Standalone same-environment restore remains pre-destructive. Import has no environment rollback/transaction and may already have a changed host file. No durable outcome proving environment coherence is written. |
| SQL rollback command/grants succeed after destructive failure | Main EXIT trap ignores initial object rollback errors at78. It runs PRE_DB restore and grants at80–84. On exit0 it ignores journal reconciliation errors at86–88, calls `control fail` with errors ignored at89–90, then restarts backend/workers at101–102. `backup_control fail` calls `_normal_mode()` unconditionally after marking FAILED. | SQL command/grant success is the only condition. Object rollback can have failed while RecoveryState becomes NORMAL and writers restart. No object-byte/readback or environment-coherence proof exists. FAILED+NORMAL is not a verified recovery receipt. |
| SQL rollback or grant failure | In the main destructive EXIT trap, failure sets `restart_allowed=0` at92–94, so that invocation keeps stopped processes stopped. But the interrupted-marker branch has different semantics: it stops all processes at119–121 while `destructive=0`, `claimed=0`, `restart_allowed=1`. A failed direct SQL restore at122–124 exits into cleanup, which skips both recovery branches and restarts the stopped processes. The same occurs on journal/object rollback error at129–131. | The interrupted-run path can restart writers after unsuccessful rollback. The root host marker remains NORMAL/ACKNOWLEDGED_NORMAL; no durable fail-closed host transition is installed. A partly restored recovery singleton may be QUIESCED, NORMAL, missing or otherwise unreadable; it is not verified. |
| Successful disaster restore / authority reset | Rehydrate sets RecoveryState QUIESCED. Validation runs; `enter_quarantine` transaction sets QUARANTINED, rotates auth generation, invalidates credentials/tokens and marks RESTORED_QUARANTINED. Script removes destructive marker, marks finished, restarts backend and worker/beat at253–265. | HTTP middleware denies non-recovery routes in QUARANTINED. However, root host marker stays ordinary NORMAL/ACKNOWLEDGED_NORMAL, which admits every process role. Workers therefore restart in quarantine. Default TenantGateTask checks source-tenant migration/not-restored gates, not deployment recovery mode. For example notification tasks can still claim/send through their normal PII/source gates. Successful quarantine does not prove ordinary background writers are excluded. |

## Relevant source owners

- `scripts/restore.sh`: restart flags58–68, failure cleanup70–105, interrupted
  recovery107–138, pre-destructive stages183–223, final SQL replacement225–241,
  rehydrate/objects/validation243–251, quarantine/restarts253–266.
- `scripts/import-backup.sh`: environment installation112–116, import registration
  128–130, trap removal/work cleanup/host-lock release/exec handoff131–134.
- `backup/management/commands/backup_control.py`: fail125–128 and
  `_normal_mode`263–266; pause129–132; object rollback168–170.
- `backup/restore_services.py::prepare_restore_resume`: pre-destructive-only
  rewind and QUIESCED→NORMAL99–120.
- `backup/object_restore.py::rollback_objects`: remote delete/copy operations can
  raise; the main shell trap discards their failure.
- `backup/recovery.py::enter_quarantine`: transactional DB/auth quarantine60–130;
  it does not change the root host marker or stop worker services.
- `backup/process_roles.py`: NORMAL and ACKNOWLEDGED_NORMAL admit ALL_ROLES.
- `backup/middleware.py`: per-request DB recovery gate protects HTTP; it does not
  cover Celery processes.
- `tenant_migration/task_gate.py`: source-tenant/not-restored boundary without a
  deployment recovery-mode check. `integrations/tasks.py::_claim_log` uses PII
  fencing, not deployment recovery mode.
- `backup/host_topology_record.py`: `configuration_facts`43–63 and wrapper
  equality check around127 reject changed static environment bytes.

## Constraints for a correction

No automatic restoration of old continuity keys is safe merely because an operation
is FAILED, RecoveryState is NORMAL, or one pg_restore command exited0. A verified
selected target database, complete object rollback and coherent configuration must
be established before normal writers resume. If proof is unavailable, retain bytes,
keys/configuration copies and recovery controls; durably deny ordinary writers and
require explicit operator recovery. Do not start workers in quarantine.

A supported different-key import also needs an explicit trusted static-configuration
transition under its host operation lock; silently bypassing the topology digest is
not a correction. Changing environment before a proven source-database replacement
must not expose ordinary target traffic to incompatible keys. Any rollback must
retain the matching key set for the actual surviving database, with no blind key
flip when SQL/object recovery is uncertain.

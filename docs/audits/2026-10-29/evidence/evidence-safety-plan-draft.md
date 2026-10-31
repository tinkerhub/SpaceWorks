# Evidence safety correction draft

Status: draft only; not Stage 1 approval. Root owns EVID-S01 report changes. This lane
owns S02–S05 after box Stage 3 freezes. No production action is authorized by this file.

- S02: bind eligibility to the current retention policy when each photo is actually
  claimed, under a compatible short makerspace lock after evidence coordination locks.
  A longer policy committed before claim must prevent deletion and any new retention
  blocker. Bind the claim's actual policy/cutoff to its completion audit; do not report
  the stale candidate-list snapshot as its authority. Provider I/O remains outside
  database transactions. Changes affect future claims; an already committed expiry
  claim can already be deleting bytes and must not be automatically undone.
- S04: inspect a fresh PROMOTING finalization before creating a new EXPIRING state.
  Skipping that photo must leave no new blocker. Existing EXPIRING state remains a
  deliberate fence, including after partial provider failure; never delete it merely
  to force attachment. Demonstrate an actual concurrent promotion can finish and attach.
- S03: no release based on caller-declared photo size or absence of a finalization row.
  Release only a trusted, finalized, explicitly charged journal's validated byte size,
  independently of current transport configuration. Missing upload/finalization must
  not subtract unrelated storage. Do not invent a charge for legacy or POST rows.
  The reviewed plan must explicitly resolve current POST and recompute semantics:
  POST consumption currently has no add_storage call, while recompute can include
  declared missing-photo size. Conservative non-release protects other objects but
  legacy counts may need authoritative reconciliation; silently claiming full quota
  correctness would be false. Any recompute command change needs root coordination.
- S05: use existing IsActiveStaff (active-user plus staff-origin admission, with no
  legacy global-role ceiling) alongside the existing action/query RBAC. Upload and
  detail must refuse foreign-origin targets before any provider calls, preserve
  membership-only Inventory Manager and same-origin success, originless native/HMAC
  admission and scoped 404 behavior. Existing route target lookup already knows
  evidence-detail. Keep OpenAPI auth/error responses accurate.

Root executes all runtime tests. New fixtures must configure a real infrastructure
Host: both INFRA_HOSTS contains testserver and clients send raw HTTP_HOST=testserver
in managed mode. Do not disable TenantHostValidationMiddleware or managed quota to
make tests pass. Preserve evidence metadata immutability, all-version final/staging
expiry, real image validation, fresh claim token settlement, audit append-only state
and per-tenant source/recovery gates.

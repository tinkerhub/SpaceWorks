# Security environment forwarding — Stage 2 source handoff

2026-10-30. Implemented the exact approved bounded environment-forwarding plan. This is source
implementation and static inspection only. The root/orchestrator supplied fresh host doctor/auth
confirmation and owns separate Stage 3 execution, schema/build checks, review and QA. Those gates
have not been performed or passed by this Stage 2 lane.

The approved plan and `APPROVED` review are copied byte-for-byte beside this report as
`security-env-forwarding-plan.md` and `security-env-forwarding-review.txt`. Current whole-file SHA-256
values, entry-snapshot hashes and literal default values are in `security-env-forwarding-stage2.json`.
Hashes describe the actual dirty workspace source at handoff, not HEAD or a clean checkout, and do
not establish deployment readiness.

## Implemented change and reason

- `docker-compose.yml`: add the missing ten `PII_*` entries and `API_CLIENT_AUTH_REQUIRED` to the
  existing `backend-env` anchor. Keep its five existing HMAC/nonce entries unchanged.
- `docker-compose.prod.yml` and `docker-compose.cloud.yml`: add all sixteen existing settings to
  `backend-env` and `app-env`, respectively. Existing aliases/merges carry the settings to backend,
  migrate, worker/beat where present, cloud cron, candidate-backend and management commands launched
  through these services. No service, alias, merge or role was introduced.
- Preserve Django's existing literal defaults: encryption and enforcement off, dual-read on,
  broker `local`, cache/skew 300, nonce requirement off, two existing protected prefixes, all
  key/KMS fields blank. Compose `.env` is interpolation input, so these explicit mappings repair
  the missing process-environment boundary without changing settings or application logic.
- `.env.example`: document all sixteen values as optional comments with the actual defaults.
  `docs/self-hosting.md`: add the targeted environment reference and unreleased upgrade note.
  `docs/scoped-pii-encryption.md`: explain forwarding before the existing staged procedure.
  The key-generation, staged rollout, backfill, readiness, rotation and rollback procedures themselves
  are unchanged. No secrets were created or printed.

Previously ignored `PII_ENCRYPTION_ENABLED=True` and `API_CLIENT_AUTH_REQUIRED=True` now become
effective when the changed topology is used to restart processes. Operators must inspect saved
flags first. PII activation requires the complete existing fenced rollout with independent keys,
preflight, exclusive fleet replacement, backfill and readiness; simply flipping the flag is unsafe.
Retain the previous local wrapping key during rotation. KMS additionally requires the optional
dependency and operator IAM authority; no KMS provider success is claimed.

Client enforcement rejects unsigned requests lacking existing accepted client authentication on the
configured protected prefixes. Existing browser/publishable-client authentication and middleware
exemptions remain canonical. Leave enforcement false unless deliberately configuring signed-client
ingress. Browser clients must never receive `HMAC_SECRET`. Operator `.env`/Compose changes require
the normal trusted-record initialization before the planned restart; no initialization occurred here.

## Static scope reconciliation

Entry snapshots of the six authorized edited files were captured before editing under
`/tmp/spaceworks-security-env-forwarding-stage2-before/`. Removing exactly the newly added literal
environment entries reproduces each Compose entry snapshot byte-for-byte: 11 added entries in base,
16 in production, 16 in cloud. This also preserves all dirty image/OCI/task-generation/recovery,
mount/proxy/default lines and every bootstrap/orchestration-ready environment. No application
secrets were added to those minimal environments.

Static inspection matched every setting/default to `backend/config/settings.py` and read the existing
inventory HMAC middleware as source to keep the documentation's accepted-client exceptions accurate.
Shared anchor consumers were inspected as source only; no Compose resolution or process-effective
setting result is claimed. Scoped whitespace inspection and the `AGENTS.md`/`CLAUDE.md` byte comparison
are recorded in the JSON. No app/test source, PII broker, backup continuity/classification, host guard
input, proxy configuration, live `.env`, generated schema or frontend artifact was edited.

No tests, collection, application imports, application runtime, Docker, database/provider access,
network calls, key generation/rotation, deployment, staging, commits or pushes were performed.
Only ordinary local file/diff/hash tooling was used. The parent's already-running backend pytest
process was not touched, and its result is not evidence for this change.

## Pending root-owned Stage 3 and later gates

Use the separately approved Stage 3 plan for safe synthetic Compose JSON fixtures across base,
production and cloud, exact configured values/default parity for all application consumers, and
unchanged narrow bootstrap/probe environments. Prove process-effective Django settings and the
existing missing-key refusal/valid independent-local-key checks without production secrets or live
changes. No KMS or deployment validation can be inferred from static hashes.

Preserve prior pass/failure evidence. The parent's frozen full-backup 60-file evidence must refresh
the affected Compose hashes for this exact delta before reuse; no previous freeze was rewritten by
this lane. Root owns final schema/build/review/QA and any later runtime actions. Stage 2 source work
is complete; Stage 3 and subsequent gates remain pending.

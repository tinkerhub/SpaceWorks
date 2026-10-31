# Recovery host compatibility — separate Stage 3 writing

Status: tests written and statically read only; NOT executed, imported, collected or attested. Parent independent verification remains pending. No Docker, database, build, runtime controller/guard/checker, staging or commit action was performed by this lane.

Owned writes are limited to `backend/tests/backup/test_signed_full_host.py`, `backend/tests/backup/full_backup_host_helpers.py`, and this new report. No production source, shared documentation, historical freeze/report, or `recovery_*` / `test_recovery_*` helper/test was edited. Both owned Python modules remain below 300 lines (147 and 150 respectively).

Read-only basis: the approved restore-recovery plan and deltas, final corrections plan/delta, current final source freeze and actual wrapper/controller/input/configuration/lifecycle/marker/lock source, plus the new recovery input/transport/test helpers and related tests. Current `recovery-final-source-freeze.json` whole-file SHA256 is `b8db8cba92d819dfceae8698f9ec2c94cfed9b0f9c5bdc85636069da0185f39f`; it was not rewritten.

The obsolete helper copied only one shell script, replaced restore with a fake stub, and forged `id=10001`. That fixture could not satisfy the actual complete root-owned source guard. It also expected configuration replacement before registration, which is retired unsafe ordering. Those fake shell/identity helpers have been removed. The replacement calls the actual `scripts/restore-host.py` main and substitutes only its external transport; it exercises the actual lock, root ownership/file checks, archive preparation, marker transitions, configuration transition and lifecycle. It does not execute or claim to satisfy the shell's 25-file source guard. Actual shell/import argument dispatch and installed-layout/root-guard behavior remain the separately owned copied-install test lane; no private guard or restore stub is replaced to get these cases past admission.

The original six cases remain four functions with the original three refusal-token parameters:

| Existing case | Current meaningful assertions |
| --- | --- |
| Import refusal | Invalid real Ed25519 signature reaches static admission and refuses before full extraction, registration attempt, configuration, claim/quiescence, grant/dump/replacement or service mutation; original environment/marker/running services remain intact. Only bounded metadata is projected. |
| Import success / ordering | Externally pinned FULL signature and complete tar ledger are validated before synthetic registration under coherent OLD keys. Registration omits `--restore-id`; subsequent real registered preflights bind the returned UUID via the real prospective record. The durable blocked marker and OLD-topology writer stop precede NEW environment observation. Strict installed-key validation has no prospective record and occurs with all application writers stopped. Injected failure at the first SQL-stage management call preserves blocked state, old/new environment copies and the authenticated bundle; replacement SQL/rehydration has not started. Preview SQL is explicitly synthetic. |
| Identity bootstrap | Actual controller/lifecycle runs through synthetic SQL replacement, then actual `RestoreTransport.grants` constructs the fixed grants/identity-bootstrap command and stdin before any postreplacement management call. Payload preserves the synthetic queried target record and binds restore UUID, outer hash and signed capture identity. Strict installed preflight precedes replacement; completion reaches the real quarantine marker and starts backend only. |
| `preflight-ok` | First registered FULL token succeeds, claim occurs, changed second token refuses before quiescence, SQL/grants/dump/preview or service stop/start. Environment and marker remain unchanged. |
| `unknown` | Same changed-token refusal and no-effects assertions. |
| `compound-coordinator-ready` | Same changed-token refusal and no-effects assertions; compound coordinator token cannot authorize FULL dispatch. |

Ed25519 verification, sealed tar/member ledger checking and prospective-delegation validation are the real validators, with the existing out-of-band configured verification key. No signature/key/schema/ownership/UID/marker/lock check is mocked. Build/PG-major/storage probes, Docker/config/container responses, age copying, SQL wire responses, registration UUID response and backup-control responses are synthetic. For registered preflight the helper additionally runs the real static validator under the synthetic one-shot process environment; it does not assert real database registration or registered DB-state validation. The real grants command construction does not attest that PostgreSQL bootstrap SQL executed. No real age, PostgreSQL, Docker, broker, provider, full host restore or readiness claim follows from these tests.

The small adapter reuses `InputTransport`, `SyntheticTransport`, `marker_rig` and `isolated_host_state` read-only. It first checks the actual controller-created prospective source is regular, root-owned, single-link and exactly mode 0444, then mirrors its bytes into the fixed container namespace, including the legitimate postregistration UUID refresh; this models the read-only Docker bind view and leaves actual delegation validation intact. The isolated helper first requires `/run/spaceworks-host` to be absent and explicit disposable-container opt-in. Existing host authority is never removed, adopted or reused.

Exact new whole-file SHA256 values, pending parent verification:

| Path | SHA256 |
| --- | --- |
| `backend/tests/backup/test_signed_full_host.py` | `3c747b762d95b2d9c9df9ed039f865c45a3adeafe85835e4b2f3087ff8849fe1` |
| `backend/tests/backup/full_backup_host_helpers.py` | `cfc31b04fcfc7294b95b90a6f9ff968bff61db399276d7187f4cfe0f46ded432` |

Read-only support versions inspected:

| Path | SHA256 |
| --- | --- |
| `backend/tests/backup/recovery_input_support.py` | `3893ee77c7c7ea04926281090c419a3e611361dbc80c4c39cdfe9da2f8674e10` |
| `backend/tests/backup/recovery_transport_support.py` | `b21d7ccb63ea97a4acf4566634b938c2a6333d78a81362b8e04bc1210e37bc6c` |
| `backend/tests/backup/recovery_test_support.py` | `4db99e24c335f04a593d54c6108399df95cf575530e28323aafa06ac81c6ce32` |

Historical `backup-full-tests-freeze.json` is unchanged at `0c8c8320170b2705434da64732ff34fbd5fdbfb430891a97a4ae537c256a2cdf`. Its old host-test/helper entries deliberately remain `cd81d6766a5170e3da6c3c12d3c0cf5da8d40bb67751f3a6613e61c6527df804` and `eab3165c4b094290ac68057237cb60067174502835d937d7a209c2328bb0639d`; the parent must independently verify the new versions before changing any historical accounting. The two test files were already untracked in this shared checkout; no staging was used to make them visible.

Parent-only verification command, NOT run here, inside the prepared disposable Linux UID0 container with the full checkout mounted at `/repo`, installed test dependencies/settings, and no existing `/run/spaceworks-host` authority or bind mount:

```sh
cd /repo/backend
PYTHONDONTWRITEBYTECODE=1 SPACEWORKS_TEST_REPO_ROOT=/repo SPACEWORKS_TEST_PRIVATE_HOST_STATE=1 python -m pytest -q -p no:cacheprovider tests/backup/test_signed_full_host.py
```

Run this serially with the other private-host-state cases. No test result, syntax/import/collection success or installed-host readiness is asserted. No production source defect was established by this static compatibility-writing lane; runtime failures must be investigated rather than bypassed. Independent execution, review and QA remain with the parent.

## Parent-lane independent verification addendum

Read both replacement files against current controller/input/configuration/lifecycle source; no runtime executed. Strengthened HostTransport.observe so EVERY real controller transport phase probes the actual shared flock from an independent child with close_fds=True, requires contention, and rejects any cleanup-rollback dispatch while that lock is held. This combines the actual controller/lifecycle path with real cross-process lock proof rather than relying only on a mocked operation. The helper remains under300 lines. Current helper SHA256: `cb913135f4be18bac4786815ecd6e9b63a54147df753494d9cfccd6a50cbfe88`; lines: 163. Earlier table records the CLI handoff version, preserved historically. Runtime remains pending.

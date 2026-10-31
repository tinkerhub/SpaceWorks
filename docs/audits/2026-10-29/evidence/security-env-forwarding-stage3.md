# Security environment forwarding — Stage 3 test-author handoff

2026-10-30. Tests only, authored separately from Stage 2 after reading the approved
[plan](security-env-forwarding-plan.md), [APPROVED review](security-env-forwarding-review.txt),
[Stage 2 source handoff](security-env-forwarding-stage2.md) and JSON, the complete three Compose
files, complete Django settings, and actual wrapping check/validator/model dependencies.
This is a **static test/source freeze, not runtime pass evidence**. The root/orchestrator owns
execution, existing encryption checks, host configuration regressions, later review and QA.

## Added tests and protected behavior

- `backend/tests/test_security_env_forwarding.py`: 39 parametrized cases: 15 forwarding/effective
  settings cases, 15 minimal-bootstrap cases, and 9 enabled-local refusal cases.
- `backend/tests/security_env_forwarding_helpers.py`: explicit public synthetic inputs, private
  subprocess capture, and session cache keyed by topology and scenario. Exactly 24 Compose
  resolutions are planned (3 topologies × 8 distinct scenarios), shared across tests and settings.
- `backend/tests/security_env_settings_probe.py`: separate Python 3.12 process reading actual
  `django.conf.settings`, with exact type/value comparisons for all 16 settings. The planned
  matrix launches 79 child probes: 70 across the five main scenarios and 9 refusal probes.

Every topology uses **actual** `docker compose config --format json`, one explicit absolute `-f`,
explicit project directory/name, the `host-recovery` profile (includes candidate-backend), and an
explicit empty `--env-file`. No default override or real `.env` is loaded. The subprocess environment
is built from synthetic values plus PATH and a private HOME/DOCKER_CONFIG; inherited application,
Compose and cloud credentials are excluded. The required interpolation values follow the existing
host Compose contract test, using test-only values and a valid deterministic API-client Fernet key.
Docker/plugin absence fails; there are no skips, xfails, fake Compose resolvers or success mocks.

The five main scenarios are unset defaults, explicit blanks (the existing `:-` default semantics),
configured local values, explicit false/zero values, and configured KMS forwarding. All ten PII
settings and all six HMAC/API-required settings are compared on **14** application consumer slots:
base/prod backend, migrate, worker, beat, candidate-backend; cloud backend, migrate, cron,
candidate-backend. Fixed service names and `--role` commands bind this set. Default/configured
coverage includes the five pre-existing base HMAC entries without changing their contract.

Both orchestration-init and orchestration-ready are checked in all three topologies: **six service
instances, each with exactly five current environment keys**, including their expected synthetic
owner/runtime database addresses and scheduler. This records the actual source contract; there is
no sixth environment key in the approved source. Exact map equality refuses any added application
PII/HMAC secrets. Their bootstrap entrypoints are also pinned.

The process probe receives each resolved application environment and checkout-rooted PYTHONPATH /
DJANGO_SETTINGS_MODULE. Base Compose lacks TRUSTED_PROXY_COUNT: only this unrelated prerequisite
is supplied as `0` to the child when absent; none of the 16 target values is replaced. The real
settings loader unconditionally reads backend/.env, so the probe suppresses **only**
`environ.Env.read_env`, checks that it was called once, and additionally refuses `.env` opens via
an audit hook. Settings definitions, Fernet validation and search-key validation are unchanged.

For local wrapping only, a base Django AppConfig loads the real encryption models required by the
actual search validator. It runs no project ready hooks and never calls django.setup(). The probe
calls the existing check_pii_wrapping_configuration, with database connections and network access
explicitly refused. Valid deterministic, independent current/previous/search/API keys are public
test fixtures. Missing and malformed current/search keys must return exactly encryption.E001 and
encryption.E006; shared current/search material must return encryption.E005; valid independent local
keys produce no wrapping errors. API_CLIENT_AUTH_REQUIRED is checked as a real bool in both states.
KMS is settings forwarding only: no check/provider/IAM success is fabricated. These wrapping results
cannot establish database-aware encryption readiness, search-generation binding or rollout safety.

All subprocess stdout/stderr stays in memory. Failures expose service/key names or generic probe
failure categories, never full config, captured output, tracebacks or unexpected setting values.

## Required root-owned isolated runtime

Use an **already available** Linux image with Python 3.12 and the backend/pytest dependencies.
The outer pytest process disables plugin autoload and conftests, so it cannot initialize Django or
read a checkout dotenv before the child isolation takes effect. No DB is needed. Mount the whole
checkout (not backend alone), since the tests resolve its actual sibling Compose files.

The private feasibility tools were located statically at:
`/tmp/spaceworks-actual-host-drill/swdrill202610292203055ae1c4/tools`.
Root must supply its Linux Docker CLI 27 binary and compatible real Compose plugin. Mounting the
plugin in the standard system location is necessary because the tests deliberately use a private,
empty DOCKER_CONFIG. The Docker daemon socket is **not** required or mounted. This is the proposed
scoped runtime command, **not executed by this author** (set STAGE3_PY312_IMAGE to the root-provided
existing image; do not pull/build for this command):

```sh
STAGE3_TOOLS=/tmp/spaceworks-actual-host-drill/swdrill202610292203055ae1c4/tools
docker run --rm --pull=never --network none --read-only \
  --tmpfs /tmp:rw,mode=1777 \
  -v "$PWD:/workspace:ro" \
  -v "$STAGE3_TOOLS/docker:/usr/local/bin/docker:ro" \
  -v "$STAGE3_TOOLS/cli-plugins/docker-compose:/usr/local/lib/docker/cli-plugins/docker-compose:ro" \
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  -w /workspace/backend "$STAGE3_PY312_IMAGE" \
  python3.12 -m pytest -c /dev/null --noconftest -p no:cacheprovider \
  -q tests/test_security_env_forwarding.py
```

Only the root executes that command, after providing the fixture/runtime. The daemon runs the
outer isolated test container; Docker inside it only resolves config. No Compose up/run/build,
application startup, deployment, shared database access or network is part of these new tests.
Root separately owns existing encryption/check and host-config regressions with their normal
appropriate harness, without overlapping a shared database suite. The parent's running 317-test
process was untouched and provides no result for these newly uncollected files.

## Freeze and validation

The companion [JSON](security-env-forwarding-stage3.json) contains exact whole-file SHA-256 hashes
of the approved sources, test files, inputs and this report; source hashes describe this dirty
checkout rather than HEAD. The six approved Stage 2 implementation hashes and its settings reference
hash were compared with the Stage 2 manifest. Static AST parsing, the under-300-line guard, explicit
untracked-file whitespace checks and scoped git diff --check passed. Neither test modules nor
application modules were imported/executed. No runtime/test/collection/Docker/network, production
edits, staging or commits were performed. Previous evidence and the parent's 60-file freeze were
left intact. Root must record actual results separately and reconcile hashes if any source changes.

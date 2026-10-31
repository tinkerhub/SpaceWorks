# Seekable promotion: finite Stage3 test writing only

Scope authorized by the user: the two new tests and minimal helper below, exact
`create_final_from_staging` mock adapters in three existing tests, and this report.
Read `/tmp/spaceworks-seekable-promotion-plan.md`, its `APPROVED` review text,
the four current source files, and durable `seekable-promotion-stage2.md`.
The parent's supplied finding is that default boto checksum handling sought a
nonseekable StreamingBody before SQL. No private worker logs were read.

Only source/text reads, stdlib AST parsing, hashing, line counting, whitespace
checks and scoped diff inspection were performed. No project imports, collection,
tests, database access, Docker, build, runtime, staging, commit, source edits,
other-lane helper edits or source-freeze updates occurred. Existing host/Docker
boundary test-writer work was preserved. This is test code, not passing-test or
successful-publication evidence. No additional production bug is established by
this static-only work; execution and independent review remain parent-owned.

## Coverage written

- Unit source is an actual `botocore.response.StreamingBody` over a generated,
  nonseekable `RawIOBase`, never a BytesIO stand-in. The production promotion
  function executes in the tests. Real `TemporaryFile(mode="w+b")` handles are
  observed in place, with regular-file descriptor, mode 0600, unlinked inode,
  seekability, write sizes, close attempts, closed state and unusable fileno checks.
  The fake PUT actively consumes/rewinds/consumes the body in bounded reads, checks
  exact length, bytes type, content type and `IfNoneMatch="*"`. Source reads and
  spool writes are recorded with a seven-byte chunk size to expose boundaries.
- Exact size/SHA success includes empty and chunk boundaries. Under/oversize and
  wrong SHA refuse before PUT; oversize bytes are rejected before being spooled.
  Malformed/partial facts refuse before provider access or tempfile allocation.
  Legacy `storage.copy_archive(source, target)` exercises valid GET ContentLength
  bounding, and missing, noninteger, boolean and negative bounds refuse safely.
- Source OSError, tempfile allocation/write errors, SDK failure and conditional
  409/412 all check close attempts for every acquired handle. Both close-error
  and ordinary-close cases retain the primary error/cause. Verification subtype
  survives failing closes. Close failure after successful PUT is typed too.
  The fake winner stays unchanged and the primitive never deletes remote bytes.
- The opt-in S3 file creates a unique `seekable-stage3-<uuid>` bucket on the
  parent's dedicated local port 59200 endpoint, enables versioning and uses the
  production boto client factory. It asserts the default request checksum setting
  is `when_supported`. GET/PUT observers delegate actual SDK calls unchanged;
  checksums are neither replaced nor disabled. Staging is uploaded by a real PUT
  from disk; real nonseekable GET bodies feed production promotion and real final
  PUT. Full streamed GET proves exact size/SHA. Both handle classes close. A winner
  written by another actual PUT keeps its body, version ID and sole retained
  version on conditional refusal. Wrong size/hash cause zero final PUTs and no
  final versions or delete markers. Staging remains intact throughout these tests.
  Cleanup removes every version/delete marker only from each newly owned bucket,
  then removes that bucket; no shared prefix is purged. Fixtures are synthetic.
- Protocol and reconciliation tests reuse the existing signed `_prepared` fixture
  and real `persist_pending`, ledger transitions and promotion transaction. Remote
  boundaries alone are doubled; SQL immutability and promotion guards remain real.
  They assert immutable expected-size/SHA forwarding, staging-verified state before
  publication, final readback before availability, successful ledger promotion and
  post-commit staging cleanup. Injected final readback failure leaves the ledger
  staging-verified and neither archive nor ledger AVAILABLE, with no cleanup.
- The makerspace case uses real request creation, `run_archive`, operation lock,
  lease, claim/completion/failure transitions, and a synthetic builder-result
  fixture. Expected facts come from its actual disk file size and bounded hash
  calculation. Both remote verifications and final creation must receive those
  facts. Failed final readback cannot become AVAILABLE; successful completion
  persists exactly the captured size/SHA. This is a caller-boundary test, not
  proof of actual age encryption, archive building or a full backup.
- Existing adapters only accept `**kwargs` and assert exact forwarded facts and
  locators while retaining their original copy/event behavior and all original
  assertions. No skip/xfail or guard bypass was introduced. The operation-lock
  file was already untracked work; its pre-existing contents were retained.

## Parent-only finite execution commands (NOT RUN)

From `backend/`, in the parent's supported Python 3.12+ environment with this exact
source/test snapshot and installed requirements, run serially:

```bash
python -m pytest -q --create-db \
  tests/backup/test_seekable_promotion.py \
  tests/backup/test_reconciliation_operation_lock.py \
  tests/backup/test_reconciliation_e5.py \
  tests/backup/test_promotion_concurrency_e10.py
```

Required base environment: `DJANGO_SETTINGS_MODULE=config.settings` (also set by
pytest.ini), `SECRET_KEY` set to a local test value, `DEBUG=True`,
`TRUSTED_PROXY_COUNT=0`, `DATABASE_URL` pointing only to the parent's isolated
PostgreSQL 16 database using its test owner with CREATEDB, and a nonempty valid
Fernet `API_CLIENT_ENC_KEY`. Load the complete installed app set, including backup
and makerspaces. The existing pytest fixtures supply fresh signing/verification
and audit keys, isolate operation directories and use LocMem cache. No real
producer-capability/restore credentials are required by these scoped tests.
Do not use a production DB or run alongside another pytest process on that DB.

Run the S3 primitive lane separately, from `backend/`:

```bash
SPACEWORKS_TEST_S3_DISPOSABLE=1 python -m pytest -q \
  tests/backup/test_seekable_promotion_s3.py
```

In addition to base settings required for Django startup, the parent must supply
these exact dedicated variables to that process (credentials are intentionally
not recorded here):

- `SPACEWORKS_TEST_S3_ENDPOINT_URL=http://127.0.0.1:59200` for host execution, or
  `http://host.docker.internal:59200` when parent container execution requires it.
  `localhost` is accepted too. Port 59200 and an explicit local endpoint are
  required; there is no implicit AWS endpoint or shared bucket fallback.
- `SPACEWORKS_TEST_S3_ACCESS_KEY_ID` and `SPACEWORKS_TEST_S3_SECRET_ACCESS_KEY`:
  parent's dedicated disposable endpoint credentials, with create/delete-bucket,
  versioning, PUT/GET, list versions and delete-version permissions.
- Leave `AWS_REQUEST_CHECKSUM_CALCULATION` and profile-based checksum overrides
  unset so the unmodified production factory uses SDK default `when_supported`.
  Do not set checksum-disable environment/configuration. No production bucket,
  data, keys or credentials may be used. Missing opt-in fails explicitly; these
  tests do not silently skip. This lane has no django_db mark or PG/age backup
  proof, although Django settings still require a syntactically valid DB URL.

The S3 lane proves only primitive publication if it passes. Parent must independently
read and freeze these bytes, rebuild a NEW genuine OCI image, restart BOTH isolated
backend and worker on it, and run a NEW actual backup producer before claiming full
backup success. Do not resume the stale image. Existing failed evidence remains
untouched. No restore SQL has been performed here; parent owns any later restore.

## Exact current owned test bytes

All paths below are under `backend/tests/backup/`. Whole-file hashes include any
pre-existing content in the three adapter files and do not claim authorship of it.

| File | Lines | SHA-256 |
| --- | ---: | --- |
| `test_seekable_promotion.py` | 232 | `83351dc60f8a74501a7190303fa579dbec018963fa48ce9b1574f069180c5c3d` |
| `test_seekable_promotion_s3.py` | 190 | `d268ed06f3a468a8b639a46649a22d14dfb126e10baf6714a8c53e56dc613fa2` |
| `seekable_promotion_helpers.py` | 171 | `8f046523cf7d101d53d83f138f1fe71f476e0b21b5d92b025d9e3c818b768ed5` |
| `test_reconciliation_operation_lock.py` | 152 | `a44f3c3d579edf7f9dedde6e73f88db98b2c9bb9b6dedf317536d23bae55195a` |
| `test_reconciliation_e5.py` | 177 | `954068f23249377dbdfc9eca3e78f7cf809573e5c807f3da08308d37bd0655e5` |
| `test_promotion_concurrency_e10.py` | 75 | `175812052d693e1ed5cfa4366e924bfd11dd8f186c69175cc7b355dc1d8743d8` |

## Unchanged Stage2 source identities and facts

All paths below are under `backend/apps/backup/`; hashes still match Stage2.

| File | Lines | SHA-256 |
| --- | ---: | --- |
| `storage_promotion.py` | 176 | `a944b057138fd2510357665a548a2c2126eea6f61f7759573727de4089e4b4a3` |
| `artifact_protocol.py` | 37 | `2e65e2c5b76bfebe73cc9e467e43a369b44ebd2f7e075edfc1d77a5521781fe2` |
| `reconciliation.py` | 140 | `bdaf87285bec7cfd62622097e5871d9b2ec96e34f65d102239af7d679677535c` |
| `services_archives.py` | 263 | `b02860b19d6c02af9eb2e6685abaef95b36558bce7e2a9103a7328caba1b530f` |

Text/AST inspection confirms the primitive's paired-fact validation before provider
access, `min(CHUNK_SIZE, remaining + 1)` read bound, private tempfile rewind,
ContentLength and create-only PUT. Legacy length remains GET-derived. Protocol
forwards ledger expected size/SHA; reconciliation forwards row expected size/SHA;
makerspace runner forwards captured file size/SHA. All retain final readback.
No production checksum, guard, SQL or cleanup changes were made by this stage.

## Static verification commands executed

Run at repository root. The stdlib script parses file bytes without importing them,
checks ceiling/whitespace/no skip-or-xfail and compares every hash to this report.
It also checks the three production callers still supply both keyword facts.

```bash
python - <<'PY'
import ast
import hashlib
import re
from pathlib import Path
report = Path('docs/audits/2026-10-29/evidence/seekable-promotion-stage3.md').read_text()
rows = re.findall(r'\| `([^`]+\.py)` \| (\d+) \| `([a-f0-9]{64})` \|', report)
assert len(rows) == 10
for index, (name, lines, expected) in enumerate(rows):
    root = 'backend/tests/backup' if index < 6 else 'backend/apps/backup'
    path = Path(root) / name
    raw = path.read_bytes()
    tree = ast.parse(raw, filename=str(path))
    assert len(raw.splitlines()) == int(lines) <= 300
    assert hashlib.sha256(raw).hexdigest() == expected
    assert raw.endswith(b'\n') and all(line.rstrip() == line for line in raw.splitlines())
    if index < 6:
        assert not any(isinstance(n, ast.Attribute) and n.attr in {'skip', 'skipif', 'xfail'}
                       for n in ast.walk(tree))
    elif name != 'storage_promotion.py':
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == 'create_final_from_staging']
        assert len(calls) == 1
        assert {k.arg for k in calls[0].keywords} == {'expected_size', 'expected_sha256'}
    print(path, lines, expected)
PY

git diff --check -- \
  backend/tests/backup/test_seekable_promotion.py \
  backend/tests/backup/test_seekable_promotion_s3.py \
  backend/tests/backup/seekable_promotion_helpers.py \
  backend/tests/backup/test_reconciliation_operation_lock.py \
  backend/tests/backup/test_reconciliation_e5.py \
  backend/tests/backup/test_promotion_concurrency_e10.py \
  docs/audits/2026-10-29/evidence/seekable-promotion-stage3.md
```

Both completed successfully as static checks only. The stdlib whitespace check
covers untracked tests too; git diff alone omits untracked paths. The report's own
whole-file hash/line count is returned separately, avoiding a circular self-hash.

## Parent-lane independent readback

All Stage2/Stage3 CLI writers closed0. Independently read the four source files, real SDK/source/temp handle paths, caller facts and all six test/helper/adapter files. The tempfile observation helper now takes an explicit live chunk bound, preserving its strict unit7-byte/live64KiB checks without relaxing production limits. All10 Python paths were AST parsed, hash/ceiling checked only. Exact current bytes are in seekable-promotion-freeze.json. No tests/runtime/provider actions occurred here. Prepared full-backend input script maps existing private AWS settings into the three explicit SDK test aliases; no secret is written to these source inputs/logs. Actual SDK/publication and whole backup remain parent runtime gates.

# Host Docker boundary: finite Stage 3 test writing

Written 2026-10-30 after the approved test-only Stage 2. Runtime verification
belongs to the parent. This report records source inspection and test writing,
not a passing test run.

Only these two new files were written:

| File | Lines | SHA-256 |
| --- | ---: | --- |
| `backend/tests/test_host_operator_docker_boundary.py` | 248 | `60300ea055fa3227baaf3d217e806d71e7328f4d1dbc018a4a62f22b272eb830` |
| `docs/audits/2026-10-29/evidence/host-docker-boundary-stage3.md` | Final manifest | Final manifest |

The completion manifest supplies this report's own line count and digest to
avoid a self-referential digest. These hashes are observations, not a source
freeze or signature authority.

The module fixture reads the actual complete snapshot using `read_sources`
with `Path(__file__).resolve().parents[2]`. With the entire checkout mounted
at `/repo`, this resolves to `/repo`, including root-level host scripts.
No arbitrary synthetic source map stands in for the positive checkout test.
Each negative test starts with `dict(snapshot)` and replaces copied frozen
`SourceFile` records. No production module is imported or executed by the tests.

The positive case requires the exact two exemption paths, the actual 25-entry
wrapper declaration, successful shared validation, no remaining Docker
offenders, the original `scanned > 100` floor, and exactly those two raw app
regex matches. The regex fixture reads the existing guard's `re.compile`
argument as an AST literal. The tests call the same public
`validated_docker_exemptions` and `scan_docker_boundary` used by the guard;
they do not invoke private guard functions or recreate its safety validator.

Finite negative fixtures cover:

- All seven actual operator modules imported by existing request/view, worker
  and management sources. Nine bounded statements cover aliases, absolute and
  relative imports, from-package members, actual exported members, constant
  `__import__` targets/fromlists/relative levels, and aliased
  `importlib.import_module` targets with a constant relative package anchor.
- A second root controller importing each operator module, despite declaring
  its own Linux/UID-0 check. Only the exact approved controller has the exception.
- Quoted Docker invocations in ordinary apps, ordinary backup code, a shared
  pinned helper and all five nonexempt operator helpers. Pinned mutations get
  refreshed copied digests before scanning; the result must name precisely the
  changed app path. This protects against a package-wide or closure-wide exemption.
- Wrong digest, missing/extra/wrong declared paths, missing source records,
  noncanonical keys, linked/nonregular/noncanonical source facts, checker
  reviewed-literal drift, executable package initialization, and an unreviewed
  transitive controller dependency.
- Wrapper Linux/UID checks, directory/file root ownership, mode and link checks,
  hash comparison, isolated guard/controller flags and pycache isolation.
  Moving the entire guard after controller launch must refuse. Removing,
  weakening or moving the controller's root check after transport construction
  must refuse even after refreshing the copied controller digest.

The mutation utility changes only in-memory `EXPECTED` literal data. It never
writes the real wrapper, controller, helper, checker, source freeze or digest.
Refusals match the intended diagnostic wherever available. Existing bare
assertions use an exact empty-message match after a single controlled mutation;
missing source matches the particular `KeyError` path. No broad exception tuple,
skip, xfail, new scanner framework or production permission/signature change
was introduced.

This is a statement regression guard, not a formal RCE/reflection proof.
Computed/reflected imports can evade static analysis; root ownership, isolated
launch and actual socket authority remain runtime protections.

AST parsing of the new test file and the formatted import fixture statements
completed. Text inspection confirmed every wrapper mutation anchor occurs
exactly once, the Python file stays below 300 lines, and it has no trailing
whitespace. No test/helper or production import, collection, test execution,
Docker, DB, build, runtime checker, staging or commit occurred.

Read-only basis:

| Basis | SHA-256 |
| --- | --- |
| `/tmp/spaceworks-host-docker-boundary-plan.md` | `5b1de9b4d0b1d84a0629cd26a17f93f97dd89fbfe10ef06a4e98c35f09aaed11` |
| `/tmp/spaceworks-host-docker-boundary-plan-review.txt` (APPROVED) | `778d6af16f00d9f59df9176feb9f97f05ca06f1468266a18cd32cad56d9b23b0` |
| `evidence/host-docker-boundary-stage2.md` (read in place) | `119cde5964958389aeb19cea035ab568e6f563499906030563204d5fd3531fc2` |
| `backend/tests/host_operator_boundary_helpers.py` (263 lines) | `253f80d9a1c5a500f314884e88075bdf5f5453febabe0afa4cdc25a83c25dade` |
| `backend/tests/test_host_update_boundary.py` (73 lines) | `54ed1320955ebb373e5b55ec33d7b49baf4f5de64878da4537d5a8ae30bd3f9f` |
| `scripts/restore.sh` | `9983bf0ea7e999f9ecd539c8e9fdaad15499637740175f0c2cda4f8dd652fa41` |
| `scripts/restore-host.py` | `f971c644b459bddfe5c461f555f48936e963afa8abfcd384a894a44d2c9a12d3` |
| `scripts/check-restore-host-bundle.py` | `19a289c7022db1f528080f25c138f72cd665fb02aeaddd3648424a498f9ad6c6` |

Finite parent-only command, inside the parent's Python/pytest environment with
the whole checkout already mounted at `/repo`; not executed here. Disabling
plugin autoload and conftest loading keeps this source-only invocation apart
from Django/DB fixtures. Both existing and new guard modules remain selected.

```sh
cd /repo/backend && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/repo/backend python -m pytest -q -c /dev/null --noconftest -p no:cacheprovider tests/test_host_update_boundary.py tests/test_host_operator_docker_boundary.py
```

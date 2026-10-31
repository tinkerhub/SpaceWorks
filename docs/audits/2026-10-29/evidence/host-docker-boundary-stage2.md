# Host Docker boundary — approved Stage2 implementation

Stage2 only, 2026-10-30. Stage1 was APPROVED in the named review below.
The parent owns subsequent Stage3 mutation tests, execution, full audit and
bounded fixes after the review gate. This writer did not advance those stages.

## Owned files

| File | Lines | SHA-256 |
| --- | ---: | --- |
| `backend/tests/host_operator_boundary_helpers.py` (new) | 263 | `253f80d9a1c5a500f314884e88075bdf5f5453febabe0afa4cdc25a83c25dade` |
| `backend/tests/test_host_update_boundary.py` (existing) | 73 | `54ed1320955ebb373e5b55ec33d7b49baf4f5de64878da4537d5a8ae30bd3f9f` |
| `evidence/host-docker-boundary-stage2.md` (new) | 131 | Self-digest in completion manifest |

The completion message records this report's final line count and SHA-256;
embedding its own digest here would create a self-referential hash. These are
observational hashes, not a new source freeze or production identity authority.

## Implementation and protected behavior

The existing no-web-Docker test passes its unchanged regex and a copied source
snapshot to `scan_docker_boundary`. That pure function first validates the
operator boundary, then scans every nonmigration/non-pycache Python app source.
Only `backend/apps/backup/host_restore_transport.py` and
`backend/apps/backup/host_restore_configuration.py` receive exemptions, and only
after successful validation. The existing scan floor above 100 files, known
Docker-pattern witness and failure message remain. All three existing test
functions retain their purposes. The all-Compose socket-ban function, Compose
file discovery and host update-script witness body are unchanged.

The helper fixes seven operator module paths:
`backend/apps/backup/host_restore_{transport,configuration,admission,files,prepare,lifecycle,resume}.py`.
It independently fixes the exact approved 25-path set, checks the current
checker's `REVIEWED_PATHS` literal and wrapper's `EXPECTED` literal against it,
and verifies the SHA-256 of every closure file. Duplicate/extra/missing entries
cannot satisfy those literal/set checks. Snapshot capture and validation require
regular, canonical, single-link source files; capture also checks directory
parents. Local checkout ownership need not be root: the runtime wrapper's root
ownership and mode enforcement are inspected structurally as source data.

The graph traverses all Python source under `backend/apps`, `backend/config`,
`backend/scripts` and root `scripts`, including migrations and package inits.
It resolves absolute/relative imports, package-member imports, package prefixes,
local package initializers, literal `__import__` (including constant fromlists
and levels), and literal `importlib.import_module` targets with common aliases
and constant relative package anchors. The controller's computed transitive
local closure must equal the approved 25 paths. `apps/__init__.py` and
`apps/backup/__init__.py` must remain empty or contain only string expressions.
Incoming edges to the seven operator modules are allowed only from those seven
and exact `scripts/restore-host.py`. Normal app callers may still import shared
nonoperator modules among the 25. No entire-package or 25-file Docker exemption
was added.

AST checks match the actual executable wrapper privilege condition and the
directory/file/hash loops, including Linux, effective UID zero, owner UID,
protected mode bits, single-link regular files and the bounded `/tmp` ancestor
exception. They require a failing `SystemExit` handler. Shell structure requires
the guard to execute under `set -euo pipefail` before every controller launch;
all four launches retain `-I -B -X pycache_prefix=/dev/null`. The controller's
top-level `main` guard must raise on Linux/UID failure before every direct
`RestoreTransport` construction, and such constructions must belong to `main`.
Unused constants elsewhere cannot satisfy these structural checks.

## Immutable Stage3 injection interface

`read_sources(root)` returns a `MappingProxyType` of frozen `SourceFile` records
containing copied bytes plus canonical/regular/link metadata. It reads source
data and never imports production modules. `validated_docker_exemptions(sources)`
and `scan_docker_boundary(sources, docker_call)` only consume that data and do
not access the filesystem or mutate their inputs.

Stage3 can copy the mapping with `dict(snapshot)` and replace a record using
`dataclasses.replace(record, data=...)`. Added callers can use new `SourceFile`
records. The existing test consumes the same pure scan function, so mutations
can exercise both import isolation and Docker-pattern scanning in memory.
To reach a structural check beneath SHA validation when mutating a closure
member, Stage3 can consistently update the copied wrapper's corresponding hash
in memory. Historical on-disk source/test freezes and digests remain unchanged.
There is no copy-world framework, production execution or new root mechanism.
No negative mutation tests were written in Stage2.

This is a regression surface boundary, not a formal reflection/RCE proof.
Computed dynamic imports are not generally decidable; arbitrary reflection,
runtime path manipulation and adversarial interpreter behavior are outside this
static guard's claim. Actual root-only launch, filesystem trust and daemon
socket authority remain the runtime boundary.

## Source basis and read-only observations

| Named basis | Lines | SHA-256 |
| --- | ---: | --- |
| `/tmp/spaceworks-host-docker-boundary-plan.md` | 13 | `5b1de9b4d0b1d84a0629cd26a17f93f97dd89fbfe10ef06a4e98c35f09aaed11` |
| `/tmp/spaceworks-host-docker-boundary-plan-review.txt` (APPROVED) | 14 | `778d6af16f00d9f59df9176feb9f97f05ca06f1468266a18cd32cad56d9b23b0` |
| `scripts/check-restore-host-bundle.py` | 119 | `19a289c7022db1f528080f25c138f72cd665fb02aeaddd3648424a498f9ad6c6` |
| `scripts/restore.sh` | 72 | `9983bf0ea7e999f9ecd539c8e9fdaad15499637740175f0c2cda4f8dd652fa41` |
| `scripts/restore-host.py` | 96 | `f971c644b459bddfe5c461f555f48936e963afa8abfcd384a894a44d2c9a12d3` |

The exact reviewed closure is the seven fixed operator paths above, the
controller, both package initializers, and these fifteen shared backup files:
`full_format.py`, `host_capability_journal.py`, `host_capability_types.py`,
`host_marker.py`, `host_marker_file.py`, `host_pointer.py`,
`host_private_file.py`, `host_run_ledger.py`, `host_supervisor.py`,
`host_topology_record.py`, `inplace_marker.py`, `inplace_recovery_facts.py`,
`operation_lock.py`, `restore_manifest_facts.py`, `topology.py`.
All backup names here are relative to `backend/apps/backup/`.

Read-only source inspection found identical 25-path declarations in checker
and wrapper. All 25 source byte hashes matched the existing wrapper declaration;
all 25 were canonical regular files with link count one. The helper's focused
safety AST block equals the current wrapper's executable safety AST block.
These observations did not invoke the helper or controller.

Syntax-only AST parsing covered 1,929 app files, 15 config files, nine backend
script files and fourteen root script files (1,967 total), plus both owned Python
files. `git diff --check` for the owned paths found no whitespace errors.
Repository/global workflow instructions were read for orientation; source
analysis remained limited to the approved roots and named source/guard files.

## Scope and deferred verification

Only the three owned paths were written. No production file, source/test freeze,
digest declaration, other test or guard was edited. The workspace already
contained unrelated changes; those were not modified, staged or committed.
No staging or commits occurred. No production/test imports, test collection,
test execution, Docker, database, build, checker/controller invocation or helper
execution occurred. Read-only standard-library scripts parsed source ASTs,
inspected file metadata and computed observational hashes.

The parent must run the existing guards and subsequent Stage3 mutation tests,
then its authorized broader audit and review. Stage2 makes no runtime or test
pass claim.

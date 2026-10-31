# Plain-tar path conflicts — bounded Stage3 writing handoff

2026-10-30. Tests written and read statically only: **unexecuted, unimported and uncollected**. Parent owns execution, independent review and QA. This lane ran no application/runtime helper, test collection, tests, DB, Docker, build, staging or commit operation.

Only new writes:

- `backend/tests/backup/test_restore_tar_path_conflicts.py`
- This evidence note, `docs/audits/2026-10-29/evidence/recovery-tar-paths-stage3.md`

Read AGENTS.md, global `~/.claude/CLAUDE.md`, DEV-WORKFLOW, relevant backup invariants, actual restore/private-file helpers and existing tar-screen/root-lane support. The explicit bounded Stage3 instruction leaves runtime steps to the parent. No production source, other recovery tests/helpers, historical report or freeze was edited.

## Written behavior

Seven parameterized cases use genuine regular/directory `TarInfo` entries and `io.BytesIO` file bodies in actual plain tar files. Required `manifest.json` and `keys/env.json` contain real small JSON bytes and pass through the production bounded projection. No parser, trust, ownership or path check is replaced; every case calls the existing `require_linux_root()` assertion. The private-file writer defaults to requiring root ownership, so the parent must use Linux UID0 rather than bypass that precondition.

- `payload/a` as a regular file with `payload/a/child` is refused in either order by actual `project_metadata`, expecting typed `RestoreHostError` with the path-conflict message. Both metadata files precede these conflicts, checking that screening continues beyond them.
- A regular `keys` conflicts with required `keys/env.json` in either order. Assertions allow exactly the bounded metadata already projected before refusal; no ordinary payload is written. An unrelated payload precedes each conflict to exercise metadata-only projection.
- Explicit directories before descendants, explicit directories after descendants (also reversing directory order), and entirely implied parents pass through actual `project_metadata` and `extract_bundle`. Assertions compare the complete projected and extracted trees, empty explicit directories, nested/sibling file bytes and metadata byte equality.

Existing harmless long `GNU.sparse`-looking path-value and large serialized-cap cases remain in `test_recovery_tar_screen.py`; this file does not duplicate or edit them. These are file/metadata-boundary assertions, with no Django model or database operations in their bodies.

The approved correction advances rejection into bounded metadata screening. Previously the conflict failed during fresh private extraction, before configuration/service/SQL effects. This note makes no live-corruption, deployment-readiness or executed-success claim.

## Exact static handoff

| File | Lines | Whole-file SHA256 |
| --- | ---: | --- |
| `backend/tests/backup/test_restore_tar_path_conflicts.py` | 104 | `9420c9ad45d9f607051fca136c0114dc4ff1ce3c084536fee5aa0eafb8d3940e` |

Read-only source snapshot: `backend/apps/backup/host_restore_files.py` SHA256 `4adb25d8febcaf651813a186a1e3070723dcc53c650929b74dae1d3f7768e8cf`. Reused `recovery_test_support.py` SHA256 `7ab7f02af9626cb7df02ed2f5897a740f1e8715476afd3631527500725d17653`. These observations do not rewrite or extend any freeze.

One parent-only verification command, **not run here**, from `/repo/backend` in the prepared disposable Linux UID0 environment with installed test dependencies/settings and protected pytest temporary ancestry. Run serially with the parent's other lanes:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider tests/backup/test_restore_tar_path_conflicts.py
```

Only static reads, SHA256 and line counting support this handoff. No syntax/import/collection success, pass count or runtime result is asserted.

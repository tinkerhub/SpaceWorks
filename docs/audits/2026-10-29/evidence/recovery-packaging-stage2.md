# Recovery packaging Stage 2 handoff

2026-10-30. Implemented the independently APPROVED bounded packaging add-on, including the appended parent ownership clarification. This is source implementation with static reconciliation only. Parent owns Stage 3 execution, later review/QA gates, operator-document integration and the <=2 heavy-job budget. No deployment/readiness or runtime pass is claimed.

Read AGENTS.md, global ~/.claude/CLAUDE.md, docs/DEV-WORKFLOW.md, relevant backup/deployment invariants, the approved /tmp packaging plan/review and evidence/recovery-stage2-independent-corrections.md. The direct Stage2 assignment and its explicit restrictions control this execution lane; no additional agent/CLI review or runtime work was launched.

No tests or collection, application imports, actual checker/guard/helper execution (including --help), DB access, Docker/provider commands, builds, privilege/runtime actions, staging, commit or push occurred. Only the four authorized source files below and this report/final freeze were edited. Parent-owned application modules, test files, principal/hardlink checks, rollback/scanner/UI/image sources and shared operator docs were left untouched.

## Implemented behavior and production reason

- The 119-line stdlib-only checker reads the exact existing PY_GUARD heredoc as data, AST-extracts its one literal EXPECTED dictionary, rejects duplicate/noncanonical/unknown/traversing paths and malformed digests, and requires the exact reviewed 25-file closure. It checks regular, single-link files and directory components without following symlinks, then hashes all 25 files. It prints the reviewed path list only after complete success. The caller's fixed runtime entries and the checker itself receive structural preflight; their content is not opened by that structural pass. No .env/credential, network, application or backend-tree discovery is involved. The pinned release plus existing capability-covered wrapper remain the authority; no keyring/signature scheme was added.
- install_staged_host_bundle captures checker output/status before appending those 25 paths to its 34 fixed entries. Every fixed entry and dependency is validated before it creates its host-config backup directory or replaces runtime files. There is no unchecked process substitution, eval or second copy-set discovery. Nested paths remain intact, including both different __init__.py files. deploy/init-object-buckets.sh, frontend/nginx.conf and all 33 previously present fixed entries remain. The earlier update.sh database-backup/image sequence is unchanged; this guarantee concerns the bundle installer, not every earlier updater action.
- Replaced-file backups still use cp -p at the original relative path. Python/checker/config/PowerShell files install0644; shell files install0755. Newly created code directories use0755. UID0 replacement files are explicitly root:root; new directories belong to invoking root. Non-root replacement copies retain existing owner/group before content replacement; new files belong to the caller. Existing live directory ownership/modes are not converted, and no new recursive chown or private-state migration was added.
- Fresh install.sh requires the checker and wrapper and captures successful validation of the same complete guard contract before moving the extracted tree or launching the new updater. Extraction uses --no-same-owner so archive UID metadata cannot defeat root ownership on a UID0 fresh install. Only the staged exact guarded files/checker and their code-directory modes are normalized, along with the existing shell entrypoints. The existing non-root fresh-install ownership handback is unchanged. install.sh remains at its existing 300-line ceiling; explanatory comments were shortened/removed to accommodate the bounded preflight without moving installer behavior.
- restore.sh checks Linux UID0, all 25 file hashes, root ownership, regular/single-link files, no group/world write bits, the wrapper's own file metadata, and all code directory ancestors before any host-code import. Directories must be root-owned and protected; the sole writable-ancestor exception is literal root-owned mode1777 /tmp above an isolated fixture, never the fixture/code directory itself. Symlink ancestors and other sticky directories are refused. The existing private authority policy is unchanged.
- Every new checker invocation and the guard/controller invocations use python3 -I -B. Controller invocations additionally use -X pycache_prefix=/dev/null: attested source must not be bypassed by pre-existing local bytecode, and -B prevents cache writes. Installed-layout help also requires this supported root-owned Linux layout. No-effects behavior is still a Stage3 proof obligation.
- Source search found no additional owner of runtime-bundle copying/preflight that needs synchronization. Proxy refresh owns separately protected operator-editable Caddyfiles and was left alone. No release/workflow packaging expansion was made.

## Preserved independent corrections

scripts/restore-host.py still explicitly requires Linux and rejects NORMAL/ACK compound reservation/fence/not-restored declarations before preparation/effects. host_restore_prepare.py still delegates prospective continuity for already-registered signed-full DISASTER archives as well as imports; disaster remains reset/quarantine. Neither file was edited here. EXPECTED was regenerated from their current bytes; the dependency path set remains exactly the historical 25 paths. Only these two dependency digests changed from the historical guard:

- `scripts/restore-host.py`: `f971c644b459bddfe5c461f555f48936e963afa8abfcd384a894a44d2c9a12d3`.
- `backend/apps/backup/host_restore_prepare.py`: `c392c3a70f6c5c97578454a2951b18b0430f8df2036005f85654894f0fcbf5f8`.

## Exact source and copy inventories

The historical recovery-source-freeze.json is preserved byte-for-byte. Its current whole-file SHA256 is `d72451f12ec83a9444ce2c05e91fbb836ac379b187b7e0423b52450931d1d109`.

The combined recovery-final-source-freeze.json records current whole-file bytes for all prior43 source paths, the add-on paths and all25 guarded dependencies: 59 distinct source files. It separately records the pinned copy set of 34 fixed +25 guarded =59 files, each with current SHA256 and intended installed mode. These two 59-file inventories have different membership. The checker is the only added fixed runtime entry. This freeze includes existing dirty source changes and does not assert authorship of them.

Final freeze SHA256: `51086a0c5aac6a6be65f82e5c301ab5ab1978cf1937aaacc7a4b28e0ef27c9cc`.

| Add-on source path | Lines | Whole-file SHA256 |
| --- | ---: | --- |
| `install.sh` | 300 | `0e9fc5e775413b9b85fa96ec092ec3c4b15f2cf91da1a7d5a0c675bfc646c554` |
| `scripts/install-host-bundle.sh` | 63 | `a34e6467928ff6420ebbf3147a2739488c0bb291db414159edf3fe30089dc1d6` |
| `scripts/check-restore-host-bundle.py` | 119 | `19a289c7022db1f528080f25c138f72cd665fb02aeaddd3648424a498f9ad6c6` |
| `scripts/restore.sh` | 72 | `295256b6a6fa31acc7384da2c1089ee143e4999b3aac1b50305784bfa21f0b84` |

The exact 25 guarded paths below install0644 and must remain regular single-link root-owned non-group/world-writable files for restore/import. No executable bit is required: the controller is invoked through Python.

| Guarded path | Current SHA256 |
| --- | --- |
| `backend/apps/__init__.py` | `01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b` |
| `backend/apps/backup/__init__.py` | `87e7763152dbb2a14b12826c8015a1fa82467090df82e11e47622b6879f0fe75` |
| `backend/apps/backup/full_format.py` | `8d059952308193480ae5acb21625dbb9cd898c94a23f98f46567d9f7326743de` |
| `backend/apps/backup/host_capability_journal.py` | `b251db0457f9bdd388d372d4fbad6b6384f4e6e1412d40bc2f9a523c24521ff8` |
| `backend/apps/backup/host_capability_types.py` | `aeac8a00a8fc7db6592f9b46a0eae1d074e81fd385765238681ebc807c6ac09c` |
| `backend/apps/backup/host_marker.py` | `18d032f4b347ddbe7831c0531e1252eba576e8de9ed8d8be19062ce218dee104` |
| `backend/apps/backup/host_marker_file.py` | `0c63f5a282ed89e12f1395b4a29eb9683068589ce934a144111beb82edc2900b` |
| `backend/apps/backup/host_pointer.py` | `d5343ce1c7a1143356b07b54afbdbd44a8f22a04dc1493ca65e93b6300e29b6f` |
| `backend/apps/backup/host_private_file.py` | `1e18213207aa6141e4a1e916aa6949bc905c57a6f881b18fa9cc30fc6accb40a` |
| `backend/apps/backup/host_restore_admission.py` | `fc4c3231a6ef9677531811b1b895c6c18f997f5e3ce4c9e8dfc98363869959a5` |
| `backend/apps/backup/host_restore_configuration.py` | `f01614e7691f7d486a49e81f72cf20ed2f223645675ea84a78fcd6dd545cb803` |
| `backend/apps/backup/host_restore_files.py` | `219a50cd6d03b6251fbc818dbdb86639062a217a83626bb65115115a4a9772c1` |
| `backend/apps/backup/host_restore_lifecycle.py` | `bb0887f7dc9ae063db5030b212dffa9d2c319ddae1b1bda8b136357755770cec` |
| `backend/apps/backup/host_restore_prepare.py` | `c392c3a70f6c5c97578454a2951b18b0430f8df2036005f85654894f0fcbf5f8` |
| `backend/apps/backup/host_restore_resume.py` | `7c89f8faa4e823cd1fe8573ab5c04584b2016df07f28090807b696cd70dc9c93` |
| `backend/apps/backup/host_restore_transport.py` | `c1dd16d552715272a8f4ae3a87c2b9af844d68a4a5d2a768eab840fdbe27e599` |
| `backend/apps/backup/host_run_ledger.py` | `2c4d747ad4554176bc25ff1e4da914a3a5852ccf7ed5326279788f0212e08dd7` |
| `backend/apps/backup/host_supervisor.py` | `95e62a71d3633fd372428100fd7e49ac410633dc497d94463844f1f67749f4ed` |
| `backend/apps/backup/host_topology_record.py` | `212533a4b0d8e4e2aa0491e46c58a265907732668e7560d7c4957ccdfdd98f28` |
| `backend/apps/backup/inplace_marker.py` | `026a817f3c857a00b09700955af9f22f5728e23b657bfcfc5f155178945b83ef` |
| `backend/apps/backup/inplace_recovery_facts.py` | `77cac93c564a700dd7321166582833772b4115262241ee5b4e81e89df855b3b9` |
| `backend/apps/backup/operation_lock.py` | `226cf543049dcca1ad26a0a31db47effd4347a8416ea10794c4a3f809fe110ce` |
| `backend/apps/backup/restore_manifest_facts.py` | `a78561210f21df1f192a2dc15aa81eb939da6fe8c99d4067648726b4d3baa459` |
| `backend/apps/backup/topology.py` | `8c5f31fe31eceb86d84b3d438b363657513a8c6abb73b8bc4ea22ccd65215048` |
| `scripts/restore-host.py` | `f971c644b459bddfe5c461f555f48936e963afa8abfcd384a894a44d2c9a12d3` |

The remaining 34 fixed runtime paths are listed below. Their exact byte hashes are in pinned_runtime_copy_files in the final freeze; no docs, tests or whole backend tree are copied by the updater.

| Fixed runtime path | Installed mode |
| --- | --- |
| `setup.sh` | `0755` |
| `install.sh` | `0755` |
| `setup.ps1` | `0644` |
| `docker-compose.prod.yml` | `0644` |
| `docker-compose.cloud.yml` | `0644` |
| `docker-compose.yml` | `0644` |
| `docker/compose.build.yml` | `0644` |
| `docker/compose.tls.yml` | `0644` |
| `docker/compose.saas.yml` | `0644` |
| `frontend/nginx.conf` | `0644` |
| `deploy/init-object-buckets.sh` | `0755` |
| `scripts/bundled-database-url.py` | `0644` |
| `scripts/configure-compose-wrapper.py` | `0644` |
| `scripts/check-restore-host-bundle.py` | `0644` |
| `scripts/host-capability.py` | `0644` |
| `scripts/import-backup.sh` | `0755` |
| `scripts/init-host-orchestration.sh` | `0755` |
| `scripts/install-deploy-runner.sh` | `0755` |
| `scripts/install-host-bundle.sh` | `0755` |
| `scripts/refresh-proxy-config.sh` | `0755` |
| `scripts/setup-deploy-runner.sh` | `0755` |
| `scripts/env-file.sh` | `0755` |
| `scripts/host-image.sh` | `0755` |
| `scripts/module-selection.sh` | `0755` |
| `scripts/request-access-selection.sh` | `0755` |
| `scripts/restore.sh` | `0755` |
| `scripts/retire-update-polling.sh` | `0755` |
| `scripts/retire-update-tombstone.sh` | `0755` |
| `scripts/setup-host-orchestration.sh` | `0755` |
| `scripts/spaceworks-compose.sh` | `0755` |
| `scripts/update-lock.sh` | `0755` |
| `scripts/update.ps1` | `0644` |
| `scripts/update.sh` | `0755` |
| `scripts/validate-compose-wrapper.py` | `0644` |

## Exact operator wording for parent-owned docs

> Install the complete matching pinned host bundle before using restore/import. A fresh UID0 install retains root ownership; that is the supported ownership mode for this Linux host controller. Packaging does not automatically migrate an existing operator-owned layout. Running that layout with sudo remains unsupported until explicit preparation of its authority/code paths and all their directory ancestors.
>
> For a chosen installation ROOT, prepare only ROOT itself, ROOT/.env, ROOT/.spaceworks-version and ROOT/.spaceworks-layer when present, the exact 25 guarded Python paths listed in the matching release inventory, the existing capability-covered wrappers/configuration paths listed below, and their code-directory ancestors. Use root ownership and remove group/world write access. The concrete target modes below are0755 for code directories and shell entrypoints,0644 for Python and public configuration, and0600 for .env. Files must be regular, non-symlink and single-link. Preserve the existing stricter authority-file requirements; never loosen private files to make a command pass.
>
> Default /opt/spaceworks normally has protected root-owned /opt ancestry, but verify every ancestor. Do not chown an operator's home directory. An install under operator-owned home ancestry needs a separately reviewed explicit relocation before it can satisfy this controller; the installer does not silently move it.
>
> Preserve app-owned OPS/work and every database/object-store/Celery volume, backup, rollback object/copy, data directory and private key. Do not apply blanket chown -R or chmod -R to ROOT, /var/lib/spaceworks, an operator home or any retained private/runtime state. The source add-on neither performs this preparation nor proves runtime readiness. Keep existing protected topology/producer-capability procedures; do not hand-edit hashes or refresh authority records to bless drift or a failed restore.

Concrete preparation inventory (guidance only; no command was run):

| Named path relative to ROOT unless absolute | Ownership/mode target |
| --- | --- |
| ROOT, scripts/, backend/, backend/apps/, backend/apps/backup/ and all external directory ancestors | root-owned0755 (or an already stricter protected directory mode); ordinary code ancestry has no group/world write bits or symlinks |
| Exact25 guarded paths above | root-owned0644, regular/single-link |
| .env | root-owned0600, regular/single-link; preserve contents |
| .spaceworks-version, .spaceworks-layer when present | root-owned0644, regular/single-link; preserve contents |
| scripts/restore.sh, scripts/import-backup.sh, scripts/spaceworks-compose.sh | root-owned0755, regular/single-link; capability-covered wrapper bytes must match the release |
| scripts/host-capability.py, scripts/validate-compose-wrapper.py | root-owned0644, regular/single-link; remaining capability-covered Python wrappers |
| scripts/check-restore-host-bundle.py | root-owned0644, regular/single-link; packaging checker, not a new signature authority |
| docker-compose.prod.yml and applicable existing docker/compose.build.yml, docker/compose.tls.yml, docker/compose.saas.yml; docker/ directory if applicable | root-owned0644 configuration; root-owned0755 directory ancestry; preserve the selected topology |

This table concerns installation authority/code. It does not authorize modifying OPS state, private host keys, topology records, capability markers, work, retained evidence or data ownership. Root-private operational prerequisites must already be satisfied by their existing separately controlled setup. A pinned update makes its new file copies root-owned under UID0 but deliberately leaves existing ROOT/directory/.env ownership untouched, so sudo update alone is not layout conversion.

## Static reconciliation completed

- Parsed52 source Python files plus embedded PY_GUARD with ast.parse; never imported or executed guarded code/checker functions.
- bash -n for install.sh, scripts/install-host-bundle.sh and scripts/restore.sh; scoped git diff --check and direct new-file whitespace/final-newline checks.
- Compared literal reviewed/EXPECTED/historical path sets (exact25), all25 current whole-file SHA256 values,59 distinct copy entries, required runtime sentinels, and current file existence. The original fixed copy paths remain present.
- AGENTS.md and CLAUDE.md remain byte-identical. Existing entry snapshot differs only in the three edited existing files; the checker is new. The two independently corrected files and all other frozen source were unchanged during this task.
- Unchanged full_bundle.py SHA256: `d3237368907e29f5990bd573d1ab50faadfc90b3343c3e6ec236608256e9b15f`. New checker119 lines; installer300; bundle installer63; restore wrapper72. No runtime success is inferred from these static results.

## Required separate Stage3 proof — pending

1. Build a genuinely copied clean Linux bundle with exactly the59 declared runtime files and no source-checkout/import fallback. Verify every package init and module, preserved deploy/init-object-buckets.sh and frontend/nginx.conf, deliberate modes and UID0 root ownership. Exercise the actual installed shell-to-Python --help path with no DB, Docker/service, intent, config or cache write. Seed local stale/poisoned bytecode to verify only attested source loads. No ownership monkeypatch may stand in for the actual root-owned layout.
2. Prove real non-root invocation refusal and root invocation against an operator-owned source/directory refusal, including a sudo-equivalent caller with unsafe ancestry. Positive root-owned isolated layout may use ordinary root-sticky1777 /tmp ancestry only. Refuse symlink and non-root/writable code ancestry, arbitrary sticky writable ancestors, and changed/missing/hardlinked/symlinked helper/module/wrapper files before imports/effects. Check no __pycache__ writes.
3. Prove a normal invocation with missing .env refuses without runtime/config/intent mutation. Help success is only parsing/import/no-effects proof, not runtime transport or restore readiness.
4. Run staged-update preflight with each guarded dependency missing, altered, hardlinked or symlinked, plus linked/nonregular old fixed entries/checker. Existing target bytes, original backups and private sentinels must remain untouched; no host-config backup directory may be created on preflight refusal. Check unknown/traversing/duplicate/nonliteral/bad-digest EXPECTED declarations and ambiguous/missing heredocs; there must be no successful partial path output or copy.
5. Compare actual copied paths exactly against34 fixed +25 guarded entries. Confirm both __init__.py paths remain distinct, directories0755, Python/checker0644 and shell0755; verify non-root replacement retains existing ownership. Confirm original replaced-file backups and private .env/key/OPS/work/database/object/Celery/rollback/data sentinels retain bytes and ownership. Verify the already-present Caddyfile refresh policy remains independent.
6. Exercise fresh-install archive preflight at the real before-move/before-staged-updater boundary, requiring the checker and complete contract. Preserve original destination/private state on refusal. UID0 fresh install must retain root ownership; non-root fresh installs retain their existing operator-ownership behavior and remain unsupported for restore until explicit preparation.

Also retain the parent-required independent-correction cases: explicit non-Linux refusal, compound protected target refusal before effects, and registered signed-full DISASTER archives with rotated continuity versus strict non-reset rollback. Parent owns actual runtime/image/broker/storage proof and later review/QA. Source-only Stage2 is complete; all installed-layout/runtime outcomes above remain unproved.

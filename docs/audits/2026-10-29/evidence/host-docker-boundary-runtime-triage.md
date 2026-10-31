# Host Docker boundary runtime triage

Parent runtime reported 61 passing and 13 failing cases out of 74. The failures were confined to the test helper and occurred before the intended positive, Docker-negative and controller-root-order assertions. No production source defect was established by that run.

The AST resolver incorrectly tried each absolute import prefix relative to the importing package. Resolving `apps.backup.host_marker` from a backup module therefore invented an edge through `backend/apps/backup/apps.py`, the Django AppConfig module. Python 3 absolute imports do not use implicit package-relative resolution. That false edge expanded the controller closure into hundreds of application modules.

The bounded correction removes only that importer-directory fallback. Both configured source roots remain, explicitly relative imports are normalized to their actual package first, package initializers and from-package members remain considered, literal dynamic targets remain resolved, and deferred function imports remain scanned. No module, new Docker invocation, wrapper ownership/mode/hash check, UID check or external caller is exempted.

Independent static AST inspection after correction found exactly 25 controller dependencies, matching the actual wrapper EXPECTED set with no extra or missing path. This inspection parsed source text only; it did not import the test helper or any production module, collect tests, run tests, or access Docker, providers or databases. Separate Stage 3 adds minimal source-copy regressions through the same public validator; root owns runtime rerun. Historical freeze and failure evidence are preserved.

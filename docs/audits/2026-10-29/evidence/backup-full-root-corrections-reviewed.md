# Signed-full source freeze follow-up

Independently inspected the root's three bounded source changes after the first test run exposed missing eligibility and hardlink refusal cases:

- archive_import.require_import_principal re-reads the persisted actor and requires active account, ACTIVE access status, no forced password change, and superadmin/superuser authority before raw service preflight/provider effects.
- import_backup_archive reuses that exact eligibility check before calling the import service.
- full_bundle.verify_full_root rejects every declared regular file (including manifest.json) whose st_nlink is not exactly one; symlinks/unknown files and complete byte-ledger checks remain.

Refreshed exactly these three hashes in backup-full-source-freeze.json after confirming all other 31 production entries matched. No test execution by this lane. The first root runtime run was 209 passed / 15 failed; tests-only fixture corrections are being prepared separately. These hashes prove source identity, not readiness or passing tests.

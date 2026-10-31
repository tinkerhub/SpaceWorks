# Backup runtime audit follow-up

Status: confirmed defect; corrective design review in progress. This is a source review, not a successful restore drill.

## Reproduced by tracing the shipped path

1. `backup/archive_builder.py::build_archive` constructs `CompoundCapture` for every deployment archive.
2. `backup/source_verifier.py::verify_and_sign_source_partition` rejects an empty slice set. The default all-platform-readable population therefore cannot complete the current compound producer.
3. Even if that source refusal were bypassed, `outer_manifest.py` mirrors only the database dump and sealed slices into `contents`. The bundle also contains continuity-secret and object files. For an empty sovereign set the compatibility field is `partial: false`, so `backup_control_preflight.py` selects legacy content verification, which refuses those unlisted files.
4. For a non-empty sovereign set the preflight returns `compound-coordinator-ready`; `scripts/restore.sh` explicitly refuses to execute it. `run_compound_restore` exists as a coordinator library with tests, but no shipped non-test concrete host launcher calls it.
5. `scripts/import-backup.sh` performs static B1 signature/artifact admission, then installs archived continuity secrets and recreates backend/worker/beat processes before the supervisor reaches its runtime refusal. A statically valid unsupported artifact can therefore change configuration before refusing restoration.

## Boundaries that must remain intact

- An opaque sovereign component must never be restored through the old full-deployment path.
- A `partial: false` field does not turn a B1 envelope into an authenticated legacy payload.
- The source verification public key must come from an independently trusted host/operator channel. A key carried by an archive cannot authenticate itself.
- Age confidentiality, Ed25519 integrity, complete payload coverage, frozen consent/cohort checks and verified durable publication are required for any replacement full-deployment format.
- Static artifact admission cannot be reported as proof that a concrete privileged restore launcher is installed.

A bounded, explicitly signed full format for deployments whose complete frozen population permits platform access is being reviewed. Unsupported B1 import/restore must fail before configuration, service or restore-intent effects. The absent sovereign host launcher remains a material production-readiness limitation until implemented and exercised with its real adapters.

# Source review scope and evidence corrections

Status: local source correction and separate regression-test writing complete;
execution pending. The real production ledger is still `UNREVIEWED`; this work
does not approve any production source or unblock a release by itself.

The bounded inspection found five concrete problems in the new release-source
checker. The corrective plan passed its Stage 1 CLI review after incorporating
the reviewer's required draft-reset change. A separate Stage 2 CLI implemented
three files; the coordinating agent read the complete changes.

| Problem | Correction and boundary |
| --- | --- |
| The ignored `frontend/tsconfig.tsbuildinfo` cache was treated as source and would differ from a clean release checkout. | Omit only that exact generated cache path before reading bytes or adding an inventory row. Other ignored or unknown source files remain review candidates. The frontend Docker context already excludes TypeScript build caches. |
| Dated audit logs, CSV maps, JSON inventories and XML results were treated as production inputs, changing every global source fingerprint when verification evidence changed. | Classify only recognized report-data extensions beneath a canonical `docs/audits/YYYY-MM-DD/` directory as documentation. Retain path/classification inventory; executable and unknown files there still require review. A cited actual review report remains independently bound to its bytes. |
| SVG was an unhashed static asset despite supporting executable browser content when opened directly. | Treat SVG as an opaque production input with a byte hash and explicit whole-context review. The scanner does not execute or parse its XML. |
| Four public, checked-in environment templates were omitted by the generic private-file rule. | Hash exactly `.env.example`, `.env.production.example`, `backend/.env.example` and `frontend/.env.example` as opaque production inputs. They matched the known tracked templates at inspection. Real environment files, private keys, credentials and private directories remain unread. No template values were printed. |
| A derived API exclusion accepted a nonempty report name without validating actual report bytes. | Reuse the existing report binding/validation and review fingerprint helpers. Bind the derivation's command, output, input hashes and versions to the actual report. Missing, changed or unsafe evidence refuses output exclusion. Drafting clears derived report bindings and fingerprints without mutating the input census. |

Changed source files:

- `backend/apps/backup/source_primitive_scope.py`
- `backend/apps/backup/source_primitive_derived.py`
- `backend/apps/backup/source_primitive_registry.py` — only the unreviewed derived-record reset.

These remain pure static helpers with no Django application startup, database
queries, source execution, provider calls or discovery-generated approvals. The
release workflow and its mandatory verification dependency were not weakened.

The separate Stage 3 CLI added 30 cases and adapted the existing derived-report
fixtures. Static parametrization gives 135 cases across the five listed files;
the runtime collector, not this estimate, supplies the authoritative total. The
coordinating agent read all new/changed tests and corrected the generated-function
symbol assertion to the parser's qualified `<module>.generate` owner. These cover
matching clean/local scope, private-byte exclusion, unknown executable/data
negatives, SVG edits, actual derived-report tampering and immutable drafts.

Run in the primary-controlled Python 3.12 / Node 20 environment, with the normal
pure-static test setup and without Django conftest startup:

```sh
PYTHONPATH=backend python3.12 -m pytest --noconftest -c /dev/null -q \
  backend/tests/backup/test_source_primitive_scope.py \
  backend/tests/backup/test_source_primitive_derived.py \
  backend/tests/backup/test_source_primitive_registry.py \
  backend/tests/backup/test_source_primitive_audit_scope.py \
  backend/tests/backup/test_source_primitive_input_scope.py
```

The primary agent owns execution and final corpus review. See
[the explicit review segmentation plan](source-review-segmentation.md) for completing
the still-pending production review decisions.

# Optional source certification

This strict whole-checkout certification was introduced during the 2026-10-29
audit. It was not a pre-existing required product release guard. Activation in the
release workflow is deferred; the existing CI/pip-audit release requirements remain.

For an independent, optional strict certification check, use Python 3.12, Node 20
and the frontend TypeScript parser installed from the lockfile. From the repository
root, run:

```bash
python scripts/check_source_primitives.py
```

The current `registry.json` is `UNREVIEWED`. The command refuses before discovery,
returns exit code 1 and reports:

```text
source review refused: scope/corpus is UNREVIEWED
```

Certification remains incomplete. Discovery, mappings and passing tests are not
review decisions; an exported UNREVIEWED draft is not an approval. Neither these
documents nor retaining the checker establishes a full audit or certification.

Before activating a release dependency, complete actual source/context reviews
and explicit report-backed decisions covering scope and callers, assemble a valid
normalized ledger for the final snapshot, and pass the independent CLI check on
that exact release checkout. Source changes require reassessment of the changed
dependency context and reconstruction of decisions; replacing hashes alone does
not supply approval. Even a passing ledger covers only that snapshot, not live
deployment checks.

The final audit report and mandatory final Codex uncommitted review remain
required. Real feature/security findings remain production blockers independently
of this optional certification. The [review sequence and reassessment rules](../audits/2026-10-29/evidence/source-review-segmentation.md)
describe the remaining work.

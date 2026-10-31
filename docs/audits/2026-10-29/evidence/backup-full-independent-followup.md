# Signed-full independent verification corrections

Status: source frozen for separate Stage 3 tests; no runtime success claim. This
supplements and supersedes affected control-record paragraphs/hashes of the prior
Stage 2 handoffs. `backup-full-source-freeze.json` records current complete bytes.

The independent pass retained the approved separate signature domain, exact payload
ledger, source snapshot/cohort checks, shared durable publication, fixed maintenance
bootstrap, and explicit unsupported-sovereign-coordinator limit. It corrected three
remaining workflow issues:

- The privileged identity bootstrap now accepts both BOUND NORMAL and
  ACKNOWLEDGED_NORMAL, the two ordinary all-writer-ready states. Candidate,
  quarantine and unbound markers remain refused.
- A rollback's all-table diff can exceed 64 KiB. The complete private control report
  therefore remains in its existing file; a mode-0600, fsynced companion
  `restore-control.json.identity.json` contains only the bounded target identity.
  The fixed privileged bootstrap receives this companion through stdin and retains
  its 64 KiB boundary. A large legitimate report no longer blocks rollback.
- The dump was taken while the selected archive was still RUNNING, before its final
  encrypted digest/size/expiry were committed. The outside-DB control record now
  preserves those selected, already verified archive facts. Rehydration checks the
  selected archive UUID and canonical signed manifest digest, restores the exact
  encrypted SHA/size/final locator/completion/expiry, and clears its old download
  token. It cannot silently adopt a different signed manifest after replacement or
  leave a restored available archive with blank integrity/size fields.

The last correction lives in the focused `backup/full_control_record.py` helper;
physical identity remains settings-free in `full_restore_identity.py`. Django's
rehydration service applies those facts in its existing transaction. The privileged
bootstrap still has only fixed identity/grant responsibilities, and no marker,
source private signing key or provider authority is adopted from the archive.

Static Python parsing, shell syntax and whitespace checks passed. Actual
least-privilege capture, crypto/dump/restore, concurrency, rollback, host bootstrap,
metadata and UI regressions are being written separately and must pass before any
readiness statement. The owner of final operator documentation must also merge the
real OCI forwarding/prerequisite and externally pinned verification/signing-key
lifecycle instructions from this lane's handoffs.

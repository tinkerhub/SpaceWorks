# In-progress Stage2 independent review notes

These are preliminary source observations while the implementation CLI is still writing; they are not final findings or runtime results. Reconcile after Stage2 completes before test writing.

- Existing setup-host-orchestration.sh provisions operation.lock as root:root mode0666 so the unprivileged app's bind-mounted inode can participate in the same flock. InplaceMarkerTransition._locked currently calls `_trusted(lock_path, private=False)`, which rejects file mode&022. That would reject every normal installed shared lock. The lock file is not authority data: require root-owned regular non-symlink/non-hardlinked inode, match the held fd, and protect its root parent against replacement, while retaining the intentionally shared file access. Do not weaken private-record or marker checks.
- Review crash after terminal ledger DONE before marker replacement: success/ack should either finish idempotently after all exact current proof checks or explicitly preserve a usable fail-closed manual completion procedure. Do not repeat SQL or change keys to recover this gap.
- Verify every newly delegated privileged script and host-side module is covered by existing source/script identity mechanisms; a thin wrapper hash alone cannot cover moved authority code. Existing capture scanner and rollback entries must remain.
- Normal singleton is already seeded by migration0022; tests also have an autouse normal seeder. Fresh Task guard should never .load() or synthesize NORMAL.

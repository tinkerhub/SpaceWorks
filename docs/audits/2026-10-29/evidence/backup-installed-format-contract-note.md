# Installed recovery format contract adjudication

This is source/document adjudication while the immutable full baseline runs; it is not a runtime pass or a test-expectation change.

- Historical `HEAD:scripts/restore.sh` lines178–179 explicitly refused the `compound-coordinator-ready` token: the legacy in-place wrapper could not execute a compound restore and instructed the operator to invoke a target coordinator. The installed script inventory contains no compound target launcher. Existing coordinator-library tests exercise injected adapters; they do not establish a shipped operator entrypoint.
- Current `backup_control_preflight.run_restore_preflight` explicitly raises `COMPOUND_UNSUPPORTED` for B1. `host_restore_prepare.require_route` admits signed-full or complete registered historical same-host formats only. The new signed-full route does not convert or weaken B1 sovereignty, custody, signatures, protocol2, target/fence or host-capability requirements.
- `docs/self-hosting.md#supported-recovery-formats` now distinguishes signed-full, historical registered same-host, B1 compound and Lane D. The UI/docs agent independently verified the old shell refusal and states that B1 static validation/coordinator-library code did not install a launcher.
- The narrow `docs/INVARIANTS.md` paragraph clarification near2425 identifies the coordinator as a library requiring an injected target host adapter. Existing conditional B1 protocol/custody/fence invariants remain mandatory. `host_restore_gate_status()` remains descriptive, with no launch authority.

The limitation is an existing declared-but-unshipped integration gap, not a newly removed working host restore feature. No source, test body, manifest, immutable baseline or provider state was changed by this adjudication. Exact full-run failures still require their own trace-based disposition; no failing test is waived here.

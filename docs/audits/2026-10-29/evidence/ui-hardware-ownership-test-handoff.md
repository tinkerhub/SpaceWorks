# Hardware Stage 3 test authoring handoff

The separate CLI writer exited 0 after authoring 67 statically expanded cases in
nine new suites plus one test-only helper. All 12 original hardware source hashes
matched its freeze. No source/existing tests were edited and no runtime/TSC/build
was executed. The largest new file is 190 lines. Exact byte bindings/counts are in
[ui-hardware-ownership-test-freeze.json](ui-hardware-ownership-test-freeze.json).

The suites exercise actual Queues row visits and same-product QR races, optional
container/assignment retry, concurrent scans/native callbacks, read options through
pending, canonical queued DTO/session transport, direct issue/return and parent
remounts, captured waiver subjects and delayed walk-in selection. The HTTP/scanner
leaves implement no ownership logic.

The small authorized walk-in receipt/roster follow-on remains outstanding; its
real-query failure/pause tests and truthful standalone roster fixtures must be added
before the final combined root execution. Current source/test bytes are a historical
freeze, not approval for that future delta or whole production release.

Root Node20 focused selection after the final follow-on freezes:
`npm test -- --maxWorkers=1 hardwareOwnership Queues.qrOwnership Queues.handoverContracts`
plus the new roster follow-on suite and prior 247-case staff selection; then
`npx tsc -b`. Root controls actual execution and records collected counts.

| Test/helper | Static cases | Lines |
| --- | ---: | ---: |
| `frontend/src/features/staff/panels/Queues.qrOwnership.test.tsx` | 5 | 107 |
| `frontend/src/features/staff/panels/BoxCodeField.hardwareOwnership.test.tsx` | 8 | 107 |
| `frontend/src/features/staff/panels/useQueueActions.hardwareOwnership.test.tsx` | 13 | 150 |
| `frontend/src/features/staff/panels/Queues.handoverContracts.test.tsx` | 4 | 113 |
| `frontend/src/features/staff/DirectLoans.hardwareOwnership.test.tsx` | 11 | 190 |
| `frontend/src/features/staff/DirectLoanItems.hardwareOwnership.test.tsx` | 6 | 102 |
| `frontend/src/features/staff/DirectLoanReturn.hardwareOwnership.test.tsx` | 7 | 146 |
| `frontend/src/features/staff/DirectLoanBorrower.hardwareOwnership.test.tsx` | 5 | 100 |
| `frontend/src/features/staff/WalkInMemberForm.hardwareOwnership.test.tsx` | 8 | 126 |
| `frontend/src/test/hardwareOwnershipHarness.tsx` | 0 | 152 |

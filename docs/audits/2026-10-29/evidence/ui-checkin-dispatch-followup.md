# Queued check-in lookup dispatch correction

Actual source review found that callback ownership did not prevent a paused/queued obsolete lookup from reaching transport. The local mutation function now checks its existing exact active-input/context/generation/mounted-lifetime predicate and the latest disabled flag immediately before `lookupCheckin`. Current callbacks and disabled pending cleanup are unchanged. Presence remains a fail-closed roster filter, not authentication.

Source: `frontend/src/features/inventory/CheckinIdentityStep.tsx`, 249 lines, SHA256 `0fa9cae53acbe94c7d5d1cbeb53f26a8d63042afb7c3bb462870a20436c7efbf`.

Separate Stage 3 authored five cases in `CheckinIdentityStep.dispatch.test.tsx` (136 lines). Real TanStack mutations must first report `isPaused: true`; the tests change A→B, A→B→A, disable, or unmount before reconnecting. They resume and await actual settlement before asserting zero obsolete transport calls. Current queued success and disabled pending-release/retry are controls. The singleton online-manager state is restored in cleanup. No fake ownership transport is used.

Root verification is pending:

```sh
npm test -- --maxWorkers=1 src/features/inventory/CheckinIdentityStep.dispatch.test.tsx
```

No runtime, staging or commit was performed by this lane. Adjacent review/implementation/test-writing transcripts preserve the gates.

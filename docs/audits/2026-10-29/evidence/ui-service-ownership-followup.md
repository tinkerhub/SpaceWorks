# Shared service intake and status ownership correction

Actual source review identified stale maker/person/type state, a presign/raw-upload/submit continuation that could outlive its initiating context, unowned pending/result callbacks, and a borrow-status draft that did not follow URL navigation. The separately reviewed correction changes four source files only; their exact hashes and line counts are in `ui-service-ownership-source-freeze.json`.

The shared page now owns semantic maker/auth/policy/default-printer visits. A stable catalog object refresh retains the current draft, while type and canonical-person changes reset private details. Check-in typing remains outside the keyed detail form. Parent pending matches an exact form/action and releases on disappearance without old cleanup unlocking a newer submission.

The form captures immutable body, file policy, files and requester at admission. Existing action ownership is checked before presign, before raw storage, after bytes, before subsequent files/final creation, and before progress/success/error/cleanup publication. Serial first-response queue pinning and printer/generic DTOs remain intact. Already-admitted bytes or dispatched API writes may finish; the client prevents later stages and obsolete publication rather than claiming cancellation.

The tracker masks ephemeral completion before effects and guards current-visit callbacks/persistence. Explicit URL capability lookup and documented same-browser saved-token fallback remain compatible. The borrow reference editor is keyed by exact maker and URL token, including token removal.

## Verification

Separate Stage 3 authored 35 cases across five suites and one real-fetch/session/upload harness. Root's first focused run recorded 66 passed / 12 failed across 78 cases. Corrections were confined to tests: successful legacy refresh mocks now install a token; cache updates use immutable DTOs and await TanStack observer delivery; the stale tracker case releases held completion after actual departure/unmount instead of trying to undo a valid earlier success. Identity, immutable payload, queue pin, pending, retry, current result and negative persistence assertions remain.

Root then passed all 78 cases in 11 files (23.49s), followed by `npx tsc -b` success (chained exit 0 reported by root). Initial and corrected raw logs are adjacent `ui-service-ownership-*-runtime.log`. Current source and test freezes are adjacent JSON files. Complete-suite review/release approval remain root-owned.

The changed source remains below 300 lines: PublicMachineServicePage 120, ServiceRequestForm 176, ServiceStatusPanel 68, PublicRequestStatusPage 101. No new runtime source files or backend/API/session-store changes were introduced. No runtime execution, staging or commits were performed by this lane.

# Public lending ownership corrective audit

An explicit source read found stale maker/person state and publication defects in the public catalog, borrow desk, self-checkout and raw evidence upload. The approved local corrections keep same-maker public selection across sign-in while clearing cart/details immediately on a different maker route. Catalog placeholder reuse is restricted to the same maker.

The desk owns the accepted request reference separately from a fresh kiosk borrower draft, so clearing the confirmed person does not erase the only lookup reference. Borrow submission captures an immutable body and checks current mounted/person/auth/action ownership before delayed dispatch and completion. Identical failed bodies reuse their retry key; changed submitted bodies receive another key. Success cannot erase a cart composition changed since admission.

Inline and standalone tool lending share a single checkout/return admission owner and owned rendered pending/error/result state. Person visits, photos, QR/camera callbacks and remarks stay current-context scoped. Required evidence, return remark, QR and problem-note rules remain in place. The new uploader checks ownership after presigning and after already-admitted raw storage bytes finish; obsolete completion/error/finally cannot publish or clear newer evidence. Semantic reset is independent of callback identity. Already-admitted staging bytes may still complete.

The public session probe includes auth generation and checks cancellation/current generation after refresh. Authentication is projected from the current token rather than an infinitely cached prior true value.

## Source handoff

Exact paths, line counts and SHA256 values are in `ui-public-lending-source-freeze.json`. Nine existing inventory files and four focused new composers were changed. New owners for SOURCE-MAP:

- `PublicBorrowRequest.tsx`: current person visits and accepted completion presentation.
- `PublicBorrowRequestForm.tsx`: immutable body, body-bound idempotency, draft and publication ownership.
- `PublicSelfCheckoutView.tsx`: standalone checkout/return presentation and scanner/evidence state.
- `usePublicToolOperation.ts`: shared synchronous admission and owned mutation view.

All source files remain below 300 lines. Separate Stage 3 authored 60 cases across seven new suites plus a shared fixture. Root owns Node 20 test execution, typecheck and the complete suite. No runtime pass is claimed here. Adjacent plan review and implementation transcripts record the gates. No production credentials, deployments, staging, commits or backend/API/session-store changes were made by this corrective group.

## Remaining boundary

`CheckinIdentityStep.tsx` already guards lookup callbacks, but its mutation function lacks a current-input check before a queued obsolete lookup dispatch. This was reported to root for bounded triage; no correction is claimed in this frozen group. The frontend context decisions explicitly retain this and runtime-pending corrected source as pending rather than fabricating release approvals.

## Frozen verification handoff

From `frontend/`, root's current Node 20 environment can run:

```sh
npm test -- --maxWorkers=1 src/features/inventory
npx tsc -b
```

This includes the existing public request/checkout/check-in suites alongside all seven new ownership suites. The existing `PublicIdentityTenantScope.test.tsx` was updated to expect an empty purpose after a new confirmed person/maker, and then type a fresh B purpose before verifying the exact B request body. Its prior tenant-negative assertions are retained. The shared mutable input fixture is reset before each case. New tests cover before-paint route ownership, body-bound retries, accepted kiosk reference retention, shared operation admission, current-person immutable tool bodies, cancelled/stale session probes, and held presign/raw-storage/camera completion.

Test authoring is not execution. Runtime status remains pending until the coordinating audit records its actual result.

## Coordinated runtime result

Root's first inventory run recorded 133 passed / 11 failed across 144 cases. Traces identified test-fixture mismatches: Radix mode controls expose radio roles; invalidated bootstrap/category reads needed their actual DTO shapes; successful mocked refresh must install a token; the layout probe must use the current generation key. These were corrected while retaining all maker/person/epoch, pending, immutable-body, result and evidence assertions. The corrected root Node 20 run passed all 144 cases in 22 files (58.80s), followed by a successful `npx tsc -b` (chained command exit 0, reported by root). Raw initial and corrected logs are adjacent `ui-public-lending-*-runtime.log` files. The later five-case queued check-in dispatch suite is separate and was not included in that 144-case result. Complete-suite and release approval remain root-owned.

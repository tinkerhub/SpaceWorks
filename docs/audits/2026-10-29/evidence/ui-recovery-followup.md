# Recovery ownership corrective audit

Static review identified three confirmed defects: reset credentials could survive a changed uid/token route; an editable email could receive another email request completion; and control characters in an otherwise root-relative return path could normalize to an external origin.

The approved bounded implementation uses the existing mounted/action/context owner hook. Reset route pairs are JSON-keyed and direct-prop state is context-tagged, including A→B→A. Email request/confirm/resend and cooldown publication are bound to the captured confirmed email. Redirects require a root-relative prefix, reject control/space/DEL/backslash characters, and validate the resolved origin against a trusted local base. Safe internal query strings and fragments remain supported. No global session, API transport or backend changes were made.

## Source files

- `frontend/src/features/staff/ResetPasswordPage.tsx`
- `frontend/src/features/auth/LegacyPasswordResetForm.tsx`
- `frontend/src/features/auth/PasswordRecoveryFlow.tsx`
- `frontend/src/features/auth/passwordRecovery.ts`

## Verification

Separate Stage 3 authored 17 ownership and 32 return-path cases, with a shared synthetic transport harness. The tests use the real owner hook, React and MemoryRouter; they do not replace the ownership boundary with a fake HTTP shim. Coverage includes held success/rejection/finally, direct props and query changes, before-paint state, same-tick duplicate submission, editable email and cooldown races, and actual resolved URL origins.

Root owns Node 20 execution; at this handoff runtime is pending. From `frontend/`:

```sh
npm test -- --maxWorkers=1 src/features/auth/PasswordRecoveryFlow.ownership.test.tsx src/features/auth/LegacyPasswordResetForm.ownership.test.tsx src/features/auth/passwordRecovery.returnPath.test.ts src/features/auth/PasswordRecoveryFlow.test.tsx
npx tsc -b
```

The two new ownership files and the pre-existing `PasswordRecoveryFlow.test.tsx` use block-bodied `beforeEach` mock resets so Vitest does not interpret a returned mock as a teardown callback. All touched source and new tests remain below 300 lines. No build, staging, commit, or production credential actions were performed by this lane.

Review, implementation and test-authoring transcripts are adjacent `ui-recovery-*.txt` files. Source-review decisions remain pending until exact final bytes and runtime results are bound by the coordinating audit.

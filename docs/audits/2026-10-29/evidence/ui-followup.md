# UI and authentication completion follow-up

Status: local implementation and regression-test writing complete; execution pending. This is not a
release approval or a record of production deployment. Final runtime results belong
in the parent audit report after the primary agent runs the suites.

## Corrections inspected in the current checkout

- A fresh global staff login now keeps the makerspace chooser in a loading state
  until the router acknowledges the central staff route. The hook also rejects
  retained chooser callbacks immediately after another choice starts, before React
  commits a new render. This prevents a fast choice from carrying the old
  makerspace's Settings route into a new login.
- Staff authentication installs the access token before changing hook-owned user
  state. A rejected local installation can therefore be reported by its original
  action, without partially publishing a new user or selection.
- Password-change success handles local session installation separately from the
  server request. If the password changed but this browser cannot install the new
  session, the form clears its secrets and says to sign in again. It does not say
  that the password was unchanged or invoke the protected-screen completion callback.
- Member provider completion reports its own installation failures and releases its
  exact pending action. Starting that action invalidates the provider's old parent
  intent, so delegating this error to the provider component could otherwise hide it.
- Invitation login clears its password after a typed local installation failure.
  An already redeemed invitation and the existing member identity remain intact;
  staff navigation still requires a successful explicit staff sign-in.
- A current failed server logout is shown on the signed-out form. Its ownership is
  captured after local clearing and invalidated synchronously when a newer password
  login starts, including the period before the newer access token arrives. Late
  logout settlement does not clear a newer account or publish an obsolete warning.
- Staff Google sign-in now receives the host callback's memoized ownership scope
  and is disabled during password submission. Previously a failed password attempt
  changed the staff hook's action lifetime while Google's mounted callback retained
  the previous lifetime, so later valid Google responses were silently discarded.
  Typing in the fields does not change the provider scope or consume another nonce.

These changes use React action ownership, TanStack Query mutation completion, and
router acknowledgement; they do not change backend authorization or bypass a
makerspace's domain restrictions.

## Source files

- `frontend/src/features/staff/useStaffSession.ts`
- `frontend/src/features/staff/StaffApp.tsx`
- `frontend/src/features/staff/LoginPanel.tsx`
- `frontend/src/features/account/ChangePasswordForm.tsx`
- `frontend/src/features/members/MemberAuthPanel.tsx`
- `frontend/src/features/organizations/OrganizationInvitationRedeemPage.tsx`

The existing checkout also contains the shared Modal non-null stack-owner fix and
the invitation route-visit restoration fix. Their existing DS01/OI regressions are
part of the final frontend run; their presence alone is not a passing test result.

## Gates and pending verification

The bounded Stage 1 CLI plan review approved these changes, and the separate Stage 2
CLI implementation exited successfully. The coordinating agent read all six
modified source files and checked their ownership guards and size limits. A
separate Stage 3 CLI wrote targeted regression tests. No tests or builds have
been executed by this child agent; the primary agent controls Node 20 verification
and the final whole-workspace review.

The additional staff Google recovery correction had its own approved bounded plan
review and separate implementation call. The saved review and implementation
summaries in this directory retain those gate results without claiming the final
whole-workspace review has passed.

The root-owned session-store change supplies `SessionInstallError` and the test-only
JWT fixture helper. The UI follow-up does not implement a second session parser or
alter the API protocol. Final owner QA, commit, push and deployment remain outside
this handoff.

## New runtime checks to execute

The separate test-writing calls completed successfully: 12 cases in the five
completion files, plus one complete Google recovery integration case. The root-owned
JWT helper now exists; the test-writing summary's earlier missing-helper warning
describes its initial read and is no longer a missing-file blocker.

Run with Node 20 from `frontend`, after the root fixture migration is complete:

```sh
npx vitest run --maxWorkers=1 \
  src/features/account/ChangePasswordForm.installation.test.tsx \
  src/features/members/MemberAuthPanel.installation.test.tsx \
  src/features/organizations/OrganizationInvitationRedeemPage.installation.test.tsx \
  src/features/staff/staffSession.completion.test.tsx \
  src/features/staff/staffSelection.acknowledgement.test.tsx \
  src/features/staff/staffSocialRecovery.test.tsx
```

The tests use real component action ownership, router state, TanStack mutations,
and token/epoch publication. They replace only the relevant network/provider
boundary, a selectively failing installer, or delayed navigation acknowledgement.
They assert actual secrets, user/cache identity, request bodies and route outcomes;
none uses skipped cases or a production validation bypass.

The primary agent's first full run after these additions recorded 1,580 passing
and three failing cases. All three failures were test selector mistakes: empty
ToastProvider live regions are always mounted, and the harness's route `output`
also has an implicit status role. The tests now wait for the exact error content,
check empty live regions explicitly, and scope the loader assertion to `main`.
The existing provider-ownership test also now passes its React `key` directly,
retaining the same remount assertion without React's key-spread warning. These
bounded test-only corrections require the primary agent's focused rerun before
the record may be considered passing.

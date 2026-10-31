# Refresh pin Stage 3 test handoff

Scope: `/tmp/spaceworks-refresh-pin-stage3-prompt.txt`, approved `refresh-pin-plan.md` in this directory. Test-only frontend changes plus this requested handoff; production source and the sibling’s new installation/logout/chooser test files were not edited. Nothing staged or committed.

## Coverage and fixture decisions

- Added `frontend/src/test/accessTokens.ts`: deterministic compact JWT fixtures with UTF-8/base64url encoding, access/member defaults, positive user 1, deployment UUID, rotating-claim fields and a non-secret test signature. Labels distinguish exact token bytes. Account B explicitly uses user 2; verification and staff fixtures carry their real surface and staff scope.
- Migrated 31 existing test/helper files that install tokens through the real session module or assert those exact tokens. Existing held fetch/body/retry boundaries, header comparisons, generation fences, expiry events, query-cache assertions and test-function counts remain. No skips, removed assertions or timeout increases were added. Tests with a fully mocked installer retain their opaque fixtures.
- Empty-bearer setup now installs a legitimate prior-session token before clearing it. This models a known prior identity eligible for recovery; genuinely fresh modules without pins are covered separately. Both storage areas are reset where those existing setups install sessions.
- New parser tests cover supported browser contexts, canonical identifiers, malformed/native/partial/unsupported tuples, bounded input, strict stored schema, and exclusion of JWT/PII/rotating fields.
- Reload tests use `vi.resetModules()` and fresh real `apiSession` imports. The helper never statically imports the API owner. Separate backing stores model independent tabs and opener clones; the active storage getter is switched before each tab operation.
- The stale-cookie regression explicitly models ordered HTTP Set-Cookie delivery: B completes first, then late A replaces the simulated cookie. It verifies current B stays intact, reload refuses A, and matching B still recovers. This is a frontend ordering model; it does not claim to test browser cookie machinery or replace the separate backend characterization.
- Storage tests inject individual getItem/setItem/removeItem throws and no-ops, require read-back proof or verified invalidation, test memory-only B and fail-closed reload, preserve A/token/epoch/latch/legacy storage on failed replacement, and preserve A’s pending refresh ownership.
- Logout tests check exact error reasons, server attempts despite pin failures, durable removal/invalid-marker proof independent of the shared localStorage latch, surviving-cookie risk when proof fails, and newer-login state while an old incomplete logout settles.

## Validation performed

- Parsed all 37 owned TypeScript/TSX test/helper files with TypeScript `createSourceFile`: zero syntax diagnostics. This was syntax-only; no semantic type checking or production modules were executed.
- Statically compared existing files against a pre-edit snapshot: counts of `expect(`, `it(`, `it.each(`, `describe.each(`, `heldResponse(` and `heldBody(` are unchanged in every migrated file. Checked added lines for skips/timeout changes; none.
- Checked whitespace and new-file lengths: accessTokens 19 lines, refreshPinTestHelpers 46, sessionIntent.test 119, apiSessionRefreshPin.test 194, apiSessionPinStorage.test 132, apiSessionLogoutStorage.test 124. Every new code file is below 300 lines.
- `codex doctor` found configured authentication but network/reachability diagnostics failed in this restricted session. No nested Codex work was launched; this task is the assigned Stage 3 executor.
- **No runtime tests, full tsc, builds, Docker, backend suite, staging or commits were run. There is no runtime passing claim.** The coordinating runner owns runtime validation.

## New test selectors and static counts

Counts below are test-function declarations and statically expanded cases, not executed results. No cross-product expansion is used in these new files.

| File | Test functions | Cases |
| --- | ---: | ---: |
| `frontend/src/lib/sessionIntent.test.ts` | 8 | 74 |
| `frontend/src/lib/apiSessionRefreshPin.test.ts` | 8 | 21 |
| `frontend/src/lib/apiSessionPinStorage.test.ts` | 7 | 11 |
| `frontend/src/lib/apiSessionLogoutStorage.test.ts` | 4 | 9 |
| Total | 27 | 115 |

### `frontend/src/lib/sessionIntent.test.ts`

- `accepts $name with only its canonical immutable fields` (6 cases)
- `canonicalizes safe user IDs and UUID case while ignoring rotating and private claims` (1 cases)
- `rejects $name` (28 cases)
- `rejects malformed or unbounded compact input %#` (19 cases)
- `decodes bounded UTF-8 claims without storing their text` (1 cases)
- `rejects stored schema drift %#` (8 cases)
- `rejects malformed or oversized stored pins %#` (6 cases)
- `distinguishes an immutable context change %#` (5 cases)

### `frontend/src/lib/apiSessionRefreshPin.test.ts`

- `persists exactly the versioned identity, without the bearer, rotating claims or PII` (1 cases)
- `restores matching $name rotation after reload without advancing its epoch` (6 cases)
- `rejects cookie A delivered after explicit B, including on a fresh module reload` (1 cases)
- `rejects a valid refresh with a changed $name without clearing the current session` (6 cases)
- `never fetches with a missing or invalid reload pin %#` (4 cases)
- `preserves the pin across a local bearer clear for later matching anonymous recovery` (1 cases)
- `an opener-cloned pin accepts only its original context after the parent changes account` (1 cases)
- `independent tabs retain different pins and reject the other tab's cookie identity` (1 cases)

### `frontend/src/lib/apiSessionPinStorage.test.ts`

- `allows memory B only after confirmed old-pin removal with %s` (3 cases)
- `uses a verified invalid marker when removal is a %s` (2 cases)
- `rejects replacement atomically when all persistence and invalidation operations %s` (2 cases)
- `does not treat unreadable storage as proof of persistence or invalidation` (1 cases)
- `accepts a throwing write only if read-back proves the exact new pin was saved` (1 cases)
- `leaves an already pending matching refresh owned by A when B installation fails` (1 cases)
- `rejects an invalid token before storage work and preserves the prior session` (1 cases)

### `frontend/src/lib/apiSessionLogoutStorage.test.ts`

- `always attempts server logout and reports $name accurately` (5 cases)
- `proves per-tab logout with %s even after a new tab's login clears the shared latch` (2 cases)
- `cannot call a shared latch durable when an old pin survives and another tab can clear the latch` (1 cases)
- `an incomplete old logout cannot alter a newer login's token, pin, latch or epoch` (1 cases)

For the coordinating Node 20 runner, select these four new files from `frontend/` (command not executed here):

```bash
npx vitest run src/lib/sessionIntent.test.ts src/lib/apiSessionRefreshPin.test.ts src/lib/apiSessionPinStorage.test.ts src/lib/apiSessionLogoutStorage.test.ts
```

The migrated transport and UI ownership suites should also run centrally; shared harness changes affect their existing consumers. The sibling owns its five new UI test files and its own handoff.

## Complete exact changed-file list

31 existing files, six new TypeScript test/helper files, and this handoff: 38 files total. This list is scoped to this executor’s edits; the workspace contains unrelated pre-existing and concurrent changes.

- `frontend/src/lib/apiSessionTestHelpers.ts`
- `frontend/src/lib/apiSession.test.ts`
- `frontend/src/lib/apiSessionRace.test.ts`
- `frontend/src/lib/apiRequests.test.ts`
- `frontend/src/lib/apiRequestDispatchRace.test.ts`
- `frontend/src/lib/apiRequestSessionRace.test.ts`
- `frontend/src/lib/apiDownloadRecovery.test.ts`
- `frontend/src/lib/apiTenantCredentialRevisit.test.ts`
- `frontend/src/lib/apiResponsePublicationTestHelpers.ts`
- `frontend/src/lib/apiResponsePublicationExpiry.test.ts`
- `frontend/src/lib/apiResponsePublicationFetch.test.ts`
- `frontend/src/lib/apiResponsePublicationRetry.test.ts`
- `frontend/src/lib/apiResponsePublicationBootstrap.test.ts`
- `frontend/src/lib/apiResponsePublicationBody.test.ts`
- `frontend/src/lib/apiResponsePublicationFailure.test.ts`
- `frontend/src/lib/apiResponsePublicationDownload.test.ts`
- `frontend/src/test/authOwnership.ts`
- `frontend/src/test/socialOwnershipHarness.ts`
- `frontend/src/test/organizationOwnershipHarness.tsx`
- `frontend/src/test/staffSelectionHarness.tsx`
- `frontend/src/features/staff/panels/machine/machineConsoleTestUtils.ts`
- `frontend/src/features/account/ChangePasswordForm.ownership.test.tsx`
- `frontend/src/features/members/MemberAuthPanel.ownership.test.tsx`
- `frontend/src/features/members/MemberAuthPanel.verificationOwnership.test.tsx`
- `frontend/src/features/members/MemberAuthPanel.providerIntent.test.tsx`
- `frontend/src/features/auth/SocialSignInButtons.providerOwnership.test.tsx`
- `frontend/src/features/auth/SocialSignInButtons.oidcOwnership.test.tsx`
- `frontend/src/features/organizations/OrganizationInvitationRedeemPage.ownership.test.tsx`
- `frontend/src/features/organizations/OrganizationInvitationRedeemPage.test.tsx`
- `frontend/src/features/staff/staffSelection.login.test.tsx`
- `frontend/src/features/staff/staffSelection.callbacks.test.tsx`
- `frontend/src/test/accessTokens.ts`
- `frontend/src/lib/refreshPinTestHelpers.ts`
- `frontend/src/lib/sessionIntent.test.ts`
- `frontend/src/lib/apiSessionRefreshPin.test.ts`
- `frontend/src/lib/apiSessionPinStorage.test.ts`
- `frontend/src/lib/apiSessionLogoutStorage.test.ts`
- `docs/audits/2026-10-29/evidence/refresh-pin-tests.md`

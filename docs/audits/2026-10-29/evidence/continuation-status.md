# Audit continuation

The local runtime stopped and temporary handoff/log files were lost before this continuation. Repository code, reports, first full-run summary and the initial 12 screenshots survived. Historical counts in reports are historical evidence, not a current green release result.

- Restarted existing local PostgreSQL test databases, Redis, MinIO and Node 20 Vite containers.
- Rechecked Codex CLI 0.160.1: authentication configured, doctor reports zero failures.
- Recreated a private test environment without exposing credentials.
- X13 source fixture preflight: 1 passed; actual custom-dump roundtrip running separately.
- UI recovery focused suite: 42 passed across organization ownership, modal focus, responsive staff shell and makerspace-selection login/cache files. This precedes further auth pin/caller changes.
- Three new subagents continue backend admission, backup restore format, and UI/auth corrections.

Unfinished: safe identity pin implementation/tests; usable signed deployment backup admission; final full suites; final release-source review ledger; complete screenshot gallery and README; background review; owner QA; merged remote branch cleanup. No staging, commit, push or deployment in this continuation.

README was rewritten around official project vs customized fork, current screenshots, contribution setup,
module reference, architecture ownership and truthful unreleased audit status. The screenshot index lists
only the 12 captures actually saved; completeness is still pending. Contribution instructions now point to
the actual configured test harness rather than an unconfigured bare pytest invocation.

The actual X13 PostgreSQL custom-dump integration passed (1 case, 163.04 seconds), executing both scratch
and restored verifier boundaries and its explicit corruption probes. The first attempt correctly refused
a mutation but the test expected the wrong earlier guard; the fixture was corrected to mutate a genuinely
registry-mapped field, preserving the exact mapped-value assertion. No production verifier was weakened.
Fresh LaneD selected-artifact/actual-dump admission tests are next.

Fresh complete frontend run: type checking passed; 1,580 passed and 3 failed out of 1,583 cases in 183 files
(368.06 seconds). The three failures were newly added test selectors confusing permanent toast live
regions / a route output with the target alert/status. They were corrected without production changes;
focused rerun is pending. Build did not run because the test command stopped on failure. Further Users
scope and backup UI changes mean a final full check is still required.

Rollback safety/fairness focused run: 111 passed, 1 failed (142.75 seconds). The failing fault-injection
fixture replaced shared os.fdopen with a contextmanager even for the actual host lock's a+ handle. It now
injects only at the cursor writer's wb boundary and preserves the actual lock API. Runtime rerun pending.

After installing age 1.3.2, eight of nine selected real-producer checks passed. The remaining complete-
manifest assertion compared JSONField arrays with the in-memory tuple representation; the expected entire
manifest is now JSON-normalized. Actual encryption/decryption and exact authenticated byte hashes remain
asserted. Runtime rerun pending.

The corrected Node20 UI subset passed all32 cases. The corrected cleanup cursor/real-age subset passed
all20 cases, including genuine source derivation and decryption. Earlier failed attempts remain recorded.
These focused counts overlap the complete suites and are not an additional unique-test total.

Local browser status proof: the labelled SYNTHETIC QA 3D Printer was set to Running, closed and reopened;
the badge, editor and public-status payload still showed Running. It was then restored to its original
Idle status, and the saved public-status payload showed idle. Captures: machine-status-running.jpg and
machine-overview.jpg. No real equipment operated; local audit-MAC key warnings reflect lost temporary
local test credentials and do not constitute a verified production audit-MAC deployment.

Additional fresh verification:

- All193 module-cleanup cases passed (157.68s), including native admin, receipt boundaries, accounting,
  handoffs and recovery fencing.
- Pure source-checker tests passed213 cases (4.93s), with exactly the explicitly unfinished real-corpus
  production-review integration deselected. This does NOT clear the release gate.
- Users active-scope checks passed all11 cases after correcting a new test's nonexistent Roles region to
  the actual Roles tabpanel. Type checking passed before the run.
- Reran all74 original core failures (two renamed tests mapped to their stronger replacements):69 passed;
  one stale servability exemption and four Linux-script tests failed on macOS. Removed the stale
  exemption (the canonical purge_intent check remains); its2-test file passed. Both relevant script files
  passed all16 cases in the Python3.12 Linux container. No shell production code was changed to hide this.
- Fresh npm audit and Python requirement audit report no known vulnerabilities. Saved JSON is under evidence.

The read-through continues to find concrete blockers. Open corrective groups include individual-unit
aggregate repair/scrap and asset-action lock races; password recovery visit/email/return-URL ownership;
public inventory/cart/session/evidence scope ownership; and the new signed-full recovery format's final
runtime verification. These must close before a final green/review/QA status.

Gallery now contains60+ current local captures, including all machine detail tabs and a320px dark check-in
layout. The checked-in layout uses a separately labelled synthetic makerspace with a reserved example.test
roster URL; no lookup was sent and no upstream presence/identity claim was fabricated. Its request remains
disabled until verification. Actual DOM measurements show aside static/overflow visible/no max height,
with no nested scroll and no document horizontal overflow at1280px and320px. Final gallery reconciliation
and settled-content recaptures remain pending.


Further continuation results (overlapping focused runs, not unique totals):

- All144 inventory UI cases passed after correcting actual Radix radio selectors, leaf API fixtures,
  generation-keyed session fixtures and mocks that had claimed refresh success without installing a
  token. Type checking passed. No production ownership assertion was relaxed.
- Loan return compatibility run passed60 cases and failed10 new fixtures: they attempted duplicate
  active product QRs, refused by the existing unique constraint. Corrected to a real unrelated direct
  loan of the same quantity product, and a two-product public batch. All18 new boundary cases passed
  on rerun (7.25s); actual stock/evidence/audit and no-double-credit assertions remain.
- Signed-full first runtime run:209 passed,15 failed outof224 (129.14s). Root corrected persisted active
  import-principal checks and extracted hardlink refusal before this run. Subagent is correcting
  unreachable immutable-row mutation fixtures, role-permission assumptions and real snapshot callback
  proof; no final success claimed.
- Gallery index expanded to all64 saved captures, including loaded Backup & restore and public Stats.
  More public/account/detail variants and final settled-content recaptures remain pending.
- Independent scope review approved deferring only the newlyintroduced unconditional whole-corpus
  certification release job. Release workflow restored byteidentical to HEAD. Strict opt-in checker,
  UNREVIEWED registry and failclosed validation remain. Actual certification is explicitly incomplete;
  no synthesized approvals. Behavioral test correction is in its separate Stage3 pass.

- All214 source-checker tests now passed (9.41s), including the real UNREVIEWED registry refusal.
  This verifies failclosed admission and fixtures, not whole-corpus certification. No case is deselected.
- All19 focused check-in dispatch/backup UI cases passed (9.52s), followed by type-check success.
  The two earlier backup test failures came from an arrow beforeEach returning its mocked function,
  which Vitest treated as cleanup and invoked without arguments. Braces corrected the test hook;
  restore instruction and unsafe-ID assertions are unchanged.

- Box functional guards passed all89 cases after providing the managed test client with a legitimate
  configured raw HTTP_HOST; host middleware and managed quota remained enabled. The20 new real-PG
  checkout/revoke/evidence races plus4 existing asset races initially passed23/24; one shared-photo
  fixture wrongly required a second charge when triage had already charged it. Its locked charge-state
  assertion is corrected; full24 rerun pending.
- Signed-full corrected run passed224/226 (144.86s), including all real dump/encryption/restore,
  exact restricted-role LOGIN and actual publication races. Two control cases compared an in-memory
  assigned FK string with UUID; a fresh persisted-row reload corrected the fixture and the full13-case
  control module passed. These overlapping results cover all226 unique signed-full cases. The new
  recovery/config/quarantine group is separate and remains unverified; do not call recovery ready.
- EVID-S01 report source now uses terminal retention state for live and old rolled object counts without
  rewriting historical rollups; recorded byte metadata is explicitly separate from storage/quota.
  Thirteen new cases plus existing report/retention compatibility checks are running.
- Fresh host Codex doctor0.160.1 reports authentication/provider reachability/WebSocket allOK (overall
  warning due nonblocking environment diagnostics). A child sandbox's internal network probe is not
  equivalent to the host inference gate.

- EVID-S01 report group passed all22 cases (13new plus9existing) after correcting the new retry test's
  claim-release expectation to the actual released token/time pair and asserting recorded provider
  failure. Old rolled periods, repeat rollups, tenant/range/month/local-day scopes and immutable metadata
  passed; no provider-presence/current-quota claim is made by those counts. Source report correction
  is complete locally; the retention policy/quota/origin findings S02–S05 remain separate and open.
- Signed-full control corrected13 cases exited0; all226 unique new cases covered by the final full run
  plus that test-only correction run. Recovery Stage2 is now actively implementing its separately
  approved safety/config/quarantine group; that changes source and will require a new full integration.

- Checkout/native/evidence/asset corrected concurrency group: all24 passed (48.47s). Shared-photo
  charged-state assertions now read the journal at the actual locked boundary, preserving every
  NO KEY UPDATE clause assertion and exact once-only quota checks.
- Public machine-service, borrow-reference and printing compatibility group: all78 passed (23.49s),
  followed by TSC exit0. Initial12 failures were test assumptions: refresh success without an installed
  token, in-place cache mutation/no observer delivery, and a completion invoked while A was still
  genuinely mounted. Corrected tests retain post-departure publication/retry negatives.
- Staff multistep upload/queue/manual action ownership is now in its separate bounded reviewed group.
  New recovery source is in Stage2; evidence policy/quota/origin S02–S05 is still in Stage1.
- Added a brief evidence-compliance UI note distinguishing recorded bytes/references from current
  stored-file presence; this text-only change will be included in final frontend checks.


Current active work / next runtime queue:

- Recovery source Stage2: /root/audit_backup_finish, CLI session66937. Required source/config/shell
  protocol, Task recovery gate and target default-queue generation. No new runtime proof yet.
- Evidence S02–S05 plus S06 declared-size cap: /root/audit_backend_finish Stage1 v3. Proposed actual
  debit marker with existing local database identity, conservative foreign/legacy credit0 and bounded
  evidence-only reconciliation. Reports.py/report_rollups remain root-owned/frozen and passed22.
- Staff queue/manual action and all private upload continuations: /root/audit_ui_finish Stage2 after
  approved expanded plan. Public-service source is frozen and its78 cases+TSC passed.
- Root box label/location max200 source approved/implemented/read. Stage3 testwriter session84223,
  /tmp/spaceworks-box-input-stage3.log/result. Need newAPIboundary+existingQR runtime afterfreeze.
- No currently running root pytest/full frontend job. Final complete suites have NOT started; source
  must settle first. Final schema regeneration, screenshot reconciliation, complete report/runtime
  ledger, mandatory background review, end-only owner QA and merged remote feature branch cleanup
  remain. All audit changes stay unstaged/uncommitted/local on dev.
- Gallery72 actualJPEGs; refreshed staff-inventory.jpg now includes complete top sidebar brand and
  settled unit/count rows. Screenshot manifest records SHA256; remaining private/detail variants and
  final recaptures still need reconciliation. Main README links and local contribution links validate.

- Retention safety/fairness/source-debit group passed all77 cases (68new +9existing), 99.53s. This
  includes real PNG/debit markers/all-version expiry, actual PostgreSQL winner orders for policy and
  promotion, conservative unproved/foreign/no-op credit and progress past failed first batches.
- Staff source+tests are frozen; targeted131new+relatedold machine/queue/handout tests +TSC running
  in root (use actual exec session ID from tool output); log /tmp/spaceworks-staff-ownership-round1.log.
- Hardware UI follow-on plan is approved, source not started: immutable Queues assign→issue and
  QR modal visits, DirectLoans issue/return bodies, concrete witnessed-waiver and delayed walk-in
  borrower selection. Intentionally requested same-actor background downloads are NOT classified bugs.
- Whole-counter recompute race is confirmed/read-onlyplan approvedfeasibility. Final lock continuity
  delta review running /tmp/spaceworks-storage-recompute-exclusion-delta-review.txt. Rootowns
  gate_locks.py/gate_runtime.py/recompute boundary/source guard; no codewrittenyet. Evidence-only
  helper remains child-owned/sourcefrozen. Needdedicatedbackendcountercommittoavoidcrossconnection
  check→SET gap, no application rowlocks overS3, no newmodel/billingframework.
- Root QR input3tests written/frozen89lines, APIruntimependingwhileevidence/recoverysourcewrites.
- Recovery first43-source group is beingverified; packagingaddonreviewneeded to ship exact25host
  dependencies and handleexplicitroot-ownedsupportedlayout. FreshUID0installer alreadykeepsroot
  ownership; defaultnonrootinstall needsdocumentedauthorityprep, neverblanketchownappdata.


Latest root checkpoint (2026-10-30; supersedes the earlier active-job list):

- Corrected staff ownership group:247/38 PASS75.65s, chained TypeScript exit0. Hardware
  follow-on12 source files frozen; separate test writer active, no further broad UI expansion.
- Combined QR/evidence group:127PASS63.57s, including OPS55, Boxinput3 and evidenceaccess44;
  durable qr-evidence-focused-round2.xml. Native/orphan QR and native audit/host-race follow-up
  is a separate source/test group, not covered by that earlier green result.
- Whole-counter recompute source +Stage3 frozen. First50 run48PASS/2strictFAIL104.45s found
  actual transaction-continuity proof gap. Approved tiny correction retains pg_current_xact_id
  alongside PID/exact lock tuple. Corrected all50PASS125.41s, durable round2 XML and
  storage-recompute-transaction-correction.json. Existing compatibility/source-guard run active:
  session32419, /tmp/spaceworks-storage-recompute-compatibility.log, DB55432.
- Procurement/warranty7 source files frozen before native audit delta; independent new tests
  authoring. Later2 native admin mixins and known move-vs-native warranty save race are explicitly
  gated in backend lane before finalfreeze. No new speculative billing ledger.
- Restore packaging source complete; final bounded authenticated-extraction/Redis implicitmount
  corrections still writing. Separate test phase and actual-host drill runner follow. No restore
  success or deployment claim. Actual Redis image declares/data and real Docker creates its
  anonymous local volume; compatibility must narrowly admit that existing volume, not move data.
- Official project verified public, actual install.sh/LICENSE readable, public backend/frontend
  latest manifest resolve. Custom TinkerHub exact0.8.5 versioned images return anonymous
  unauthorized. Source-default migration was NOT applied: incompatible upstream archive or
  unverified custom package availability cannot be treated as install proof. Current guide curl
  links point Labs; custom edition requires explicit compatible artifacts/sourcebuild. No live
  config migration. Original/revised conditional plan reviews in/tmp preserve rationale.
- Gallery remains72 actual captures; notifications recaptured with settled data/sidebar top and
  manifest refreshed. Browser viewport override reset; local tab2 markedhandoff, currentnotifications.
- Branchdev, indexempty; no commit/stage/push/deploy. Final currentfull backend/frontend,
  schema/migration/registry/security checks, finalbrowser/gallery/report reconcile, background
  uncommittedreview, remote mergedfeaturecleanup and end-only ownerQA all remain.

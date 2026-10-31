# Frontend identity, navigation and public lending source review

This is an actual bounded source read, not a discovery-derived approval or a
production-readiness claim. Reviewer: **Codex `/root/audit_ui_finish`**. The exact
file hashes and enumerated owner/site decisions are in
[frontend-context-decisions.json](frontend-context-decisions.json). The production
source registry has not been written or approved by this review.

## Exact reviewed denominator

| Packet | Fully read source files | Static context decisions | Pending correction/runtime |
| --- | ---: | ---: | ---: |
| A — browser API/session, auth, account | 21 | 21 | 0 |
| B — staff/member/invitation selection and shell | 22 | 22 | 0 |
| C — public lending, evidence and public chrome | 23 | 23 | 0 |
| D — route/tenant/module and directly read UI dependencies | 13 | 13 | 0 |
| E — new focused public-lending composers | 4 | 4 | 0 |
| F — public machine-service/printing/status | 13 | 13 | 0 |
| G — remaining original staff machine/stock contexts | 10 | 10 | 0 |
| H — unchanged final staff upload/queue/evidence contexts | 21 | 21 | 0 |
| J — remaining hardware contract dependencies | 4 | 4 | 0 |
| K — About and shared footer official/community links | 2 | 2 | 0 |
| L — unchanged active hardware corrective contexts | 11 | 11 | 0 |
| M — final walk-in receipt and canonical refresh contexts | 2 | 2 | 0 |
| Total | **146** | **146** | **0** |

All 146 listed files were read in full. Earlier corrected bodies were reread before
renewing observations; the three new hardware helpers were added only after complete
source reads. Zero files are unread within this bounded assigned set; remaining
repository files are not implicitly covered. Static Node 20 / locked-TypeScript
observations enumerate 1,712 lexical owners, 1,843 candidate sites and 4,237 call
edges. They supply locations and shapes, **not decisions**. Exact authored purpose,
authority boundaries and dispositions are bound to each source-file hash.
The last 14 contexts completed their bounded correction/runtime gates after root
verified the unchanged combined source. This is not whole-repository release approval.

Some sensitive code, including `sessionIntentStorage.ts` and `usePublicSession.ts`,
has no detector candidate site at all. Their complete bodies were still read; a
zero-site file is not a safety or completeness conclusion. Files/functions not
listed in the JSON, including partially inspected additional caller context, are
outside this decision set.

## Confirmed findings and current disposition

| ID | Actual source defect | Disposition |
| --- | --- | --- |
| REC-01 | `ResetPasswordPage` reused the legacy reset form across uid/token query changes; stale completions and passwords could appear under a different link visit, including A→B→A. | The separately reviewed local fix uses an exact pair key plus context-tagged owned form state. Root passed all 58 recovery cases (49 new plus nine compatibility), followed by TypeScript build. |
| REC-02 | Editable email could change from A to B while A's recovery request was pending, then A's acknowledgement/finally advanced or unlocked B's form. | The separately reviewed local fix binds request/confirmation/resend/cooldown state to exact email visit/action ownership. Root’s focused recovery run and TypeScript build passed. |
| REC-03 | The old root-relative `next` regex admitted slash/control/slash values which WHATWG URL parsing normalized to an external authority. | A pure URL normalization probe confirmed LF/tab examples. The local fix rejects controls/backslashes and checks normalized origin; dedicated actual-origin assertions passed in root’s recovery run. |
| LEND-01 | Unkeyed maker route reuse retained the public cart/details, and unconditional catalog placeholder reuse could display A's products under B's header. | Confirmed from `AppRoutes`, the page state and the placeholder callback. Implemented and verified in root’s 144-case inventory run plus TypeScript build: maker-keyed page state, same-maker-only placeholder and admitted-cart composition guard. Complete-suite/release approval is separate. |
| LEND-02 | Borrow draft/contact/idempotency/reference state and mutation callbacks lacked complete maker/person publication ownership. | Implemented and verified in root’s 144-case inventory run plus TypeScript build: desk-owned accepted completion, fresh person drafts, immutable bodies, guarded publication and body-bound retry keys. |
| LEND-03 | Checkout/return shared scans, evidence and results without a single synchronous admission owner or fully owned rendered mutation state. | Implemented and verified in root’s 144-case inventory run plus TypeScript build: one operation admission owner, captured bodies, owned results and current QR/camera/evidence state. No backend bypass was demonstrated. |
| LEND-04 | The infinitely cached public session Boolean could remain true after logout because its key lacked the auth generation. | Generation/cancellation checks and current-token projection passed the targeted inventory run plus TypeScript build; backend authentication remains authoritative. |
| LEND-05 | A raw presigned storage upload could complete after unmount/person/tenant change and call a stable parent evidence setter, overwriting the newer person's evidence. | Mounted/context/epoch/action fences before storage and completion, including camera-instance and semantic-reset guards, passed the targeted inventory run plus TypeScript build. No server authorization bypass is claimed. |
| LEND-06 | Check-in lookup callbacks are guarded, but its TanStack mutation function can still dispatch an already obsolete queued roster lookup. | The reviewed admission guard is implemented. All five held-dispatch regressions passed within root’s 19-case check-in/backup UI run, followed by TypeScript build. |

The four recovery source files passed the focused 58-case run in 9.11 seconds
([runtime log](password-recovery-focused.log)). The separate five check-in dispatch
cases passed within the focused 19-case run in 9.52 seconds
([runtime log](checkin-backup-ui-corrected.log)). TypeScript passed after that group.
The 13 public-lending source files passed root’s complete inventory folder run:
144 cases in 22 files, followed by TypeScript build. Initial fixture failures and
corrections are preserved in adjacent evidence; no identity/epoch/pending assertions
were removed. Complete-suite and release approval remain separate.

## Additional machine-service/status findings

The 13-file packet F was read in full (1,121 lines). New observations were attached only after those source reads; no runtime/static approval was inherited from catalog discovery.

| ID | Confirmed source finding | Disposition |
| --- | --- | --- |
| SERVICE-01 | Shared service page keys only maker/type; confirmed check-in state can revive on maker A→B→A and private form state lacks person/auth visit ownership. | Bounded correction implemented; root passed 78 service/printing/reference cases plus TypeScript build. |
| SERVICE-02 | Service form has no current owner fence through presign/raw storage/remaining files/final submit, progress or callbacks. Old settlement can unlock another current form. | Bounded correction implemented; root passed 78 service/printing/reference cases plus TypeScript build. Release approval remains separate. |
| SERVICE-03 | Service status completion callbacks/effects lack an exact current maker/auth/URL visit boundary. | Current-visit callback/persistence correction passed the focused service/reference run and TypeScript build, preserving explicit capabilities and same-browser fallback. |
| STATUS-01 | Borrow status reference draft is initialized once and can retain/re-submit the preceding maker/URL token. | Bounded route/draft correction passed the focused reference/service run and TypeScript build. |

The public machine catalog and service type queries use maker keys and numeric type IDs. The shared print form/presentation retains required identity/pending controls, advisory browser file filters, pool compatibility and server validation. The upload worker is a bounded queue helper; callers must own upload admission and progress. Legacy print routes delegate to the shared service page rather than creating a second workflow.

## Additional staff machine/upload/queue findings

Packets G/H contain the complete staff contexts listed in the decision JSON. The preceding staff corrective group passed separate Stage 3 authoring and root’s 247-case runtime plus TypeScript. The later active hardware delta passed the separate combined 341-case verification described below. No passing backend permission check is used to excuse stale frontend action attribution.

| ID | Confirmed source finding | Disposition |
| --- | --- | --- |
| STAFF-UPLOAD-01 | Machine document/public-image helpers resume after raw storage with a fresh staff request rather than the initiating generation. A newer actor can therefore finalize the prior actor's admitted operation if independently authorized. UI publication is likewise unowned. | Implemented original-session/resource/action guards through config, presign, raw bytes, finalization, batch continuation and UI publication across images, machine documents, warranty, procurement receipts, maintenance and handover evidence. The prior exact frozen source passed 247 focused cases plus TypeScript; overlapping handover caller bodies changed later and remain pending combined verification. Backend RBAC still applies; no permission bypass is claimed. |
| STAFF-UPLOAD-02 | Public-image maximum-size discovery permanently caches a rejected config promise, preventing a legitimate retry after a transient failure. | Implemented rejection-specific promise reset and valid-cap checks; explicit retry/size-cap tests passed in the 247-case staff run plus TypeScript. |
| STAFF-QUEUE-01 | MachinesPanel reuses type-local form/mutation state across different numeric type IDs. | Implemented exact numeric type key while preserving container-owned per-type service drafts; actual A→B→A cases passed in the 247-case staff run plus TypeScript. |
| STAFF-QUEUE-02 | Queue actions compute their bodies from live draft values inside a potentially paused mutation; another job/type can be selected and its draft later erased by the old completion. | Implemented independent machine queue/manual owners, immutable click-time DTO bodies, synchronous field/action admission and current-composition draft clearing; targeted cases passed in the 247-case staff run plus TypeScript. |

Additional reviewed corrections prevent primitive maintenance hooks from admitting paused actions under a newer actor/resource, keep result DTOs plain, clear parent evidence before a semantic-context first paint, and check latest native disabled admission. Warranty now blocks upsert before initial successful hydration, provides initial-load retry and preserves dirty metadata across background/document refresh. The exact preceding source group passed 247 focused cases and TypeScript; later overlapping hardware caller changes passed the combined verification described below.

The canonical pool UI remains type-first, does not duplicate filament into a local grams ledger, and uses server balances for its display. Public preview/status fields and role/machine capability projections remain separate from backend authorization. The staff workspace's maker-keyed panel mount was inspected as caller context; this does not add an unread StaffTabContent body to this decision set. `machinesApi.ts` currently has 326 lines and was read only; no additions or implicit ceiling exemption are made here.

## Explicit static boundaries inspected

- API publication checks survive header resolution, fetch, body decoding, retries,
  204 responses, bootstrap-key caching and Blob downloads. An anonymous fallback
  may adopt only its own synchronous clear; it must not adopt another login.
- The per-tab session pin contains only canonical intended identity, not a bearer
  token. Its parser does not claim signature verification. Refresh equality,
  generation/latch checks and verified storage invalidation are separate from the
  backend's JWT, origin and role checks.
- Auth components bind asynchronous work to mounted lifetime, exact visit, epoch
  and action sequence. Member and staff provider callbacks retain the original
  host intent. Google field typing does not request a new nonce per keystroke.
- Invitation redemption remains a backend single-use/non-escalating action;
  successful redemption does not itself install a staff session or clear a newer
  account's cache. Local installation failure is reported by the current owner.
- Staff routes resolve explicit/locked makerspaces ahead of stored hints. Global
  chooser rights and a maker's operational superadmin override remain distinct.
  The guarded session hook, server list and module/action projections control the
  UI; none bypasses a custom-domain origin lock.
- Public display components render public DTO fields and delegate submissions;
  they do not calculate stock, mint trusted identities or expose storage locations,
  private evidence, QR history or requester records. Their caller ownership defects
  are retained explicitly above instead of being excused by shared transport.
- Public and staff mobile chrome use the configured 60rem desktop breakpoint,
  remove modal-sheet isolation on transition, cancel pending account handoffs and
  keep labelled focus targets. This static read does not replace browser/assistive
  technology checks.

## Scope and evidence limits

No application source was executed by the observation pass; only the existing
static TypeScript parser ran under Node 20. No new runtime tests, external provider
verification, physical handover, production credentials or deployment operation
were performed for these source decisions.

The request to exclude nonruntime test helpers was respected in this decision set.
The current scanner still classifies `frontend/src/test/**` and several legacy
`lib/*TestHelpers.ts` files as production source. That classification discrepancy
was reported to the primary agent; those files have **no fabricated approval** in
this review. The final corpus must either classify them narrowly with verified
provenance or obtain separate actual decisions.

A contextual reread of `backend/apps/hardware_requests/self_checkout_views.py` and `self_checkout_workflow.py` confirmed that the backend resolves the current roster/member principal, matches evidence by maker/type/uploader, rejects consumed evidence, scopes QR resolution and verifies the loan requester. These backend files are context only and receive no ledger approvals from this frontend packet.

The primary assembler must compare each exact source-file hash and current owner/
site vector. Changed bytes require renewed context review. These records contain
no canonical global corpus fingerprint, and must not be copied automatically onto
later source. Backend/service and deployment reviews remain independent parts of
the complete audit.

## Active hardware caller findings and verified correction

Four additional caller bodies were fully read after tracing the photo props. They
initially received explicit pending decisions until their own corrective tests passed; no unchanged backend permission check or
passing evidence-widget test approves their broader mutation lifecycle.

- `Queues.submitAssignIssue` awaits assign-box then dispatches issue without the
  initiating epoch/visit check. Global action settlement can clear/toast an obsolete
  modal. Request bodies are captured for single stages; the multi-stage owner is missing.
- `QueuesAssignIssueModal` is actively reused without a row key. Its held QR resolver
  appends a previous request's scan after close/reopen for a different request.
- `BoxCodeField` has a cancellable maker-list read but no exact dialog/scan owner for
  the held QR resolver or retained scanner callback.
- `DirectLoans` builds direct issue DTOs from live form state inside mutationFn,
  keeps borrower/items/remark editable while pending, and resets the current form
  unconditionally on completion. Return completion is also unowned. `DirectLoanItems`
  can repopulate the parent via stable setters after its post-issue remount.

These are confirmed browser attribution/state defects, not demonstrated backend
permission bypasses. Root was notified before further source edits. Their bounded source correction passed root’s combined 341-case run, TypeScript and production build. Whole-repository production readiness remains a separate decision.
The old `handover/IssueDialog` has no active import beyond its re-export barrel; it
is recorded as dormant source, not silently approved for future reuse.

The seven actual hardware contract dependencies were also fully read. Three plain
DTO/list contexts received explicit static decisions. Four required the bounded hardware correction: witnessed
waiver live subject, walk-in creation/late selection, parent accept-modal visit, and
assign-box container invalidation. Their final source contexts were reread and
passed the combined test/runtime result below. `DirectLoanList` does not get an invented
unmount-cancellation rule: a current-actor explicitly requested download can finish
in the background, and canonical response decoding rejects a different actor.

About and shared-footer source were fully read. The use/install card and AGPL
license point to SpaceWorks-Labs/SpaceWorks; community contributions point to
tinkerhub/SpaceWorks. Fixed external anchors include safe new-tab relations and
accessible notice. This static link/configuration check does not assert external
GitHub availability or replace the About-page runtime test.

## Active hardware correction source freeze

The approved follow-on group corrected the recorded active hardware defects in
12 source files (nine existing plus three focused domain helpers; maximum 207
lines). Complete final bodies were read after Stage 2; exact bytes are in
[ui-hardware-ownership-source-freeze.json](ui-hardware-ownership-source-freeze.json).
Parent maker/session and modal/form visit boundaries own immutable workflow DTOs,
optional assign-to-issue continuation, synchronous pending edit admission, concurrent
asset scans, scalar native camera openings, waiver subject and delayed walk-in
selection. A separately reviewed repair makes readonly container-list ownership
independent from temporary edit pending state. No additional generic lifecycle
framework, backend workflow mutation or dormant-dialog change was introduced.

The preceding staff group passed root’s 247 cases across 38 suites in 75.65 seconds
plus chained TypeScript exit 0 (session 89449). Those earlier facts cleared only unchanged
exact source contexts. The combined 341-case run subsequently verified the final
overlapping handover bodies, hardware group and unchanged accept-modal caller
contract against their exact reviewed hashes.

## Created-person / roster-refresh closure

The separately approved small follow-on now retains the actual server creation
receipt before selection refresh, blocks creation replay and clears successfully
submitted draft fields. Its focused helper observes the exact canonical roster
query and actual non-manual fetch success; failed/paused/missing/disabled/absent
results cannot select. Late pause during retry releases local UI, consumes eventual
rejection and retires superseded attempts without cancelling legitimate shared
reads. A post-await proof check prevents manual cache or query replacement from
authorizing a stale selection. These two final bodies were fully read; exact bytes
are in [ui-walkin-roster-source-freeze.json](ui-walkin-roster-source-freeze.json).
The 27 separate real-query cases and earlier 67 hardware cases passed within the
combined 341-case verification below. Their context decisions remain bounded static
review plus focused runtime evidence, not release approvals. The combined current
staff/hardware source freeze has 34 unchanged files.

## Final bounded staff/hardware verification

Root verified **341/341 cases across 50 files in 113.47 seconds**, followed by
`npx tsc -b` and `npm run build`, both exit 0. The production build completed in
2.46 seconds with the existing greater-than-500 kB chunk advisory. Exact source
hashes for all 34 combined files and the unchanged accept-modal context still
match their complete reads. The explicit JSON now records 146 reviewed contexts
and zero pending contexts within this assigned set; it does not write or approve
the canonical production ledger.

The initial combined run passed 338 and failed three fixture assertions: duplicate
combobox/native-option text in two container tests and native email whitespace
normalization in one failed-create draft test. Narrow test-only corrections retain
exact container options, name/phone preservation and all owner/body/pending
assertions. Both [initial](ui-staff-hardware-initial-runtime.log) and
[corrected](ui-staff-hardware-corrected-runtime.log) logs are preserved. Test hash
metadata was refreshed only for those two files. Whole-frontend, backend, provider,
physical handover, deployment and final release gates remain independently owned
by the primary audit. No production credentials or production mutations occurred
in this lane.

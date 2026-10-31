# Backend audit follow-up

Status: verification in progress. This handoff records the resumed source inspection, not a
passing release or a replacement for the final whole-workspace review. Earlier temporary
logs were unavailable after the local runtime restarted; their historical counts must not
be promoted into new passing evidence.

## Scope and source inspection

- The X13 source fixture now creates an actual open tenant PII write fence for each
  bulk-inserted makerspace and supplies the payment's required creator. Bulk insertion
  retains PostgreSQL constraints and intentionally avoids unrelated application signals.
  No production constraint or verifier has been bypassed.
- The cheap fixture preflight recreates one built-in machine type after transactional
  test flushing. The real integration creates fully migrated scratch databases instead.
- The substantive X13 case is
  `tests/tenant_migration/test_x13_builder_boundaries.py::test_real_builder_custom_dump_roundtrip_reconciles_both_boundaries`.
  It exercises the production verifier before and after an actual custom-format PostgreSQL
  dump/restore. Its explicit mutation probes do not replace either successful verifier
  invocation with a mocked result.
- Lane D has eleven `test_x12*.py` files containing 52 top-level test functions before
  parametrization. Their exact executed case count must come from the new test run.
- Rollback cleanup now rereads durable restore/recovery outcomes before destructive
  provider work and settlement. A free host lock or `NORMAL` mode alone is insufficient:
  unfinished, failed, aborted, missing or unknown outcomes retain recovery copies and
  their database locators. Acknowledged quarantine can retain its terminal active pointer.

The independent bounded source review completed with one actionable P2 finding:
expiry sweeps repeatedly inspect the first fixed-size batch, so indefinitely retained
failed restores can starve later completed restores. A bounded, progressing scan is
under corrective plan review; no outcome or source-fence bypass is authorized.
The review found no additional actionable issue in its selected-artifact/resume or
private dump-snapshot scope. This is source-only evidence, separate from the mandatory
final review of the entire uncommitted change set. See
[the exact review result](backend-boundary-source-review.txt).

## Focused verification order

Run from `backend/` using the configured local test database owner, matching PostgreSQL
client major, and the existing private test environment. Never publish that environment
or run two pytest processes against the same database.

1. Run `tests/test_audit_x13_fixture_preflight_tmp.py`; remove this temporary test only
   after confirming the fixture works and retaining the actual integration below.
2. Run `tests/tenant_migration/test_x13_builder_boundaries.py`.
3. Run `tests/backup/test_rollback_cleanup_outcome.py`,
   `tests/backup/test_module_cleanup_rollback_fences.py`,
   `tests/tenant_migration/test_module_cleanup_source_contract.py`, and
   `tests/tenant_migration/test_purge_source_contract.py` together.
4. Run `tests/makerspaces/test_module_cleanup*.py`,
   `tests/backup/test_module_cleanup_restore_barriers.py`, and
   `tests/tenant_migration/test_purge_receipt_import_fences.py` together.
5. Run all `tests/tenant_migration/test_x12*.py`. The derivation and repository-client
   integration cases perform real source production; the source-catalog file also has
   a scratch-database case. A structure-only fixture is not a substitute for those runs.

Runtime results: pending execution by the primary agent. Do not sum overlapping focused
runs into a unique suite total. The final complete backend suites remain required after
the remaining source corrections stabilize.

## Corrective test fixture follow-up

The first resumed actual X13 roundtrip reached the verifier and refused the corruption,
but its `mapped_raw` test expected the wrong guard: `accounts.User.email` is not a field
in the scoped PII registry. The helper now changes the single source registration's
`events.EventRegistration.name` through the existing raw SQL helper. The exact
`Mapped raw values` assertion remains, and ordinary non-mapped content retains its
separate frozen-row assertion. The cheap schema smoke passed one case before removal;
the actual custom-dump integration must be rerun. No production verifier changed.

The actual age derivation test later exposed a separate representation mismatch:
PostgreSQL's `JSONField` stores sequence-state tuples as JSON arrays. The regression now
normalizes the complete expected manifest through strict JSON serialization before
comparing both the persisted and decrypted manifests. All source-catalog, real decryption,
selected-reader and exact emitted-byte SHA checks remain. This changes only the test's
representation comparison; the derivation case still requires a passing runtime rerun.

## Rollback cleanup progress implementation

The independent plan review approved a private, non-authoritative scan cursor under
the configured `BACKUP_OPS_DIR`, inside the shared writable work mount. Each sweep
retains the existing maximum number of examined rows and advances across retained,
frozen, source-closed and provider-failed rows. Subsequent sweeps wrap so later eligible
rows can be visited. The existing host lock and all fresh recovery/source/frozen-object
checks continue to authorize each deletion independently of scan progress.

Stage 2 wrote `backup/rollback_cleanup.py` and `backup/rollback_cleanup_progress.py`.
The new helper was added to the portable authority-source inventory during independent
verification. The existing narrow module-cleanup structural source guard passed against
the current source; no delete/fence/outcome guard was relaxed. Separate Stage 3 wrote
25 cases: 19 cursor-trust/process/fault cases and six real-row fairness cases. All three
test/helper files remain below 300 lines. Static syntax/whitespace checks passed;
runtime closure remains pending. Run `tests/backup/test_rollback_cleanup_progress.py`
and `tests/backup/test_rollback_cleanup_fairness.py` together with the existing outcome
and source-fence cases. Exact current file hashes are in
[backend-followup-freeze.json](backend-followup-freeze.json).

Proposed operator wording for the primary agent to merge after implementation:

> Rollback expiry progress is stored in `BACKUP_OPS_DIR/rollback-cleanup-progress.json`.
> The work directory and progress file must remain private and owned by the runtime
> user. Production already shares the work directory across workers; do not move the
> cursor beside the separately mounted root-owned operation lock. The cursor controls
> traversal only and cannot authorize deletion. Failed and aborted restore copies remain
> retained without an automatic expiry override; do not edit their stage to force cleanup. A
> `rollback_cleanup_progress_unconfirmed` diagnostic means that individual cleanup may
> have completed but durable scan progress was not confirmed; preserve the actual
> cleaned/skipped counts, fix local storage permissions or capacity, and retry. Settled
> rows prevent a retry from crediting storage twice.

## Selected-workspace Users panel follow-up

The primary agent's browser audit found that the Users panel could show the first
makerspace in the account's list while the header showed another selected space. The
source confirmed that Users initialized its own local scope from that first list item.
The approved correction is confined to `StaffTabContent.tsx`: pass only the active
makerspace to Users and key its React instance by that makerspace's id. Workspace
switching now resets staff forms and role targets along with the scoped queries.

The global superadmin Create makerspace action and chooser-list invalidation remain;
creation does not implicitly change the active workspace. Full cross-space lists remain
available to the transfer, reporting and scanner panels that intentionally use them.
The existing oversized Users module was not changed. Separate Stage 3 wrote five
real-component regressions for scoped reads, staff submission, workspace form/role reset,
global makerspace creation and permission denial. Only the external `staffRequest`
transport is mocked; Users, its descendants, modal, tabs and query cache remain real.
Runtime validation remains pending. Exact Stage 1–3 handoffs and file hashes are retained
beside this file. Run `StaffUsersScope.test.tsx` with `panels/UsersInvitations.test.tsx`
under Node 20, then retain the required full frontend validation.

## Individual stock and fix-shelf follow-up

Actual inventory source review found aggregate repair/shelve/scrap could change counts
without changing individual units, asset status eligibility could become stale while
waiting for its row lock, and the fix-shelf quantity fallback treated explicit zero as
the full shelf quantity. Approved Stage 1/2 corrections now reject individual aggregate
operations after the product lock, validate fresh asset state after its actual lock,
use non-key maker plus asset-only row locking, and expose the existing unit manager
from the shelf. Only untouched quantity input defaults to the displayed shelf count;
invalid values disable actions and the mutation revalidates any open confirmation.

Separate Stage 3 produced 15 backend cases and nine frontend cases. This agent has read
the new tests and source independently, but did not run them. The root audit coordinator
owns actual results. Exact frozen source/test hashes are in `individual-fix-freeze.json`.
Central targeted commands, from the relevant project directory:

```text
# backend/; actual PostgreSQL and the root coordinator's private runtime environment
python -m pytest -q tests/test_individual_fix_boundaries.py tests/test_individual_fix_lifecycle.py tests/test_asset_fix_concurrency.py
# frontend/; Node 20
npm test -- src/features/staff/panels/NeedsFixShelf.units.test.tsx src/features/staff/panels/NeedsFixShelf.quantity.test.tsx
```

The backend cases retain genuine image validation, request acceptance/issue/return,
unit and container scan expectations, immutable evidence/audit checks and observed
independent PostgreSQL session waits. They include the implicit accepted reservation
that leaves an asset AVAILABLE while its product has no unreserved available stock.
No live physical count was inferred or automatically reconstructed by these fixes.
The root must regenerate the OpenAPI snapshot/client after all source groups settle.

The separate 19-file hardware source decision packet records three additional open
checkout/return findings; these are not closed by the inventory fixes. The evidence
report finding `EVID-S01` is also pending. Source-review coverage and runtime verification
are separate, and none of these bounded packets asserts whole-application readiness.

Root's first central individual-stock run reported 11 backend passes and four
concurrency proof-helper failures; all nine new frontend cases passed. PostgreSQL's
configured activity-query length truncated wide SELECT text before its FROM clause.
The test helper now captures the complete executing SQL with Django's execution
wrapper, then requires the same independent waiter PID/blocker lock edge and matches
the server-reported statement prefix before checking the full table/lock clause.
Timeouts and server configuration were not changed. This correction awaits the root's
central rerun and is not a production behavior change.

## Box checkout and QR correction follow-up

Approved v3 plus its nesting addendum now freeze eleven production source files in
`box-checkout-source-freeze.json`. The original mixed-box automatic unit issuance was
removed: every individual unit needs its own QR, with an optional separately selected
staff container. A shared tenant-scoped subtree guard refuses implicit parent checkout
when nested available hardware would otherwise remain recorded in stock. Quantity
stock stored directly in a box still uses box QR checkout. Scanner eligibility uses
the same refusal and existing reviewed/public container occupancy checks.

Public/direct checkout, reviewed issue, public return and triage now use compatible
short evidence-first, non-key makerspace coordination. Native QR revocation owns its
fresh row lock and rechecks outstanding loans inside its own transaction; the API
serializes the resulting fresh instance. Runtime proof of the concurrency group is
still pending its separately owned Stage 3 writer and root execution.

The root's functional run passed **89 cases in 23.20 seconds**: 84 new cases and five
existing cases, including the corrected mixed-box expectation. The durable XML is
`box-checkout-functional-host-corrected.xml`. Two initial runs were refused before DRF
by the managed host middleware because fixtures omitted the actual infrastructure
Host. The corrected fixtures keep the middleware and finite managed quotas enabled,
configure testserver as an infrastructure host and send raw HTTP_HOST=testserver.
Those setup failures did not establish any application regression or pass.

The separately generated concurrency group is now frozen in
`box-checkout-test-freeze.json`: 20 new PostgreSQL cases plus the existing four asset-fix
cases. It observes independent session PIDs, the actual server blocking edge and full
executed SQL. Coverage includes competing public/direct boxes, reviewed issue versus
selected-container units, the actual native ModelAdmin revoke action, real rebind
scan/audit foreign keys, triage's domain evidence lock and a real retention sweep
finishing before attachment. Validation barriers always call the real functions;
finalization-only waits are distinguished from the intended domain waits. No race
case was deferred. The managed race fixture explicitly configures and sends the raw
infrastructure Host just as the passing functional fixture does. The root must execute
the group; no concurrency pass is claimed here.

Evidence S02–S05 now have a read-only Stage 1 plan review pending. EVID-S01 report
semantics and sources belong to the root. The old evidence packet is retained as
`evidence-source-decisions-pre-no-key.json`; its finalization entry and the root's
changed report source must be deliberately re-reviewed before any final ledger bind.

Root's corrected concurrency group passed **24 cases in 48.47 seconds**, recorded in
`checkout-lock-races-corrected.xml`. That comprises 20 new races and four existing
asset-fix races. One first-run expectation incorrectly required a second quota lock
for an image already charged by winning triage. The corrected observer reads the
fresh journal only after the actual Maker lock completes; all no-key SQL and exact
once-only charge assertions remain. The 89 functional and 24 race groups are separate
targeted evidence and must not be presented as whole-suite or release approval.

## Further source review and pending verification (2026-10-30)

The source-review packets now explicitly cover 108 of 242 top-level Python files across this lane's seven apps. **134 top-level files still have no explicit packet**, and nested management commands/migrations are outside that denominator. This is source reading coverage, not runtime approval. Historical packet hashes are deliberately not silently refreshed after later fixes.

| App | Current top-level files | Explicit packet files | Without packet |
|---|---:|---:|---:|
| inventory |36|18|18|
| hardware_requests |57|19|38|
| boxes |17|0|17|
| evidence |21|19|2|
| operations |80|21|59|
| procurement |18|18|0|
| warranty |13|13|0|

New full-read packets: operations physical 21 files/227 lexical owners; procurement18/136; warranty13/108. Findings are in operations-qr-open-findings.md and procurement-warranty-open-findings.md. These packets record individual purpose/runtime boundaries and exact hashes; they do not approve whole apps or replace root's final census.

Evidence safety source is frozen (S02–S07). Separate retention Stage3 writer added68 cases across five test modules plus the existing retention module; access/recompute/export writer added44 cases in four modules. Root's first access run:41 passed,3 fixture-only memoryview deepcopy errors. Corrected test-owned full-row clone converts binary memoryviews to exact bytes without dropping any fields; corrected rerun pending. Runtime results remain root-owned. Projection/import metadata tests do not imply an executed host restore artifact.

OPS-S01–S03 Stage1 approved and Stage2 source independently inspected: three files with exact QR text bounds, suffix-preserving derived descriptions, atomic actual-change QR audits and Maker-before-batch print module gate. Source manifest: operations-qr-source-freeze.json. Separate Stage3 test writer running; no runtime execution by this child. Root retains whole-counter recompute lock boundary and sourceguard ownership.

Procurement/warranty follow-up Stage1 review is running read-only for real accepted-document quota admission, initial procurement status attribution, native machine provenance validation, serialized sparse warranty updates with atomic audit and immutable existing warranty hosts. No source edits there yet.

## Verified focused groups and final known closures (2026-10-30)

Root completed canonical `evidence-retention-round1.xml`:77 tests passed,99.53s. The test freeze's nine files still match exact hashes. The evidence source freeze's nine non-command files match; its original recompute command digest remains historical because root replaced that separate boundary. This retention result does not assert command coverage.

Root completed `qr-evidence-focused-round2.xml`:127 tests passed,63.57s. It includes all55 OPS regressions, the existing portable snapshot case/reference checks, box varchar boundary tests and old QR APIs, and all44 evidence access/size/recompute/projection cases. The memoryview fixture correction passed. Manifests bind the actual JUnit hash and matching file bytes. These are overlapping focused groups; never add them into an invented whole-suite total.

Document/procurement seven-file source is implemented and independently read (29–221 lines), with the separately approved five-call-site `no_key=True` refinement. The existing canonical asset transfer may still move a warranty deliberately; native form host changes are refused. New document quota charges use actual validated bytes, transactional metadata/audit, same-key retry idempotence and no speculative legacy deletion credits. Separate Stage3 tests are being written; runtime pending.

Root confirmed missing native AuditLog entries in WarrantyAdmin; same omission confirmed in ToBuyItemAdmin. A separate approved delta adds the existing canonical AdminAuditMixin in the documented storage/audit/superuser order, with native add/edit/no-op/privacy/rollback regressions still to write. This supersedes the two original source-freeze admin hashes after the writer completes.

BOX-S03/04/05 are source-confirmed and their bounded Stage1 plan approved: tenant-qualified missing-target404 before scan writes; usable native-created box QR; shared atomic Box+QR+audit and atomic tool/scan mutations. Stage2 is running in only the approved files, alongside the two tiny native audit mixin changes. Broad additional exploration is paused by root until this known set is closed; this does not mean remaining unexamined owners are approved.

## Native source checkpoint and central runtime handoff

`qr-native-current-source-freeze.json` records12 independently inspected current source files, max290 lines, superseding the explicitly named historic snapshots. The shared canonical admin bulk-delete helper now wraps AuditLog writes and Collector deletion in one transaction; Box's redundant wrapper was removed. Its native creation remains the single explicit `qr.box_created` action, while existing edits use canonical field-name-only audit. The Box creation Maker lock is separately reviewed `NO KEY UPDATE`, preserving module serialization and FK compatibility.

Native Warranty source admission now pins the POST's initial tenant before Django opens its transaction, then locks Maker NK → concrete host → fresh visible warranty. A canonical asset transfer winning after that snapshot produces404 without native mutation or wrong-tenant audit. The request locking flag exists only inside the actual change form; the storage deletion mixin's pre-atomic object lookup is unchanged. Crafted change `_saveasnew` is refused. Both source files were read in full and have their own source freeze.

Three new test sets are independently fully read and source-frozen:161 document cases,126 QR/native cases,30 native Warranty cases (317 statically expanded cases total, actual root collection/results pending). No child runtime was executed. All native test rows use real authorized clients, domain serializers/validation and actual PostgreSQL locks; provider tests replace transport only.

The shared admin transaction guarantees canonical application AuditLog and domain deletion rollback. Django's separate native LogEntry writes precede `delete_queryset` in its bulk action and remain outside that helper boundary; do not claim full diagnostic-row rollback for a failed bulk request. Additional Box edit/bulk tests explicitly scope this distinction.

One final bounded parent create/edit/delete race remains source-planning: preserve the existing Box.parent SET_NULL semantics, align all native/API parent writers and native Collector discovery through existing Maker locks, reload after waits, and refuse missing parents cleanly. Root requested this within the known QR closure. The Stage1 review is read-only; no source writes will overlap root's317-case run.

## Central317 result and remaining two bounded source groups

Root completed `documents-qr-native-round1.xml`:317 collected,304 passed,13 failed (467.24s). Actual class-name partition: document_safety161 passed, native_warranty30 passed, QR/native126 had13 failures. Nine are the test helper `native_form(client, name, **changes)` colliding with a ToBuy `name` field; root owns the argument rename. Four are real QR source-gate failures: genuine QUIESCED gate still permits Box/product/asset QR creation and explicit scan201. Strict423 assertions remain unchanged. Exact XML hash/failures are in documents-qr-native-round1-triage.json; only the zero-failure subgroups were bound to their unchanged test/source bytes. Do not call the full317 group green.

Root released the source hold. Parent create/edit/delete Maker-lock Stage1 approved and Stage2 is active in only boxes/services.py, admin_forms.py, admin.py, new admin_lifecycle.py and operations/views_containers.py. It must preserve SET_NULL, refresh targets/parents after waits, serialize native Collector discovery and all parent metadata writers, reject disappearing targets without resurrection, keep explicit native fresh/hidden/active/no-password-rotation admission, and stay below300 lines. Pending result `/tmp/spaceworks-box-parent-stage2.txt`, log with matching stem.

The QR source-gate follow-up is separately Stage1 read-only (`/tmp/spaceworks-qr-source-gate-stage1.txt`). Actual QR mutators include creation, scan, resolve lookup, revoke and rebind plus native callbacks. Source N must precede Maker/QR/asset/product locks and survive commit; cross-maker rebind admits both scopes in stable order and refuses changed tenant identity instead of acquiring a new scope under locks. API revoke currently takes QR before calling its service, so merely adding a late service assertion is unsafe. No source writer may overlap the parent group's shared services.py; wait for its freeze and rebase the approved source-gate implementation onto it.

The independent Box edit/shared bulk extension is29 cases in test_native_box_audit.py plus native_box_audit_helpers.py, both fully read and frozen. Its structural Box delete owner assertion must be corrected to the upcoming lifecycle wrapper's actual MRO/delegation, while Category remains the direct shared Audit owner. Preserve all domain/canonical AuditLog rollback assertions and the explicitly separate native LogEntry attempts.

No child runtime, staging, commits or pushes. Root remains sole backend runtime coordinator, and owns generated schema, source census/guards, final review and user QA. Only these confirmed source groups remain in this child's active scope; broad additional exploration stays paused until they close.

## Parent Box source inspected; QR admission revision

Parent Stage 2 five sources were independently fully read and AST parsed, max291 lines. Source freeze: box-parent-source-freeze.json. Native source admission spans Django change form; Maker NK serializes fresh native form/deletion Collector and existing API Maker UPDATE. Fresh parent/target reload preserves SET_NULL and refuses resurrection. Separate Stage 3 writer is active; no runtime result yet. QR source-admission Stage 1 requires two concrete additions: retained native QrCodeAdmin edit/delete and native asset generation. Revised scope is undergoing a second read-only approval; no source writer overlaps Box parent sources. The four genuine QUIESCED423 expectations are unchanged.

Parent Stage 3 is frozen and independently fully read:77 planned cases in seven new box_parent_safety files, plus the exact existing native Box MRO assertion correction (29 existing cases). Durable box-parent-test-freeze.json records hashes and root-only command. No child runtime. Actual PostgreSQL fullSQL/PID blocking edges, both delete/writer orders, Collector SET_NULL, sparse omission, disappearing targets, fresh policy, FK compatibility, stable bulk ordering and outercommit source ownership are authored; passing behavior awaits root. Related source runtime should wait until the combined QR source writer freezes.

## Final QR source closure and separate tests

Main approved QR source group is independently fully read, max288 lines. Final11-file freeze: qr-source-final-source-freeze.json. New qr_admission.py and admin_qr_lifecycle.py have explicit per-owner review in qr-source-helper-decisions.json (2 files/26 owners), with runtime-pending decisions. Source N is admitted before QR/asset/product/Maker locks and retained to commit; effective native action selection including select_across is frozen by PK; changed tenant/target never causes late foreign admission. Native ordinary QR edits/deletes use canonical audit; custom revoke/rebind retain service events. Generation native=True is caller-private; API defaultFalse membership semantics remain.

Independent verification corrected native disappeared/moved QR selection from raw DRF Conflict (outside DRF would500) to scoped Django Http404, without changing API409 behavior. Tiny separately approved resolve POST correction now records its actual immutable lookup scan and one qr.scanned canonical audit atomically; read-only Print GET remains unchanged. Six QR mutations and AssetGenerate document typed423/503 source errors; generated artifacts remain root-owned. Separate QR Stage3 test writer is active; no runtime was run here. Parent77/newQR/existingnative29 should run against this combined frozen source.

## Owned QR mutation source freeze for host snapshot

All owned non-test backend writers are idle. Final qr-source-final-source-freeze.json now records the independently inspected AssetQr and print-item closures (services191, views214). Historical pre-target-race source snapshot retained explicitly. AssetQr refuses a moved/deleted asset after actual row waits without old-tenant QR/audit; print-item mutation fresh-locks its original-tenant QR before deriving target snapshot. Module Maker NK exclusion avoids transfer audit FK inversion. UI lane separately owns the confirmed historical nested live-QR read exposure, preserving immutable item snapshots and later legal QR moves. Three separate test-only writers are active in distinct new directories; source is ready for root sanitized host archive capture, not a passing-runtime claim. Root reported parent77+existingnativeBox29 ALL106PASS300.01s on its immutable source snapshot; no child runtime and no count sum with other groups.

## Actual main QR result and finite follow-up checkpoint

Root actual399 run (main273 + existingQR126) completed371PASS28FAIL687.11s. Exact XML hash and failure names are in qr-source-main-combined-round1-triage.json.25 are global source middleware/JWT consulting gates before real role/origin denial;2 are API rebind source-high N admitted before destination-low despite later service sorting;1 is a test controller holding Product then attempting Maker hide while API already holds Maker and waits Product (impossible committed winner, actual deadlock). No expectations weakened. Root9 generated schema controls passed; original4 strict genuine closed-source cases also passed separately. Root27 native-document controls and parent106 passed separately; no sum into full-suite total.

Current read-only ownership review: /tmp/spaceworks-qr-http-ownership-stage1.txt (session59442). Candidate exactly reviewed QR POST callbacks with fail-closed actual callback/service binding; canonical services authorize/origin-check before retained Source N; middleware and JWT late assertion must share ownership decision. All other routes/default guard/purge behavior remain. No global source edits by this child yet. Generation fixture Stage3 correction /tmp/spaceworks-qr-generation-fixture-stage3.txt (session74005) preserves9 coherent negatives and replaces impossible product+hidden winner with3-session serialization: hidden updater waits behind API Maker while API waits Product, then valid generation precedes hide.

Asset28 actual27PASS1FAIL71.75s: sole failure observed no new dedicated backend before cancellation. Root-approved test-only source_observations correction discovers live pg_locks first, then clears PostgreSQL statistics snapshot before owned PID SQL; strict genuine cancel/503/no-write assertions retained. Corrected helper hash59fe70fe0520fa30db251d8415e8e710be497a216977ff844684583d3da58a18; root rerun pending. Both Asset and print fixture opt-in modules were legitimately enabled, without disabling guards.

Print76 test group fully independently inspected and ready (60 prior +16 fresh policy); source service194lines now refreshes actual User and MANAGE_QR after QR wait. All these source/test writers exited. UI lane owns serializers/qr_zip/native download adapter/frontend null handling. Root typed ErrorSerializer annotations were actually read and current source hashes explicitly rebound; generated schema/types remain root-owned. No child runtime, staging, commit or push.

### 2026-10-30 — bounded QR HTTP ownership final test handoff

All three runtime ownership sources are independently read and source-frozen. The exact eight POST registry delegates tenant admission to existing authorized canonical QR owners while retaining the middleware shared unscoped writer lock across authentication and response dispatch. Unknown routes, other methods, print-item writes and original purge ownership retain their existing boundaries. No auth, permission or source lock primitive was bypassed.

The separate supplied-source guard checks exact declarations, actual URL/barrel/class/own POST and consumed services, all nine retained sorted source-admission edges, callback identity, middleware P ordering and the late trusted-P requirement. Two new guard files are below300lines; the existing global guard only wires this check in its actual APPS_DIR branch. An independent verification correction added audit.record to protected writes. No model or authority-field decision moved, so no new AUTHORIZATION_SOURCES path is required for these static guard files. Root owns final census bindings.

Independent review of the16-file runtime test group is complete:473 static case products in30functions;270 supplied-source contract products in two separate files. These numbers are authored static products, not passing or collected runtime results. The exact file/source hashes and root commands are frozen in qr-http-ownership-test-freeze.json and qr-http-source-guard-test-freeze.json. Both groups are ready for root execution. Production writers are idle; no tests, collection, Django imports, builds, staging or commits were run by this reviewer.

### 2026-10-30 — claim presence and global conversion source closure

A final source-policy review distinguished deployment-global auth telemetry from exported tenant presence. Canonical claim revocation already ends its presence atomically, and ordinary presence expiry is bounded by the claim deadline; the sixteen authored invalid-claim cleanup cases deliberately inject inconsistent legacy rows and are now labelled that way. The real reachable source-freeze gap was native/OIDC walk-in conversion invoking the claim revocation hook under only global admission.

The nine-file source closure is independently read and frozen in claim-source-final-freeze.json. Native and bound OIDC adapters admit the complete DB-derived membership namespace set before identity row locks and retain it through the real atomic commit. Growth after the User lock causes retry instead of acquiring a new namespace under row locks. Native acting-admin authority is reloaded after waiting; OIDC identity/collision validation occurs before source admission and repeats on locked rows. OIDC locks Membership before User, while the hook now locks only claim rows rather than implicitly locking joined memberships. Defensive inconsistent-row cleanup takes its actual owner's namespace and defers when frozen, unavailable or not restored while keeping authentication401 unchanged.

Dedicated-origin middleware may already own a raw shared source reference. Same-key reuse now validates that reference's original PID, transaction and exact granted ShareLock, preserving rollback/close on failure and avoiding reacquisition behind a queued exclusive writer. P=0 remains distinct from tenant admission; genuinely new lower namespaces are refused before any new acquisition. The original exclusive owner protocol and counter bridge remain intact. Root separately reviewed these bodies, registered the actual native authority owner, merged operator/source-map wording and started the fourth isolated host topology with these exact source bytes. No runtime was executed by this child. Separate claim/cleanup/retention tests remain under authoring and independent review; no production readiness is asserted.

### 2026-10-30 — final claim regression freeze and confirmed audit-FK race

Root reproduced the exact canonical issue-versus-native transition interleaving: the two-case group produced one pass and one real PostgreSQL deadlock. The issuer retained a Maker FOR UPDATE while waiting for the target User; the native conversion retained that User and needed the Maker FK check for its tenant audit. A separately reviewed one-line change in `makerspaces/staff_authority.py` now uses NO KEY UPDATE for the immutable Maker primary key, preserving metadata/authority serialization while allowing the audit FK KEY SHARE. Actor checks, scope and downstream lock order are unchanged. Exact source SHA is c6ea7cdab5410417e496099859e83c042ecce44ea71eacd8d100886e8fc15646. Strict race expectations were preserved.

All claim test authors have exited. `claim-source-final-test-freeze.json` binds fourteen new files with fifty AST parameter products plus the existing473 HTTP products. The two unchanged native/valid-claim control function hashes and thirteen untouched HTTP files match the earlier freeze. Sixteen legacy/fault cleanup cases now prove actual owning-tenant N retention alongside P; the previous no-N expectation was corrected because presence/audit are exported tenant data. A legitimate explicit testserver Host/infra fixture correction preserves tenant middleware. Original author metadata preparation was interrupted after finite code authoring; a separate tiny Stage3 added exactly two raw-holder exclusive-upgrade negatives. All final files were independently reread and hashed. Root has started the immutable523-case runtime group; no passing runtime or complete production-readiness claim is made here. No child runtime, staging or commits.

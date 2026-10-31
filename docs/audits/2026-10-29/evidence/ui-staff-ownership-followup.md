# Staff queue, upload and handover-evidence follow-up

Reviewer: Codex `/root/audit_ui_finish`. This is a local corrective audit packet;
Stage 1 review and Stage 2 source writing completed. Separate Stage 3 test authoring
completed with CLI exit 0; root runtime/whole-release review remain pending. No staging,
commit, push, external upload or production credential action was performed here.

## Changes and purpose

One small shared upload protocol preserves the initiating session generation and
existing action/resource owner through config discovery, presign, direct storage
bytes, metadata finalization and each batch file. Previously, raw storage completion
could resume with a fresh authenticated request under a different account. Backend
RBAC independently still applied; no permission bypass is claimed. Already dispatched
writes/bytes may finish; obsolete later work and UI publication are fenced.

The protocol is used by public staff images, machine documents, warranty documents,
procurement receipts, maintenance attachments and issue/return evidence. Semantic
resource keys and existing action owners prevent old success/error/finally callbacks
from replacing another resource's preview/evidence, opening its private URL, clearing
its fields or showing a misleading toast. Evidence receives real request/loan IDs
from callers and clears an old parent ID before the new context's first paint.
Callback identity changes and pending disabled flips preserve legitimate current
state. Latest disabled/native-camera admission blocks obsolete newly initiated work.

Image-size configuration clears only its own rejected/invalid promise, so a transient
failure permits explicit retry. Maintenance pending now spans raw bytes, and retry
keys retain their originating machine/log/session/visit. Maintenance hook admission
happens synchronously before TanStack can pause either `mutate` or `mutateAsync`;
response DTOs remain plain and the one-argument hook contract exposes no unguarded
per-call callbacks.

Machine queue/manual submissions capture immutable click-time DTO bodies and use
independent current owners. Same-tick duplicate/action/field changes are rejected
before pending renders. Old completion cannot clear a new draft. Existing fleet,
pool, report, handover and payment invalidations remain. A numeric machine-type key
resets type-local mutations and consumable form state while outer per-type service
drafts remain intact.

Warranty metadata cannot upsert while its initial GET is unresolved or failed without
data. Explicit loaded null permits creation; initial failures offer Retry. Dirty
same-visit fields survive background metadata/document refetch. Current successful
save synchronizes the server's normalized returned metadata.

## Exact scope and pending verification

The 23 changed/new source files, byte hashes and line counts are recorded in
[ui-staff-ownership-source-freeze.json](ui-staff-ownership-source-freeze.json).
The maximum is 230 lines. The existing 326-line `machinesApi.ts` was read only.
Full final source contexts were reread; no test result is inferred from inspection.

Gate plans/results are adjacent `ui-staff-ownership-*` and
`ui-warranty-initial-*` text artifacts. The separate test-author contract is
[ui-staff-ownership-tests.txt](ui-staff-ownership-tests.txt). The separate author wrote 131 statically expanded cases across 13 new suites and
three test-only helpers (16 files, 1,713 lines; largest 164). Exact byte bindings and
root runtime-pending status are in [ui-staff-ownership-test-freeze.json](ui-staff-ownership-test-freeze.json),
with the full handoff in [ui-staff-ownership-tests-result.txt](ui-staff-ownership-tests-result.txt).
Actual collection/runtime results must be attached by root. This packet is not
a canonical source-registry approval or a production release decision.

The bounded frontend source review currently contains 145 complete contexts:
132 explicit static context decisions and 13 pending corrective/runtime contexts,
including the newly traced active hardware callers. It enumerates 1,689 lexical
owners, 1,794 candidate sites and 4,155 call edges;
parser enumeration supplies locations, never approval. Remaining repository files
are not implicitly covered by that count.

## Initial root runtime and bounded fixture correction

Root collected 247 cases across 38 relevant suites: 242 passed, five failed in
81.85 seconds ([initial log](ui-staff-ownership-initial-runtime.log)). Three new
DocumentsTab cases were stopped by jsdom's internal required-file constraint state:
`fireEvent.change` provided the selected FileList to React, but native click-submit
still considered the file absent. The corrected fixture asserts required and selected
file, then exercises the real form submit handler. Two new ServiceConsole cases
waited for the parent draft but clicked before the B query had rendered its action;
they now await that real action. Every payload, ownership, retry and pending negative
assertion is retained. No production source changed. Corrected root runtime and
TypeScript are pending, so this group remains explicitly unapproved for release.

The corrected root log records **247/247 cases across 38 suites PASS** in
75.65 seconds ([corrected log](ui-staff-ownership-corrected-runtime.log)). Exact
TypeScript/command-exit confirmation is still pending with root. The approved
follow-on active hardware source group is now being implemented; these focused
results describe the prior frozen source bytes, not subsequent unverified edits.

Root subsequently confirmed the corrected run and chained `npx tsc -b` completed
with **exit 0 (session 89449)**. The prior frozen group is runtime-verified.
The later hardware correction still requires its own source/test freeze and runtime;
changed overlapping files cannot inherit this result automatically.

# QR print-batch read projection closure

A print-batch item deliberately retains its original label and target snapshot
after a legitimate cross-makerspace QR rebind or asset move. The old detail
serializer followed that historical FK into the now-other-maker live QR and
exposed its current maker, target, status, payload and timestamps to staff scoped
only to the batch. The ZIP path also followed that current QR without a maker
check. Snapshot retention is not a grant to those current live fields.

The separately approved four-source correction returns nullable `qr_code` when
the current QR maker differs from the item's batch maker, even for a global
actor. Stored label/target/order/identity fields and canonical later moves are
unchanged. Explicit OpenAPI annotation declares the nullable nested QR.

ZIP output includes only fetched current same-maker entries. A partial batch
returns those labels with coherent numbering and unchanged SVG/sanitization; an
empty/all-moved batch returns existing typed validation 400. The native download
action catches that refusal and displays an error instead of producing a 500.
The UI preserves the original item snapshot with a neutral unavailable placeholder,
never mounts a QR-image request for null, shows printable versus collected counts,
uses Download available for partial batches and disables zero-printable downloads.

The initial plan review required the actual native ZIP caller and honest partial
UI wording; both revisions were incorporated before the final plan approval and
source writing. Stage2 exited 0. All four final source bodies were independently
read in full; exact hashes are in qr-batch-projection-source-freeze.json, max231
lines. Source is frozen while separate Stage3 writes scoped HTTP/native/schema
and UI tests. The old native successful-download fixture will receive one legal
same-maker item so its MIME/filename assertions stay a valid positive; new empty
refusal cases cover the intentional contract change.

No child runtime, application import, database, build, schema generation, staging,
commit or push was performed. Root owns actual scoped tests, generated OpenAPI/client
refresh, TypeScript and final review. Earlier complete frontend/backend results
do not verify this later source snapshot. No complete production approval is made.

## Final Stage3 freeze

Separate test writing exited 0. All seven new backend test/helper files and the
frontend test were read in full, along with the one existing native positive
fixture and its required imports. Static expansion gives 18 new backend cases
(detail6, ZIP6, native5, schema1) and five frontend cases. The four source hashes
remain unchanged. Exact tests are bound by qr-batch-projection-test-freeze.json;
the adjacent Stage3 result records root commands and honest limitations.

Backend fixtures perform actual canonical product rebind and asset move with an
authorized global transfer actor, then read as A-only, B-only, both-space and
global staff. Exact DTOs/SVG bytes, historical rows and domain/audit state are
asserted. Frontend tests use real BatchLabels, QrImage, token selection and
download mutation, with leaf HTTP and browser-download instrumentation. They
prove conditional rendering/dispatch, not backend authorization. Schema generation
is restricted to the actual detail route. No cases are skipped and no permission
checks or historical semantics are bypassed. Runtime/TSC/global schema refresh
and final complete-suite/review evidence remain root-owned and pending.

## Parent runtime result for the initial four-source snapshot

Root verified 30 backend cases in 35.65 seconds: 18 new projection cases, three
native/snapshot compatibility cases and nine OpenAPI cases. This proof is bound
to the historical 193-line admin source. Root also verified five frontend cases
in 3.70 seconds plus chained TypeScript/session3170 exit0. The sole initial UI
failure was a Node Response consuming a jsdom Blob without stream; only its fake
response body changed to string bytes with the same ZIP content type. All real
mutation/fetch/download/identity assertions remain. Current test freeze records
the changed fixture hash and preserves its predecessor.

A later independently confirmed native inline detail exposure is a separately
approved 208-line admin delta, not covered by the earlier native ZIP tests.
qr-batch-native-inline-source-freeze.json binds that delta, and
qr-batch-projection-current-source-freeze.json binds the four current sources.
The original source freeze remains historical. New native-detail tests/runtime
and complete current backend/source review remain pending; no release approval.

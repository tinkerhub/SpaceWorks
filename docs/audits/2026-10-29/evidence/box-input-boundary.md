# CreateBoxQr input boundary — Stage 3 evidence

Scope: the approved and implemented `CreateBoxQrSerializer` label/location maximum
of 200 characters. Stage 3 adds only
`backend/tests/test_box_qr_input_boundaries.py` and this evidence document.

The two parameterized rejection cases POST through the real API with an active
Space Manager created by the existing test helpers. Each sends 201 characters in
one field, checks HTTP 400 and the DRF error detail's `code == "max_length"`, and
compares every persisted Box, QrCode and AuditLog row before/after the request.
A pre-existing foreign box/QR makes that comparison cover existing state too.

The positive case sends distinct 200-character label and location strings, checks
both serializer and model field bounds, then verifies HTTP 201, exact persisted
and returned strings, one added Box/QR/audit row, QR payload/target/tenant/creator/
active status, and the audit action/target/tenant/actor. The local fixture selects
self-host infrastructure settings and sends `HTTP_HOST="localhost"`; middleware
remains enabled. Production handlers and ModelSerializers are unchanged here.

Existing permission/foreign-scope cases remain in `backend/tests/test_qr_api.py`
and are intended to run alongside these tests; no denial matrix is duplicated.

## Validation status

Static syntax and case counting only. No tests, collection, Django imports,
database access, network/provider calls, staging or commits were performed.
Runtime test execution and final OpenAPI/schema/type regeneration remain with
the root orchestration task; this document does not claim a passing test run.

## Selectors (from backend/)

- `tests/test_box_qr_input_boundaries.py::test_box_qr_rejects_201_characters_without_writes[label]`
- `tests/test_box_qr_input_boundaries.py::test_box_qr_rejects_201_characters_without_writes[location]`
- `tests/test_box_qr_input_boundaries.py::test_box_qr_accepts_exactly_200_characters_with_scoped_qr_and_audit`
- Compatibility: `tests/test_qr_api.py`

## Approved plan (verbatim)

```text
Read-only Stage1 tiny API boundary correction. Do not edit/run tests/importDjango. Actual source backend/apps/boxes/serializers.py CreateBoxQrSerializer hasunbounded label/location; Box modelvarchar200; CreateBoxQrView passesserializerdata into Box.objects.create catchingIntegrityErroronly, so201chars raisesDataError500. Plan2sourcefieldchanges max_length=200 (or derive actual modelmaxvalue ifexistingpatternpreventsdrift; preferplain200sameModelSerializerconvention). No truncation/no broadenedexceptioncatch; normal DRF400field max_length beforewrite. Description TextField unchanged. Existing membership/action/origin parent scoping/dupelabel logic unchanged. Sourcefilecurrently<300. RootfinalregeneratesOpenAPI/types withotherpendingchanges. SeparateStage3 small new backend/tests/test_box_qr_input_boundaries.py actualAPItests: label201andlocation201 each400max_lengthandnoBox/QR/auditmutations; exact200both201successwithcorrectscopedfields+oneQR/audit; forbiddenforeignactors stillpermissiondenied usingexistingcompatselectors don'tduplicatewholematrix. UseactualRequestHTTP_HOSTwhenmanaged orselfhosttestsettingslegitimateinfra, no disabledmiddleware. Rootruns tests. Inspectsource serializer/model actual admin_API CreateBoxQrView and tests/test_qr_api.py. ReturnAPPROVEDorBLOCKED minimalreason; unrelatedlargeauditnotinscope.
```

## Plan review (verbatim)

```text
APPROVED — both model fields cap at 200; adding `max_length=200` to the two serializer fields provides DRF field-level 400 validation before writes. Description and existing authorization/scoping/duplicate handling remain unchanged.

Stage 3 coverage is appropriate. Use valid-length payloads for permission checks, preserving existing denial statuses, including scoped 404s. No edits, tests, or Django imports performed.
```

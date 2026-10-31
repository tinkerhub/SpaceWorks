# Native QR print-batch inline projection

The original API/ZIP closure did not cover Django's readonly inline FK display.
A native BatchA change page rendered the live QrCode string/current target/status
and change link after a legitimate move to B, including hidden B. The old stored
item snapshot and FK must survive that move; they do not authorize live disclosure.

A separate read-only Stage1 approved the tiny existing-inline correction. Stage2
changed only operations/admin.py and exited0. The custom readonly display compares
maker IDs before stringification/link construction, returns QR unavailable for
foreign rows and retains escaped same-maker text/link using Django's safe HTML
formatter. Explicit fields=readonly_fields excludes the raw model FK from editing.
No permissions, snapshots, move behavior or history changed. Complete208-line
source was read; exact current/prior hashes are in the adjacent source freeze.
The original193-line freeze remains historical, and the current cumulative
four-source freeze records the later admin hash separately.

Separate Stage3 exited0, authoring one126-line file with three static cases.
Hidden-B and visible-B cases perform actual canonical product rebind before an
authenticated native BatchA GET; they inspect actual inline cells, unchanged
original snapshots/FK, no foreign link/current metadata and no raw editable FK.
Same-maker positive verifies escaped history and correct live link. Exact domain,
QR, item, audit and scan state is compared around GET. No getter/permission/queryset
was mocked and no source gate bypassed. Test/source hashes remain unchanged.

Parent command in its backend test environment:
`python -m pytest -q tests/qr_batch_projection_safety/test_native_detail.py`.
Root controls PostgreSQL/runtime and final review; no child application/test
execution occurred. The prior30 backend/5frontend/TSC results apply to their named
snapshots and do not alone verify this final native-inline delta. No release
approval, staging, commit, push or production operation is claimed.

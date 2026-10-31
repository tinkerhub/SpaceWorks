# New authorization-helper registration reconciliation

Reviewer: Codex `/root/audit_ui_finish`. Read-only complete-source inspection of
the four helpers, current `tenant_migration/authority_guards.py` and relevant
SOURCE-MAP entries. No application import, guard, census, database, runtime,
registry/source writer or approval bypass was executed.

## Initial four-helper omission (subsequently corrected)

At initial inspection all four new helpers were absent from `AUTHORIZATION_SOURCES`;
none was named in `docs/SOURCE-MAP.md`. The field guard explicitly says new authorization modules
are outside its automatic discovery. These files own authorization/admission
behavior rather than a declaration-only re-export, so leaving them unregistered
permits future field-level drift there to escape that bounded guard.

| Source | Current lines | Whole-file SHA-256 | Reviewed responsibility |
| --- | ---: | --- | --- |
| `backend/apps/boxes/admin_lifecycle.py` | 59 | `febfc57a34b0cb3cb895d26d1a009039ab74014411dbf0aaa6c5a63993eeada6` | Native Box source admission spans Django changeform/Collector commit; effective selected tenant admission precedes Maker locks. |
| `backend/apps/warranty/admin_forms.py` | 101 | `60c3a16dd9a5d925fe105a54c86d9cd3069610eadfeed171fc63b09622a35be9` | Native Warranty fresh actor/hidden-space checks, module/source gates and locked tenant/host consistency. |
| `backend/apps/boxes/qr_admission.py` | 137 | `d1bf4be96f9d31c21ba762bc597f92f573a9642baac1e0930858959719d8fb71` | Sorted source-write admission, current actor/hidden-tenant checks, QR identity checks and guarded tool creation. |
| `backend/apps/boxes/admin_qr_lifecycle.py` | 231 | `412bea74180f9bcddce1b5376a8ea441a2a58e0434c73eae0ef6d38ffa22ea20` | Effective native QR selection, actor/source admission across actions/history/commit and immutable fresh-row identity. |

## Bounded recommendation to the primary integrator

1. Add these exact reviewed paths to the existing `AUTHORIZATION_SOURCES` tuple;
   retain its current conservative field scanner and existing strict declarations.
2. Run the existing authority registry tests/guard against final source. If new
   exported model/field pairs appear, individually identify their actual owner and
   target projection/disposition. Do not automatically exempt discovered fields,
   copy declarations without review, or expand model coverage merely for a green run.
3. Update SOURCE-MAP: `boxes/admin_lifecycle.py` owns native Box write/Collector
   admission, `qr_admission.py` owns shared sorted source/transaction and fresh
   policy checks, `admin_qr_lifecycle.py` owns effective native QR actions/selection,
   and `warranty/admin_forms.py` owns native add/locked-host admission.
4. Preserve final exact file/owner/site decisions in the independent source census.
   The current scope classifier statically includes all four ordinary backend `.py`
   paths as production Python source; this child did not run a final census and
   cannot attest its current path/hash records. Reconcile newly discovered owners
   through actual review rather than auto-approving them from discovery.

Adding paths only extends a conservative exported-field drift check. Its model
intersection is limited to the explicitly listed Makerspace/membership/role and
machine models, and it deliberately over-approximates lexical names. It does not
prove dynamic RBAC, native action dispatch, source/Maker/QR lock order, transaction
lifetime or runtime failure safety. Those continue to require their actual source
review and the parent-owned PostgreSQL/native tests. The `_assert_source_gate`
override in the native QR helper was read in context with its effective-selection
wrappers; no bypass is proposed or inferred from that method in isolation.

Source/registry edits and runtime verification remain with root. These are bounded
recommendations and hash observations, not production ledger approvals.

## Primary integration update

After this read-only recommendation, root registered exactly the four paths in
`AUTHORIZATION_SOURCES`, retaining existing field declarations and exemptions
unchanged, and started the existing guard/catalog checks. This child updated only
SOURCE-MAP prose to name `BoxLifecycleMixin`, `WarrantyAdminForm`,
`QrLifecycleMixin`, `QrRebindAdminForm` and their shared admission helpers.
The first integration was then extended as recorded below; final guard/catalog proof is now available.
The earlier omission is historical; final complete-corpus hash/owner review and
changed QR-transfer source verification remain independent open gates.

## Final six-helper integration and guard result

Root additionally registered `boxes/admin_forms.py` and
`procurement/admin_forms.py`. Both complete bodies were read before this update.
`BoxAdminForm` delegates fresh native policy/Maker admission, reloads an existing
row to prevent resurrection and validates a current same-space parent.
`ToBuyItemAdminForm` applies canonical machine-type access/provenance validation
while retaining an existing item's tenant and kind. SOURCE-MAP names both classes.

| Additional source | Lines | Whole-file SHA-256 |
| --- | ---: | --- |
| `backend/apps/boxes/admin_forms.py` | 55 | `504f94285124a5e4c80a72710178b1d2c4a1a2a237e93e9687067c85c155c5e6` |
| `backend/apps/procurement/admin_forms.py` | 29 | `0569b3ac58e57b6833751789dfab7105b2725f2d0909506aec0aa2f79bb12a01` |

The actual tuple now includes all six named paths. The conservative lexical scan
identified only `makerspaces.Makerspace.created_by` and
`machines.Machine.created_by` as additional declared pairs, from the native QR
creator metadata. Root supplied explicit provenance/no-authority reasons; target
projection and exemptions were unchanged. Two parameterized negative removal
checks preserve strict fail-closed declaration behavior. Root verified all
**20 authority-guard/catalog checks passed in 5.23 seconds**.

The reviewed authority-guard hash was refreshed in the 60-source recovery freeze,
retaining the previous snapshot. The eight-lane recovery matrix now records all
252 identified cases passing across explicit immutable snapshots. This does not
approve the final complete source census, new asset/batch QR transfer corrections,
whole backend, privileged host drill, independent review or production release.

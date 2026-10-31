# Completing the explicit source review ledger

This is a review plan, not an approval ledger. Discovery, route/flow mappings and
passing tests do not create review decisions.

## Optional certification; activation deferred

This whole-checkout source certification was introduced during this audit; it was
not a pre-existing required product release guard. The new unconditional
`verify-source` release job and its publishing dependency are removed, restoring
the committed release graph. Existing CI/pip-audit requirements and exact-SHA
release behavior remain intact.

The independent, optional strict release-audit command remains, from the repository
root with Python 3.12, Node 20 and the locked frontend TypeScript parser installed:

```bash
python scripts/check_source_primitives.py
```

The current registry is `UNREVIEWED`: this command returns exit code 1 with
`source review refused: scope/corpus is UNREVIEWED` before discovery. Certification
is incomplete; retaining this command supplies neither a full source audit nor a
certification claim. See [the certification guide](../../../source-audit/README.md).

Activation requires complete source/context reviews, explicit report-backed
decisions covering scope and callers, a valid normalized ledger for the final
snapshot, and a successful independent CLI check of that exact release checkout.
Source changes require the reassessment below; updating hashes alone supplies no
approval. The final audit report and mandatory final Codex uncommitted review
remain required. Real feature/security findings remain production blockers
independently of this optional certification.

The metadata-only checkout census at this inspection contained 3,781 paths and
2,553 source/input files: 1,933 Python, 497 TypeScript/JavaScript, 23 shell, 20
container/YAML and 80 opaque inputs. These are provisional counts while other
agents are editing. There are 393 migration files. Thirty-three audit evidence
files and one generated TypeScript cache are currently included as opaque source;
the separately reviewed scope correction removes that unnecessary source churn
without exempting executable files in an audit directory.

## Sequence

1. Finish source corrections and tests. Freeze application/configuration/parser
   files, then discover once with the release runtime: Python 3.12, Node 20 and the
   locked TypeScript parser. Keep intermediate packets outside the checkout.
2. Partition by domain and exact `(path, lexical owner)` using
   `owner_context_sites`. Each packet should contain roughly 15–25 source files,
   the full relevant file/owner bodies, site symbols and unresolved facts, imports,
   constants and caller edges. Include files with no primitive observations in the
   domain's scope review; no observations is not itself a safety disposition.
3. Have an agent actually read each packet and its relevant callers. It records
   explicit purpose, authorization/storage/runtime boundary, disposition and
   reviewer for the exact named owners and site symbols. Shared-purpose sites may
   share an owner explanation only after the complete owner/context was read.
   Neither a folder name nor a previous flow-map association supplies approval.
4. Save actual review prose in Markdown reports, with exact source references and
   clearly retained uncertainties. An unresolved issue remains unreviewed until
   fixed. The assembling agent may mechanically serialize these explicit decisions
   using `reviewed_direct_entry`; it must not fill missing decisions from the
   discovery census, infer them from test names, or turn a whole domain green by
   default.
5. Integrate scope/classification, cross-domain caller and report bindings. Use the
   existing normalized ledger assembly and reconcile against the same frozen
   census. Run the actual corpus release check and the mandatory final code review.

## Suggested domain lanes

| Lane | Source responsibility |
| --- | --- |
| Identity and tenancy | Accounts, encryption, API clients, organizations, check-in, presence, request policy and origin/RBAC boundaries. |
| Inventory and handover | Inventory, hardware requests, operations, boxes, evidence, procurement and warranty; public/staff lending clients. |
| Machines and public services | Machines, printing compatibility, maintenance, bookings and service/queue/consumable clients. |
| Events and communications | Events, forms, notifications, integrations and delivery workers; related member/staff clients. |
| Payments | Pricing/currency, provider admission, reconciliation and payment UI; genuine provider limitations retained. |
| Recovery | Backup, tenant migration, exports, module/tenant purge and recovery admin. Split this largest lane into separate 15–25-file packets. |
| Shared UI and operator surface | App routing, session/query publication, chrome/primitives/accessibility, admin API adapters, configuration, installation/deployment scripts and runtime inputs. |

A lane is an assignment, not a claim that every file in it has already been read.
The current source and test handoffs can seed the reviewer's attention, but they do
not substitute for the exact owner/context decisions required by this gate.

## Changes during review

The current fingerprints deliberately bind the whole source corpus, call index and
symbol/import/constant index. Any source correction therefore invalidates all
previous site fingerprints. Freeze again and review the changed dependency context
before reconstructing decisions; do not simply replace old hashes or automatically
copy approvals onto new fingerprints. Documentary evidence bytes are separately
bound when cited as an actual review report.

Even a passing ledger proves an explicit review of one repository snapshot. It
does not prove production secrets, provider delivery, payments, DNS/TLS or a live
restore drill. Those deployment checks remain separate in the audit report.

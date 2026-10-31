# Walk-in creation and borrower selection follow-up

A successful person creation previously awaited `invalidateQueries` and then selected
the returned ID. TanStack can resolve that call after a failed, paused or absent query,
so the visible borrower list could lack the selected person. Rejecting that later
refresh could also misreport a committed creation as failed and invite another POST.

The independently approved small correction keeps the actual server creation receipt
under its original actor/form/borrower/handout owner. It clears successfully submitted
fields and blocks creation replay while that receipt is current. Failed POSTs retain
the draft for genuine retry. A failed, paused or absent selection read displays the
truthful created-person state and an explicit refresh button; it does not create again
or manufacture membership, waiver or complete roster fields.

One focused helper observes the exact canonical borrower query. Selection needs a
fresh non-manual successful fetch, current idle/unpaused state and an actual complete
canonical row containing the returned user ID. Missing, inactive, disabled, static,
removed, failed, paused and absent/page-cap results cannot select. Late pause during
production retry releases the local UI; retired or superseded attempts cannot select
later, and eventual rejection is consumed. Local retirement does not cancel shared
roster work. A final proof check rejects cache replacement/manual state changes before
selection. Local observation is bounded at 30 seconds, after which explicit retry
remains available.

Both final source bodies and the one-line submitted-field repair were read. The exact
two-file freeze is [ui-walkin-roster-source-freeze.json](ui-walkin-roster-source-freeze.json):
WalkInMemberForm is 166 lines and refreshWalkInRoster is 97. Plans, independent review,
source handoffs and the separate test-author contract are adjacent ui-walkin-roster
artifacts. Source writing exited 0; final Stage 3 real-query test writing completed with exit 0.
No runtime/TSC/build, staging, commit, push or production operation ran in this lane.

[ui-staff-hardware-combined-source-freeze.json](ui-staff-hardware-combined-source-freeze.json)
binds the current 34 staff/hardware source files for root's combined verification.
The prior 247-case/TSC proof applies to its earlier exact bytes. Root subsequently
verified the final 34 source hashes in the combined runtime below; release review
remains separate.

Final Stage 3 CLI exited 0 after authoring 27 new real-query cases across three
suites plus one test-only helper, and narrowly adapting two standalone fixtures in
the existing eight-case hardware walk-in suite. Prior body/identity/pending
assertions were retained. [ui-walkin-roster-test-freeze.json](ui-walkin-roster-test-freeze.json)
and [ui-walkin-roster-stage3-handoff.txt](ui-walkin-roster-stage3-handoff.txt) bind
exact files, hashes and commands. Current 34 source hashes were rechecked unchanged.
Root’s actual combined selection passed 341/341 cases across 50 files in 113.47
seconds (247 prior staff +67 hardware +27 roster), followed by TypeScript and
production build, both exit 0. The initial three fixture assertion failures were
corrected without changing source or weakening owner/body/pending assertions; the
failed-create email assertion now reflects native HTML whitespace normalization.
[Corrected runtime](ui-staff-hardware-corrected-runtime.log) and updated exact test
hashes are preserved. Whole-frontend and final release verification remain separate.
Current source and tests are frozen.

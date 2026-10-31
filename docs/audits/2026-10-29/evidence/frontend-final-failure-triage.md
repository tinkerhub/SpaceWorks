# Final frontend run: bounded read-only triage

The 1,990-case run recorded 1,986 passed and four failed across 229 files in
375.95 seconds. The chain did not reach TypeScript/build. This is a failing full
run, not production approval. Root then reran the three files unchanged with
`--maxWorkers=2`: all 17 cases passed in 7.88 seconds. No source, test timeout or
assertion was changed during this triage.

## Worker evidence and limits

The preceding 1,985-case passing run explicitly used `--maxWorkers=1`; the later
failing command was uncapped `vitest run`. Neither checked-in Vitest configuration
sets a worker cap. Relevant file durations changed:

| File | Earlier passing run | Later failing run |
| --- | ---: | ---: |
| MachinesPanel.ownership | 2.041s | 8.533s, including a 5s first-test timeout |
| StocktakeCountSection.auditB | 1.646s | 7.636s |
| WalkInMemberForm.rosterRead | 0.885s | 2.163s |

The second machine case failed at its initial Complete lookup after the first
case timed out, consistent with a timeout cascade but not proof of one. The
stocktake case failed waiting for the scanner dialog to close; its trace supplies
no captured typed-submit/HTTP evidence sufficient to attribute a product bug.
Together with the unchanged focused pass, these observations support repeating
the full run with bounded workers while retaining existing timeouts and checks.
They do not establish that every failure is environmental.

## Exact replacement-cache fixture race

`mountStaff` sets test QueryClient defaults to `queries.gcTime = 0`. In the roster
replacement case, `removeQueries` removes the originally observed Query. The
following `fetchQuery` builds a distinct unobserved Query using that zero-GC
default; the old CanonicalRoster observer remains attached to its original Query.
The installed QueryCore implementation schedules GC after fetch settlement, and
`optionalRemove` removes idle unobserved queries. `await act` can yield to that
zero-delay timer before the immediate cached-data assertion, producing undefined
without any stale borrower callback.

The production owner guard captures the original Query, retires on removal and
requires exact cache identity before selection. Replacement cache data never
makes that original owner current. The fixture's intended premise is instead
"a distinct new Query really retains a successful canonical response."

Recommended narrow fixture correction: add `gcTime: Infinity` only to that
replacement `fetchQuery`. Retain the real HTTP read, new-query-not-original,
exact canonical cached data, no selection and one POST assertions. Per-test client
cleanup already clears the cache. Do not change production cache policy, observer
logic, timeouts or weaken the ownership assertions. Root owns applying and
verifying that correction and rerunning the full suite.

A separate source observation is that QrScanner positions TypedCodeForm at a
different child index in camera and async-error branches, so rejection may remount
its local draft. This is not established as the cause of the stocktake failure;
no scanner product change or additional runtime was performed by this lane.

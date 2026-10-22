# Check-in mode: borrow by checking in, no member accounts

In **check-in mode** (`checked_in`) a makerspace has no member accounts. A visitor borrows by typing
their name; SpaceWorks matches it against an upstream check-in roster (for example the TinkerHub
check-in app) and accepts the request only from someone currently checked in at this space, for the
required purpose, with a project chosen. Staff still review every request and record the handover
evidence as usual.

> **Trust boundary.** The roster is public and carries no secret, so a match proves that *someone*
> with that name is checked in, not that the visitor is that person. It is a presence filter, not
> authentication. Rules: [Check-in gated requests](INVARIANTS.md#check-in-gated-requests).

## 1. Modules

| Module | Setting | Why |
|---|---|---|
| `membership` | **off** | While it is installed every request needs an active member, and the mode cannot be set |
| `member_accounts` | off (recommended) | Nobody signs up; check-in mode ignores accounts anyway |
| `request_workflow`, `guest_handover`, `telegram`, `reports` | on | The request queue, front-desk handouts, staff alerts, the ledger |

The installer's check-in option starts from the `checkin` module profile and forces on `reports`,
`telegram`, `guest_handover`, `machines`, `machine_service`, `printing`, `maintenance` and
`procurement`, with `membership` off. Untick what you do not use.

## 2. Server settings

| Variable | Default | Meaning |
|---|---|---|
| `CHECKIN_API_URL` | empty (mode unavailable) | Full URL of the roster, fetched with a plain `GET`, no auth. Redirects are not followed |
| `CHECKIN_REQUIRED_PURPOSE` | `Working on a project` | Only rows with exactly this purpose (case-insensitive) may borrow. Must not be blank |
| `CHECKIN_PROVIDER_NAME` | empty | Name of your check-in system in borrower copy (e.g. `Maker Gate`). Empty uses "TinkerHub" for a TinkerHub roster URL, otherwise neutral wording |
| `CHECKIN_TIMEOUT` | `5.0` | Seconds before the roster counts as unavailable. Must be positive |
| `CHECKIN_CACHE_SECONDS` | `30` | Cache for the name search only; every submit refetches the roster |
| `CHECKIN_MAX_RESPONSE_BYTES` / `CHECKIN_MAX_ROWS` | `1048576` / `2000` | Larger rosters are refused as unavailable |

With `CHECKIN_API_URL` set, a blank purpose or a non-positive timeout stops the backend from starting.
The **upstream space ID** is not an environment variable; it is stored on the makerspace (step 3).

## 3. Turn it on

**Fresh install.** At **Who can submit borrow requests?** choose **4** (check-in API), then give the
roster URL, your space's number in the check-in system and the purpose. Setup writes the URL and
purpose to `.env` and applies the mode after creating the makerspace. If any answer is invalid, or
`membership` ends up ticked, it warns and keeps "an account is required"; read the warnings.

**Existing install.**

```bash
cd /opt/spaceworks
# 1. Add to .env (replace existing lines):
#    CHECKIN_API_URL=https://checkin.example.org/api/roster
#    CHECKIN_REQUIRED_PURPOSE=Working on a project
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled up -d

# 2. Make sure membership is off for the makerspace:
bash scripts/update.sh --modules-only --makerspace YOUR_SLUG

# 3. Select the mode and the upstream space ID together:
scripts/spaceworks-compose.sh bundled run --rm --no-deps -T backend --role management \
  python manage.py set_request_access --makerspace YOUR_SLUG --mode checked_in --checkin-space-id N
```

It prints `Borrow requests for YOUR_SLUG: anyone checked in upstream and working on a project.` It
refuses (and changes nothing) while `membership` is installed, while `CHECKIN_API_URL` is blank, or
without a positive space ID. Check the live policy at any time with
`... python manage.py list_modules --makerspace YOUR_SLUG --json` (the `request_access` field). There is
no console setting for this mode; the command and the installer are the only ways to set it.

To leave check-in mode, run the same command with `--mode accounts` (signed-in accounts) or
`--mode anyone` (no account, name and contact details). Installing `membership` also overrides it.

## 4. What the roster must look like

A JSON array of objects. `null` is treated as an empty roster (nobody checked in), not an error.

```json
[
  {
    "mid": 4021,
    "name": "Asha Menon",
    "spaceId": 1,
    "purpose": "Working on a project",
    "projectName": "Line-following robot",
    "checkInTime": "2026-10-22T09:15:00+05:30",
    "checkOutTime": "2026-10-22T18:00:00+05:30"
  }
]
```

| Field | Rule |
|---|---|
| `mid` | Positive integer, unique per person. Rows sharing a `mid` are all ignored |
| `name` | Non-blank. Matched exactly after case-folding and collapsing spaces; punctuation counts |
| `spaceId` | Must equal the makerspace's check-in space ID. A row without it never matches |
| `purpose` | Must equal `CHECKIN_REQUIRED_PURPOSE` (case-insensitive) |
| `projectName` | Must be non-blank |
| `checkOutTime` | Optional; if present and in the past, the check-in has ended. Times must include a timezone |

Invalid rows are skipped. A non-2xx answer, a redirect, a timeout, invalid JSON, anything other than
an array or `null`, or a non-empty array with no valid row makes the service **unavailable**: borrowers
see an error and nobody is denied on a technicality. That is deliberate (fail closed).

Test the roster from the server:

```bash
curl -fsS "$CHECKIN_API_URL" | head -c 600
```

## 5. What borrowers see

**Everyone checks in, including signed-in staff and members** — an account is never a bypass in this
mode. The same applies to public self-checkout and public machine-job requests.

1. The borrow panel says **Borrow with check-in**. The visitor types their name as it appears in the
   check-in app and presses **Find me**.
2. Matches are listed with **That's me**. A match that cannot borrow says why: not checked in as the
   required purpose, no project chosen, or the session ended. A single eligible match is confirmed
   automatically.
3. They submit. The server re-reads the roster at that moment, so someone who checked out in between
   is refused with *You are not currently checked in.*
4. They get a reference token to quote to staff; there is no account to come back to.

Limits: 20 requests per person per hour, plus per-IP limits, and at most 50 outstanding unreviewed
account-less requests per makerspace (`ANONYMOUS_REQUEST_OUTSTANDING_LIMIT`).

Borrower-facing text names your check-in system with `CHECKIN_PROVIDER_NAME` ("Confirm your name as it
appears in *Maker Gate*"). Unset, it falls back to "TinkerHub" only when `CHECKIN_API_URL` is TinkerHub's,
and otherwise reads "as it appears on the check-in list". The wrong-purpose refusal quotes
`CHECKIN_REQUIRED_PURPOSE`.

## 6. What staff see

Requests arrive in **Requests** like any other, under the person's roster name (not what they typed),
with no email or phone. The request drawer has a **Checked in** row: purpose, project and when the
check-in was verified. Each roster person becomes a stable walk-in record, so their history, overdue
items and restrictions follow them across visits; restricting that record blocks their future
requests. Accept, issue (box QR plus photo) and return (photo plus remark) work exactly as for any
request, and Telegram alerts go out if configured.

If borrowers report errors, check in this order: the roster URL answers from the server (above), the
row's `spaceId` matches the ID you set, and the purpose text matches exactly.

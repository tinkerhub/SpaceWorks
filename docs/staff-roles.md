# Staff roles, accounts and passwords

How staff accounts work in the console, for the person setting a makerspace up. Authority comes from
**actions**, not role names: a role is a list of actions, and every permission check asks whether the
person holds the action. Renaming a role changes nothing downstream.

## Where staff are managed

| Tab | Shown when | Holds |
|---|---|---|
| **Users** | You hold `manage_makerspace` (Space Manager, superadmin). Never hidden by a module | Staff accounts (**People**), **Roles**, password resets. **Invitations** appears only when `membership` is off and `member_accounts` is on |
| **Members** | The `membership` module is on **and** you hold `manage_makerspace` | Community members: join requests, presence, waivers. Not staff |

**Add staff** (Users → People) asks for a username, password and role; email and name are optional.
The role list only offers roles that grant at least one action (the action-less **Member** role is a
community membership, not a staff role). A Space Manager sees only roles inside their own authority,
so never **Space Manager** itself; a superadmin sees every staff role.

Row actions: **Change role**, **Reset password**, **Revoke**, and (superadmin only) **Restrict** /
**Restore**.

## The default roles

Every makerspace starts with four protected roles. They can be renamed and narrowed but not deleted.

| Role | Actions | Console sections |
|---|---|---|
| **Space Manager** | Everything grantable: requests, handouts, returns, evidence, inventory, QR, machines, printing, events, bookings, audit, `manage_makerspace` | Everything for the makerspace, including Users and Settings. Not Platform settings, Modules or Tenant migration (superadmin only) |
| **Inventory Manager** | Full hardware lifecycle (`accept_request`, `reject_request`, `assign_box`, `issue_request`, `issue_direct_loan`, `return_request`, `upload_evidence`), `edit_inventory`, `view_inventory`, `manage_qr`, `view_audit` | Dashboard, Notifications, Requests, Direct handout, Ledger, Transfers, Stocktake, To Buy, Inventory, Categories, To-be-fixed, Containers, Bulk import, QR tools, Scanner, Reports, Accountability, Warranties, Audit log, Email templates. **No** Machines, Users, Settings, Members |
| **Machine Manager** | `manage_machines`, which implies `manage_printing` and `collect_service_request` | Dashboard, Job handover, To Buy, Machines, Warranties, Email templates |
| **Member** | None | None. A role with no actions is a community membership |

On top of the role, **a section whose module is off is not shown at all** (for example no Machines
without `machines`, no Stocktake without `stocktake`, no Members without `membership`). Turning the
module back on brings the section and its data back.

## Front-desk (handover) roles

There is no built-in Guest Admin. Create a custom role under **Users → Roles** and give it only the
handout actions you want:

| Action | Lets them |
|---|---|
| `view_inventory` | See the inventory |
| `assign_box`, `issue_request` | Hand over accepted requests (box QR scan plus issue photo) |
| `issue_direct_loan` | Make a direct handout without a request |
| `return_request`, `upload_evidence` | Take returns with a photo and remark |
| `collect_service_request` | Hand finished machine jobs to their owners |

A role holding only these actions gets a narrow console at `/guest-admin` with just **Requests**,
**Direct handout** and **Job handover**. Add any other action (for example `accept_request`) and the
person gets the full console instead.

## Limits that protect the defaults

- You can only grant actions you hold yourself.
- Only a superadmin can grant or assign a role carrying `manage_makerspace`, or change someone who
  already holds it. The Space Manager role must always keep `manage_makerspace`.
- `transfer_stock` and `manage_staff` are superadmin-only and cannot be given to any role.

## Stocktake: two people

Counting and completing a stocktake needs `edit_inventory`. **Approving or applying** it needs
`manage_makerspace` **and a different person from the one who completed the count**, so a Space
Manager cannot approve their own count. A superadmin may approve any count, including their own
(except in a makerspace hidden from superadmins, where the two-person rule applies to them too). The
refusal reads:

> Approving or applying this stocktake needs manage_makerspace, and a different person from the one
> who completed it.

A completed count notifies with **Stocktake awaiting approval**. Plan for a second Space Manager (or
the superadmin) to approve.

## Passwords

| Situation | What to do |
|---|---|
| Change your own password | Click your name in the sidebar → **Your account** → **Change password**. It signs you out everywhere else |
| Reset a staff member's password | **Users → People → Reset password**. Leave the field blank to generate one; it is shown once. They must change it at next sign-in |
| Forgot password | **Forgot password?** on the sign-in page emails a 6-digit code (valid 10 minutes, 5 attempts). Only shown when email is set up, and the Celery worker and beat must be running |
| Superadmin forgot their password | Use **Forgot password?** if email works; otherwise run Django's `changepassword` on the server (below) |

Who may reset whom: a superadmin, or someone holding `manage_makerspace` over **every** makerspace the
person belongs to. Nobody can reset a superadmin's password from the console, and a Space Manager
cannot reset another Space Manager's.

The first superadmin is created by setup. `setup_instance` has **no default password**: it needs
`--password` or `SETUP_SUPERADMIN_PASSWORD` and refuses otherwise. Rerunning it for an existing user
does **not** change that user's password.

```bash
cd /opt/spaceworks
scripts/spaceworks-compose.sh bundled run --rm --no-deps backend --role management \
  python manage.py changepassword admin
```

Add `-T` after `run` only if you are not at an interactive terminal (it prompts for the password).

# Setting up Space Works — Open Source Makerspace Manager (plain-language guide)

This guide is for makerspace organisers who are **not** software developers. It walks you through
running Space Works on a computer at your space, step by step. You don't need to understand
the code — just follow along.

You'll need about **30 minutes** and one **always-on computer** (any spare PC, a Mini-PC, or an
Intel NUC) that stays on and connected to your network.

---

## Step 1 — Choose the host path

**Linux:** the curl installer below checks everything first, then offers to install Docker Engine,
Docker Compose V2, curl and tar through apt, dnf/yum, pacman or zypper. It supports x86_64 and aarch64.
It prints the dependency plan before making changes.

**Windows:** install and start [Docker Desktop](https://www.docker.com/products/docker-desktop/) with
Linux containers and its WSL2 integration enabled, then open a **WSL2** terminal (for example Ubuntu
from the Microsoft Store) and run every command below there. Native Git Bash and PowerShell are not
supported.

**macOS:** install and start Docker Desktop before running the installer.

Docker Desktop installation on Windows/macOS:

1. Go to **https://www.docker.com/products/docker-desktop/**.
2. Download the version for your computer and run the installer. On Windows, keep the WSL2 engine
   and the WSL integration for your Linux distribution enabled.
3. Click through the installer (the defaults are fine), then **start Docker Desktop** and wait
   until it says it's running (a whale icon appears in your taskbar/menu bar).

> If Docker asks you to enable virtualization/WSL on Windows, accept — it sets it up for you.

## Step 2 — Run the pinned installer

On Linux, paste:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | bash
```

It installs into `/opt/spaceworks` by default. To choose another directory, export it for the `bash`
side of the pipe:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | SPACEWORKS_DIR="$HOME/SpaceWorks" bash
```

On Windows, run either form from your WSL2 terminal. The installer downloads the newest **tagged GitHub release**
archive—never a moving branch and never a Git clone—and runs that release's `setup.sh`. It checks the
architecture, dependencies, Docker, ports, disk space and install directory before installing a package
or creating the install root.

## Step 3 — Answer the setup questions

The curl installer hands off automatically to `setup.sh`, which generates the passwords and security
keys. On Windows this all happens inside your WSL2 terminal.

The script will ask you a few simple questions (press Enter to accept the suggestion in brackets):

| Question | What to type |
|---|---|
| Web address people will type | `localhost` to start (you can change it later) |
| Name of your makerspace | e.g. `Riverside Makerspace` |
| Who can submit borrow requests? | `2` (anyone with an account) is the safe default, but people sign up with an email code, so it needs working email: set the `EMAIL_*` SMTP values in `.env` (see [notifications-setup.md](notifications-setup.md)) or nobody can finish signing up. Profiles without `member_accounts` (minimal, workshop, check-in) have no public sign-up at all, so with `2` only staff can borrow from the public page and visitors are told to ask at the desk; pick `3` (anyone) or `4` (check-in) there instead. `4` lets people borrow by checking in on an upstream check-in app, with no accounts — see [checkin-mode.md](checkin-mode.md) |
| Admin login username | `admin` is fine |
| Admin email | your email |
| Admin password | type one, or leave blank and it makes a strong one for you |
| Modules | leave the current ticks, use `a` for all, `n` for core only, or toggle numbers |
| Automatic updates | press Enter for self-hosted Actions runner setup instructions after startup; requires Linux/systemd and two GitHub settings |

Then it pulls the pinned release images and starts everything. **The first time takes a few minutes** —
that's normal. Developers with a full source checkout can explicitly use `bash setup.sh --build`; normal
installs never build Django or Vite locally.

## Step 4 — Open it

When the script finishes it prints two web addresses. Open them in a browser:

- **Public catalog** — what your community sees (browse + request).
- **Staff console** (`…/admin`) — the React console where Space Managers, Inventory Managers,
  custom handover staff, and the Super Admin do day-to-day work.

The Django control plane is at `/control/` on the backend only. It is an operator-only tool and is
not exposed on the public website/port.

**Write down the admin username and password it shows.** If you let it generate a password, that
line is the only time it's displayed.

## Step 5 — Make it useful

Log into the **staff console** address (`/admin`) and:

1. **Add your inventory** — the tools and equipment people can borrow.
2. **Turn on public visibility** — open your makerspace and enable **"public inventory"** so it
   shows on the public catalog.
3. **Add your team** — **Users → People → Add staff**: a username, a starting password and a role
   (Space Manager, Inventory Manager, Machine Manager, or a role you create). Front-desk handover is a
   custom role, not a built-in. See [staff-roles.md](staff-roles.md) for what each role can do.
4. **Check enabled modules** — as the superadmin, open the **Modules** tab (or run
   `bash scripts/update.sh --modules-only`). A module that is off disappears completely from the
   public and staff screens; turning it back on brings everything back, data included.
5. **(Optional) Email & Telegram alerts** — Telegram under **Settings → Integrations**, your own mail
   server under **Settings → Notifications → Email (SMTP)**. Both have a test button. Step by step:
   [notifications-setup.md](notifications-setup.md).
6. **(Optional) Decide who hears what** — in **Settings → Notifications** you can tick which kinds of
   alert go out by email, Telegram, Slack, Mattermost or Discord and choose who receives each one;
   reword the messages in the **Email templates** tab.

### Stock, machine consumables and public printing

For individually tracked tools, create the inventory item with **zero stock**, verify the physical
units, then generate their tags and QR codes in **QR Tools**. Counts follow those units. Manual
quantity adjustments and procurement moves support quantity-tracked stock only. Existing inventory
is not repaired automatically: check the actual units before generating missing assets.

In **Machines → machine type → Consumables**, add stock for that type, such as filament for 3D
printers. There is no Shared consumables section. Existing machine-specific and legacy space-wide
pools stay usable by compatible jobs and appear in authorized machine drawers; no stock is deleted
or reassigned. The drawer's inventory-item links and local grams ledger are separate tools: do not
copy a filament pool there, which would create a second balance for the same material.

With **machines**, **machine_service** and **printing** enabled, open **Machines → 3D printers →
3D-printer queue → Enable public print requests**. This requires machine-management permission
covering the whole built-in printer type. It reuses an active queue or enables/creates only the
`Public Requests` default, preserving existing capacity and allocation settings. If that name belongs
to another type, rename the conflicting queue first. Viewing the public page never creates a queue.

In a machine drawer, use **Set status** to change operating status. **Save machine details** saves
name, location and other details separately. An unsaved status change blocks the details save: apply
it with Set status or restore the current status first. Authorized operators can still set status.

### Who gets told, and where

Out of the box, an alert goes to everyone whose job covers it — a booking alert reaches the people
who manage bookings. You do not have to configure anything for that to work.

If you want something different, three settings do it, all under **Settings → Notifications**:

- **Who gets notified** — pick recipients for one kind of alert: a role, one named member, everybody,
  or the person the message is about. Leaving it empty means "notify by role", which is the default.
  Anyone who has turned their own notifications off is never mailed, even if you pick them.
- **Rooms** — if you use Slack, Discord, Mattermost or Telegram, you can have more than one channel.
  Leave a room unrestricted and it hears everything; restrict it to a machine and it hears only that
  machine. Useful when the laser team and the print room are different people.
- **Email templates** — reword any message. Each one shows the details you can drop in (names, times,
  machine, and so on) and previews before you save. There is a reset button if you change your mind.

One rule the system enforces for you: messages written *for a member* ("your booking is confirmed")
only ever go to that member by email or phone, never into a shared chat channel where everyone could
read their name.

---

## Letting people on your network reach it

By default it's at `localhost` (only that computer). To let others at your space use it:

1. Find that computer's address on your network (its local IP, like `192.168.1.50`, or its
   hostname).
2. In the `.env` file, replace `localhost` with that address in `ALLOWED_HOSTS`,
   `CORS_ALLOWED_ORIGINS`, `PUBLIC_APP_BASE_URL`, `AWS_S3_PUBLIC_ENDPOINT_URL`, `PUBLIC_IMAGE_BASE_URL`
   and `MINIO_CORS_ALLOWED_ORIGINS` (keep `localhost,127.0.0.1` in `ALLOWED_HOSTS` too), then run
   `bash scripts/init-host-orchestration.sh` and `scripts/spaceworks-compose.sh bundled up -d`.
3. People then visit `http://<that-address>/` in their browser.

> For a public website with a real domain and HTTPS, you'll want someone technical to put a
> reverse proxy (e.g. Caddy or Nginx with a certificate) in front and set `ENABLE_HTTPS=true`.
> See [self-hosting.md](self-hosting.md).

## No spare computer?

You have two good options before giving up:

1. **Partner with another makerspace.** This app can run **many makerspaces on one backend**. If a
   nearby makerspace already runs it on their server, ask them to add yours as another "tenant" —
   you'll get your own catalog, your own web address, and your own admin, all on their shared
   backend. Most makers are glad to help another space, and it's an easy way for them to contribute.
2. **Rent a small cloud server.** A 2 vCPU / 4 GB virtual machine runs the same installer. This is
   more technical — see [deploy-ec2.md](deploy-ec2.md) for an AWS walkthrough. (The older
   Supabase/Render path in [deploy-production.md](deploy-production.md) is for demos only; it is not
   a supported backup-and-restore setup.)

---

## Everyday operations

- **Start it / after a reboot:** Docker Desktop can auto-start the app, or run
  `scripts/spaceworks-compose.sh bundled up -d`.
- **Stop it:** `scripts/spaceworks-compose.sh bundled down`
  (your data is safe — it's kept in a database volume).
- **Update to a newer version:** guided installs offer self-hosted Actions runner updates on Linux/systemd. Run
  `bash scripts/update.sh` on Linux, macOS or (on Windows) WSL2 to update immediately when your installed
  version differs from the latest release; add `--force` to reinstall the same release. Configure the
  runner and enable the repository variable `SPACEWORKS_DEPLOY_RUNNER=true`; require approval for all
  outside collaborators and review workflow changes before approval, because fork PRs can target the host.
  See [runner setup and public-repository risks](self-hosting.md#automatic-and-manual-upgrades);
  the interactive command also opens the current module tick list. The updater backs up
  PostgreSQL and verifies the new release before marking it installed. If the new application fails,
  it automatically returns to the previous retained release. Your `.env` and data are preserved. The
  database snapshot is retained but never restored automatically, and it does not cover MinIO photos
  and files; back up the MinIO data volume separately.
- **Change modules without upgrading:** run `bash scripts/update.sh --modules-only --makerspace <slug>`.
  With several makerspaces, select one slug or explicitly use `--all-makerspaces`; the updater never
  guesses. Use `--modules` to force the tick list during an update, or `--no-module-changes` to update only
  the release. Unticking asks for confirmation and retains all module data; install and update never run
  the separate destructive `purge_module_data` command.

Pasting the curl installer again over an install with `.spaceworks-version` opens a menu for update,
module changes, both, or cancel. A non-empty directory without that marker is refused instead of being
treated as a safe live deployment.

### Windows support boundary

Windows is supported through **WSL2 only**, for everything: install, Compose run/stop/logs, update,
module changes, restore, backup import and compound host recovery. Run them from WSL2 with Docker
Desktop's WSL integration. Native Git Bash and PowerShell are not supported — the production host scripts need Linux `flock`, AF_UNIX sockets, root-owned-file trust semantics and Docker bind paths that Git Bash's MSYS path conversion rewrites.
`setup.ps1` and `scripts/update.ps1` only print that refusal.

## Something went wrong?

- **"Docker is not running"** — open Docker Desktop and wait for it to start, then try again.
- **The page won't load** — give it another minute on first run; image download and startup take time.
- **See what's happening:** run
  `scripts/spaceworks-compose.sh bundled logs backend`.
- Still stuck? Open an issue on GitHub describing what you did and what you saw.

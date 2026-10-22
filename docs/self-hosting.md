# Self-Hosting Guide

This project is Docker-first for operators who do not want to build Django or Vite locally.

## Pinned curl install

The supported fresh-install path needs no Git clone:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | bash
```

The installer defaults to `/opt/spaceworks`; override it on the `bash` process with, for example,
`curl -fsSL https://raw.githubusercontent.com/SpaceWorks-HQ/SpaceWorks/main/install.sh | SPACEWORKS_DIR="$HOME/SpaceWorks" bash`.
It resolves the latest tagged GitHub release,
downloads that tag's archive, and pins the published backend/frontend images to its immutable version.
Before mutating the host it checks x86_64/aarch64 support, distribution/dependency handling, Docker,
ports 80/9000/9001, 8 GiB of free disk, release availability, and existing state. Linux dependency
installation supports apt, dnf/yum, pacman and zypper families identified from `/etc/os-release`.

If `.spaceworks-version` already exists, pasting the command again offers update, module changes, both,
or cancel; it never reruns first-instance setup. A non-empty install root without the marker is refused.

## Production Compose

Use the production Compose file when deploying published images:

```bash
cp .env.example .env
# Fill the required values, then provision the root-owned pointer/key/config state once.
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled up -d
```

Set these values before first boot. The guided installer generates all of them; by hand, replace every
placeholder (a placeholder `SECRET_KEY` fails system check `accounts.E001` and `migrate` refuses):

```env
POSTGRES_PASSWORD=replace-with-a-strong-password
POSTGRES_APP_PASSWORD=replace-with-a-different-strong-password
SECRET_KEY=replace-with-a-long-random-secret
ALLOWED_HOSTS=inventory.example.org
CORS_ALLOWED_ORIGINS=http://inventory.example.org
PUBLIC_APP_BASE_URL=http://inventory.example.org
MINIO_ROOT_USER=replace-with-a-random-access-key
MINIO_ROOT_PASSWORD=replace-with-a-long-random-secret
AWS_S3_PUBLIC_ENDPOINT_URL=http://inventory.example.org:9000
PUBLIC_IMAGE_BASE_URL=http://inventory.example.org:9000/public-images
MINIO_CORS_ALLOWED_ORIGINS=http://inventory.example.org
ENABLE_HTTPS=false
AUTH_COOKIE_SAMESITE=Lax
AUTH_COOKIE_SECURE=False
MAKERSPACE_IMAGE_TAG=latest
```

Optional image overrides:

```env
MAKERSPACE_BACKEND_IMAGE=ghcr.io/spaceworks-hq/spaceworks-backend
MAKERSPACE_FRONTEND_IMAGE=ghcr.io/spaceworks-hq/spaceworks-frontend
```

### Deploying a fork

Set `SPACEWORKS_REPOSITORY=owner/repo` on the fresh installer's `bash` process to follow your fork's
GitHub releases. The installer derives `ghcr.io/<lowercased owner>/spaceworks-backend` and
`spaceworks-frontend` unless you supply explicit image overrides, then forwards those settings
to `setup.sh` for persistence in `.env`.
On an existing curl install, `.env` selects the repository unless explicitly overridden.
Direct `scripts/update.sh` calls resolve the repository from the shell, then `.env`, then
`SpaceWorks-HQ/SpaceWorks`. Repository selection and image selection are separate on existing hosts;
set both image names explicitly when changing forks.

`setup.sh` and `scripts/init-host-orchestration.sh` resolve the host-configuration backend image from
the shell, then `.env`, then the upstream default. Its tag resolves from the shell, then `.env`, then
`.spaceworks-version`, then `latest`, matching the Compose wrapper's precedence.
Rerun `bash scripts/init-host-orchestration.sh` after any `.env` edit. For EC2 installation, check-in
setup, HTTPS and automatic redeploys from `tinkerhub/SpaceWorks`, see [deploy-ec2.md](deploy-ec2.md).

### Build from source (explicit opt-in)

Release images are published to GHCR and `setup.sh` pulls them by default. A developer with a full
source tree can explicitly build locally:

```bash
bash setup.sh --build
```

For a guided first run that generates secrets, the atomic pointer and `.env`, use the curl installer or
`setup.sh` at the repo root (see [setup-for-makerspaces.md](setup-for-makerspaces.md)).

Windows is supported through WSL2 only: run every host script (installer, `setup.sh`, update, restore,
backup import, compound recovery) from a WSL2 shell with Docker Desktop's WSL integration. Native Git
Bash and PowerShell are not supported — the production host scripts need Linux `flock`, AF_UNIX sockets, root-owned-file trust semantics and Docker bind paths that Git Bash's MSYS path conversion rewrites; `setup.ps1` and
`scripts/update.ps1` only print that refusal.

> The frontend container's nginx proxies `/api/`, `/static/`, and the docs routes to the backend.
> The **single published port (80)** serves the public app, the React staff console at `/admin`,
> and Swagger. The Django control plane is mounted at `/control/` on the backend and is
> intentionally **not exposed** on the public frontend port; access it only through direct backend
> access.

## First Run

Create the first superadmin and makerspace:

```bash
scripts/spaceworks-compose.sh bundled run --rm --no-deps backend --role management python manage.py setup_instance \
  --username admin \
  --email admin@example.org \
  --password "replace-with-a-strong-password" \
  --makerspace-name "My Makerspace"
```

The command is idempotent. It creates missing records and upgrades the named user to a superadmin if needed.
There is no default password: `--password` (or `SETUP_SUPERADMIN_PASSWORD`) is required to create the
user, and rerunning it for an existing user does **not** change that user's password (see
[staff-roles.md](staff-roles.md#passwords)).

After signing in, a superadmin lands on **Choose a makerspace to operate**; pick the makerspace to open
its staff console.

## Health Checks

Backend:

```text
GET /api/v1/health/            # public liveness: the process answers HTTP
GET /api/v1/health/readiness/  # deployment probe: host marker, migrations, encryption readiness
```

The Compose files include health checks for Postgres, backend readiness, and frontend HTTP serving.
Readiness is meant for callers inside the deployment: the bundled Caddy and nginx proxies answer `403`
for it (an existing TLS install must add the Caddy block by hand; see
[Upgrade notes](#upgrade-notes-manual-steps-per-release)), and the Compose healthcheck and `scripts/update.sh` call it on `localhost:8000` inside the
backend container. A direct, unproxied caller gets the failure reason and archive-custody counts; a
caller that arrives through any proxy (an `X-Forwarded-For` header) gets only `status`, the same
`200`/`503`, and is rate limited by `THROTTLE_READINESS` (default `60/min`).

## Scheduled Jobs

Return reminder emails are sent by a management command. The bundled Compose profiles run it through the
role-aware image entrypoint. An external cron, systemd timer, Windows Task Scheduler, or provider scheduler
must additionally be disabled by its control plane unless the host restore marker is `normal` or
`acknowledged-normal` (or it must call the same host gate); otherwise that topology is refused because it
can retain credentials and bypass the
container marker. Once that fence is configured, schedule it every 15-60 minutes:

```bash
scripts/spaceworks-compose.sh bundled run --rm --no-deps backend --role management python manage.py send_return_reminders
```

The command is idempotent. It only sends reminders for issued or partially returned requests whose `return_due_at` is in the past and whose reminder has not already been sent. Requests returned before the due time are skipped.

## Automatic and manual upgrades

CI runs on pull requests to main/dev and on pushes to main; push CI includes the reusable security audit (`pip-audit`). Only a
successful CI run for a push to `main` triggers `release.yml` through `workflow_run`; a failing main
run produces no release. Manual release dispatch also requires the `main` ref and a successful push CI
run for that exact SHA. The release is marked latest only after both images are available and the
released commit is still the main branch head. The self-host updater uses that release
as its gate, creates a PostgreSQL backup, deploys the exact immutable tag, runs migrations through the
Compose migration service, and records the version only after the readiness check passes.

Guided setup asks **Enable automatic production updates from main?** before starting the stack. The
default is **No**: the runner needs a systemd host and a runner token from the GitHub repository you deploy
from (your own fork). **Yes** prints runner setup instructions after the stack is up; setup does not mint or save a token.
Automatic deployment requires Linux x64/arm64, running systemd and sudo. Run the installer as the
current, non-root install owner; the runner lives in `$HOME/spaceworks-actions-runner` and its service
runs as that user. The installer verifies the pinned Actions runner v2.338.0 archive's SHA-256 and
retires old release polling jobs. Other platforms can still update manually.

**Public repository warning:** a repository-level runner can receive a fork PR workflow targeting
`spaceworks-prod` once a maintainer approves it. Requiring approval is a human gate, not isolation.
Review every workflow change before approving a fork PR run. An organization runner group restricted
to `deploy.yml@main` is the stronger boundary and requires an organization administrator.

In the followed repository, configure both GitHub settings:

1. **Settings → Actions → General → Fork pull request workflows:** require approval for **all outside
   collaborators** (`all_external_contributors`). When `gh` is available, the installer checks this policy
   and refuses an unsafe result unless `SPACEWORKS_RUNNER_ACCEPT_RISK=1` explicitly accepts the risk.
   An unavailable policy check does not prove the setting is safe; verify it yourself before registration.
2. **Settings → Secrets and variables → Actions → Variables:** add `SPACEWORKS_DEPLOY_RUNNER=true`.
   With authenticated `gh`, use `gh variable set SPACEWORKS_DEPLOY_RUNNER --body true --repo OWNER/REPO`.

Then install the runner as the install owner. Guided setup does this when you answer **Y** to
automatic updates, the curl installer offers **Set up automatic deploys (GitHub runner)** on an
existing host, or run it directly. It asks for a one-time registration token at a hidden prompt and
prints where to get one (**Settings → Actions → Runners → New self-hosted runner**):

```bash
bash scripts/install-deploy-runner.sh
```

For unattended use, export `RUNNER_TOKEN` instead (for example
`RUNNER_TOKEN="$(gh api -X POST repos/OWNER/REPO/actions/runners/registration-token --jq .token)"`).
The installer passes the token through `ACTIONS_RUNNER_INPUT_TOKEN`, never argv or the runner `.env`.
It resolves the repository from the installed configuration. `SPACEWORKS_INSTALL_DIR` is written to
the runner's own `.env`, not supplied by the workflow.

`deploy.yml` runs only after **Continuous Release** completes successfully on `main`, or manual
dispatch on `main`. It has no checkout or action steps and runs only installed
`update.sh --no-module-changes`, with `SPACEWORKS_DEPLOY_WAIT=1` to wait for the update lock. The
release is already promoted to latest before this job runs. Output, including rollback results, is
available in the Actions job log. No other workflow may target a self-hosted runner.

To repair the same-repository configured runner, rerun `bash scripts/install-deploy-runner.sh` without
a token: it refreshes the install path and restarts the service without extraction or registration.
Set `SPACEWORKS_DEPLOY_RUNNER=false` to stop future automatic deployment jobs. To unregister, get a
fresh removal token from GitHub's runner removal instructions (or the `actions/runners/remove-token`
API), then run as the install owner:

```bash
bash scripts/install-deploy-runner.sh --remove   # asks for the removal token (hidden)
```

Run an immediate checked update with:

```bash
bash scripts/update.sh  # add --force to reinstall the latest release even if already installed
```

When run in a terminal, the updater opens the same live-registry module tick list after the release is
healthy. It is seeded from each makerspace's current `enabled_modules`, not an install profile. Runner
deployments explicitly skip module changes. Useful explicit forms are:

```bash
# Explicitly open the live module tick list after a checked update.
bash scripts/update.sh --force --modules

# Update the release without reviewing or changing modules.
bash scripts/update.sh --force --no-module-changes

# Change modules without checking for a release.
bash scripts/update.sh --modules-only --makerspace my-space

# Non-interactively enable all optional modules except two for one makerspace.
bash scripts/update.sh --all-modules --without=printing,payments \
  --makerspace my-space --confirm-removals

# A cross-tenant change is never implicit.
bash scripts/update.sh --all-modules --all-makerspaces
```

With multiple makerspaces, interactive use asks for a slug; non-interactive use refuses unless given
`--makerspace` or the explicit `--all-makerspaces` opt-in. Unticking/disabling a module requires
confirmation and runs the two-pass dependency-safe uninstall loop. It only invokes `uninstall_module`:
retained rows are never purged by setup or update. `--modules` forces the interactive review;
`--modules-only`, `--all-modules`, `--without=a,b`, `--makerspace <slug>`, `--all-makerspaces`,
`--confirm-removals` and `--no-module-changes` provide explicit non-default behavior for operators and
automation.

Pre-update database dumps are written to `backups/` and retained for 14 days. Each compressed dump
contains PostgreSQL data: users, settings, inventory, requests, loan history, and audit metadata. It does
**not** contain MinIO objects such as evidence photos, machine images, documents, or print files; back up
the `minio_data` volume separately. The database snapshot is a recovery point and is never restored
automatically.

The scripts use `.spaceworks-update.lock` to prevent overlapping runs and `.spaceworks-version` to avoid
redeploying the same release. If migration, deployment, or readiness fails after replacement starts, the
updater automatically pulls and starts the previous retained application release, then verifies its
health. The version marker is not advanced, the runner's Actions job log records whether
rollback succeeded, and the database backup remains available. Database migrations are not reversed
automatically; keep migrations backward compatible with the immediately previous application release.
If application rollback also fails, review
the Actions job log (or manual updater output) before restoring the database snapshot and previous image tag manually.

Known limitation: when an upgrade started from the curl installer fails, rollback restores the previous
images and producer proof but keeps the installer's newer host files, so compound backups refuse the
mismatched privileged-script hashes. Rerun the installer once the release is fixed, or copy the files back
from the newest `backups/host-config-*/` and rerun `bash scripts/init-host-orchestration.sh`.

On hosts with `flock`, the updater also holds the shared host operation-lock inode. Where `flock` is
missing, update falls back to the existing directory lock, recording its owner PID and start timestamp.
A dead owner is detected and cleared on the next run. A live or unreadable owner is never silently
discarded: after verifying no update is active, pass `--override-lock`. This fallback covers update only;
`scripts/restore.sh` and the other compound recovery supervisors require `flock`.

For a manual deployment, set `MAKERSPACE_IMAGE_TAG` to a release such as
`0.5.1-main.42.a1b2c3d4e5f6`, then run:

```bash
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled pull
scripts/spaceworks-compose.sh bundled up -d
```

Do not schedule a blind container watcher: application images must not restart without the migration
service and readiness gate. Manual dependency audit: `pip install pip-audit && pip-audit -r backend/requirements.txt`.

### Host configuration changes

Any edit to `.env` or a Compose file selected for the active topology/layer requires rerunning
`bash scripts/init-host-orchestration.sh` before using the Compose wrapper again.
`backend/apps/backup/host_topology_record.py` hashes the raw bytes of the static `.env` and the ordered
Compose files selected by `scripts/spaceworks-compose.sh` into a root-owned topology record, not resolved
image references. Exported shell variables are not fingerprinted, so an exported image override is not
detected. If a recorded file changes, `validate_compose_wrapper` raises
`Compose configuration digest drifted`; the next Compose command refuses to run until the trusted
record is rebuilt.

Ordinary `scripts/update.sh` runs replace images and do not download host tooling. To adopt a release's
new scripts, Compose files or proxy configuration, rerun the curl installer and choose an update. It
stages the pinned release and runs its updater against the existing install, backing up the database
before adopting the host bundle. Private `.env`, version/layer markers, backups, volumes and host
orchestration state are preserved. This uses release archives and does not require Git.

The TLS overlay pins Caddy to an explicit patch release. `scripts/update.sh` pulls only the SpaceWorks
backend and frontend images, not Caddy, so installing a Caddy security update requires changing that pin in
`docker/compose.tls.yml`, rerunning `bash scripts/init-host-orchestration.sh`, and bringing the Compose layer
up again.

The wrapper reads the persisted `.spaceworks-layer` marker. Save `tls` or `saas` there before rebuilding
configuration records for that overlay, so runner deployments and rollback retain the active topology.
An explicit `SPACEWORKS_COMPOSE_LAYER` still overrides the marker for an individual command.

A release that changes `deploy/Caddyfile` — for example the 403 deny on `/api/v1/internal/*` that keeps the
infra-only TLS ask endpoint off the public site — reaches an existing TLS host only once you install the
new file and recreate Caddy:

```bash
SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled up -d --force-recreate caddy
```

Use `build-tls` if that is the host's layer. Recreate rather than reload: the Caddyfile is a single-file
read-only bind mount, so replacing the file can leave the running container on the old copy. No
`init-host-orchestration.sh` rerun is needed for a Caddyfile-only change, because the topology record
fingerprints only `.env` and the selected Compose files.

### Upgrade notes: manual steps per release

A plain `bash scripts/update.sh` (and the runner deploy, which calls the installed copy) pulls new
images, migrates and restarts. From the release after 0.8.5-main.11 it also brings
`deploy/Caddyfile` and `deploy/Caddyfile.saas` up to the release being deployed (downloaded from that
tag; the curl installer's update uses its staged copy) and recreates a running Caddy, **but only when
your file is byte-identical to a version some release shipped**. The replaced copy is kept under
`backups/proxy-config-*/`. A customised Caddyfile (for example a redirect for a split deployment) is
never overwritten: the updater writes the release's version beside it as `deploy/Caddyfile.release`
and prints a warning; merge it by hand, then recreate Caddy as above. An `update.sh` run with no new
release performs the same check. Hosts on 0.8.5-main.11 or older run their installed updater, which
lacks this step, so apply the notes below by hand once, or rerun the curl installer and choose an
update (which installs the new updater and applies the same unedited-only rule).

**2026-10 (0.8.5): block public readiness at the proxy.** Add this inside the `{$PUBLIC_DOMAIN}` site
block of `/opt/spaceworks/deploy/Caddyfile`, next to the existing `/api/v1/internal/*` handle and
before the `reverse_proxy` lines:

```caddy
    # Readiness is a deployment probe: healthchecks and update.sh call it inside the
    # backend container. Public liveness stays at /api/v1/health/.
    handle /api/v1/health/readiness* {
        respond 403
    }
```

Then recreate Caddy and check both endpoints:

```bash
cd /opt/spaceworks
SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled up -d --force-recreate caddy
curl -s -o /dev/null -w '%{http_code}\n' https://YOUR_DOMAIN/api/v1/health/readiness/   # 403
curl -s -o /dev/null -w '%{http_code}\n' https://YOUR_DOMAIN/api/v1/health/             # 200
```

Without the block nothing breaks: a proxied caller already gets only `{"status": ...}`, rate limited.
The block keeps the probe off the public internet entirely.

Behaviour changes in the same release that operators notice:

- **`setup_instance` has no default password.** Pass `--password` or set `SETUP_SUPERADMIN_PASSWORD`;
  without one it refuses before writing anything. There is no `super123` or similar built-in login.
- **`SECRET_KEY` is checked.** With `DEBUG=False`, a value under 32 characters or a placeholder such as
  `replace-with-a-long-random-secret` fails system check `accounts.E001`, so `migrate` (and therefore
  the update) refuses. Installer-generated keys pass.
- **A module that is off is absent.** Its console tabs, settings cards, public pages and API surfaces
  disappear rather than showing empty; turning it back on restores everything, data included.
- **Staff are managed under Users.** The **Members** tab exists only while the `membership` module is
  on; staff accounts, roles and password resets live in **Users** either way. See
  [staff-roles.md](staff-roles.md).
- **Check-in mode checks in everyone.** On a `checked_in` makerspace every public borrower, signed in
  or not, is matched against the roster. See [checkin-mode.md](checkin-mode.md).

## Publishing new images (maintainers)

`release.yml` no longer runs directly on pushes. Its `workflow_run` trigger waits for CI to complete
on `main`, then releases only when the conclusion is `success` and the original event is `push`.
CI is only `pip-audit`; the test suites run locally before pushing, not in CI. Manual dispatch is refused unless the ref is `main` and a
successful push CI run exists for the exact release SHA.

The workflow publishes `ghcr.io/<lowercased repo owner>/spaceworks-backend` and
`ghcr.io/<lowercased repo owner>/spaceworks-frontend`, then creates a
GitHub Release titled `SpaceWorks v<version from VERSION>` (for example, `SpaceWorks v0.5.1`). Its internal tag still
identifies the exact build used by the updater. When both images succeed for the current branch head, the workflow promotes
them to the rolling `:X.Y`, `:main`, and `:latest` tags, then removes older Releases and GHCR versions.
The current and immediately previous builds remain available so a failed deployment can roll its
application containers back automatically.

The root **`VERSION`** file selects the semantic release series. Edit it (for example, to `1.0.0`) only
when starting a new series; the workflow adds the run number and commit SHA to every release automatically.

The `spaceworks-backend` / `spaceworks-frontend` GHCR packages must be set to **Public** after the first
release (org → Packages) so operators can pull without authenticating; private packages require
`docker login ghcr.io` on the host. Organization Actions policy must allow `GITHUB_TOKEN` package writes.

## HTTPS & security hardening

TLS-dependent settings are **env-gated, not `DEBUG`-gated**, so the default HTTP stack works out of
the box. The default frontend nginx does **not** trust inbound `X-Forwarded-Proto`; it forwards only
its own scheme to Django.

For a real domain with automatic TLS, use the Caddy overlay:

```env
PUBLIC_DOMAIN=inventory.example.org
CORS_ALLOWED_ORIGINS=https://inventory.example.org
PUBLIC_APP_BASE_URL=https://inventory.example.org
STORAGE_DOMAIN=files.inventory.example.org
CSRF_TRUSTED_ORIGINS=https://inventory.example.org
AWS_S3_PUBLIC_ENDPOINT_URL=https://files.inventory.example.org
PUBLIC_IMAGE_BASE_URL=https://files.inventory.example.org/public-images
MINIO_CORS_ALLOWED_ORIGINS=https://inventory.example.org
ENABLE_HTTPS=true
AUTH_COOKIE_SAMESITE=Lax
```

```bash
printf '%s\n' tls > .spaceworks-layer
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled up -d
```

The layer marker persists this selection for later wrapper commands, host-triggered deployments and
rollback. Save it before initialization so the trusted topology record describes the TLS overlay.

This overlay forces `AUTH_COOKIE_SECURE=True`, because a refresh cookie without `Secure` is
never correct on an HTTPS deployment and `setup.sh` writes `False` for the plain-HTTP origin
it configures. `AUTH_COOKIE_SAMESITE` stays yours to set: the bundled frontend is same-origin,
so `Lax` is right, while a frontend on a separate origin needs `None`.

The Compose layer now both selects and activates the TLS overlay. The Caddy service no longer has a
redundant `profiles: ["tls"]` activation gate: `scripts/update.sh` runs `up -d` without `--profile`, so
keeping that second gate made every unattended update bring the stack back without its TLS terminator and
roll the deployment back into the same plain-HTTP topology.

`STORAGE_DOMAIN` creates the `files.` hostname as a Caddy site in `deploy/Caddyfile`, where it proxies
`minio:9000`; its host must match the host in `AWS_S3_PUBLIC_ENDPOINT_URL`. Create DNS records for both the
application hostname and the storage hostname before starting the overlay, or ACME certificate issuance
cannot succeed. `PUBLIC_IMAGE_BASE_URL` must also be set explicitly because `setup.sh` initializes it to
`http://<host>:9000/public-images`. Leaving that plaintext value in place makes every public item photo and
makerspace logo a mixed-content failure in an HTTPS browser, even after presigned uploads work.

The TLS overlay removes MinIO's inherited host port publications, including plaintext `0.0.0.0:9000`.
Only Caddy's HTTPS `STORAGE_DOMAIN` site is reachable from outside the Compose network; the backend and
Caddy continue to reach MinIO internally at `minio:9000`.

The overlay enables `ENABLE_HTTPS=true` and `TRUST_X_FORWARDED_PROTO=true` for the backend. Caddy is then
the trusted TLS boundary: `/api`, `/static`, and docs paths go directly to Django with
`X-Forwarded-Proto: https`, while the React app goes to the frontend container. Keep any direct
backend/frontend HTTP ports private when the TLS overlay is active.



Always-on protections (any transport): `django-axes` locks out brute-force admin logins
(`AXES_FAILURE_LIMIT`, keyed by ip+username), a scoped throttle limits the JWT login endpoint, the
public submit endpoint has its own anti-spam throttle + a honeypot, and a Content-Security-Policy is
sent on every response. The Django control plane at `/control/` is restricted to active
superusers only and must be reached through direct backend access, never through the public
frontend port.

Secrets (`SECRET_KEY`, `API_CLIENT_ENC_KEY`, makerspace Telegram bot tokens, makerspace SMTP
passwords) live only in the backend. `API_CLIENT_ENC_KEY` is the Fernet key that encrypts the
per-makerspace integration secrets at rest — **back it up and do not rotate it casually**, or
previously stored tokens/passwords can no longer be decrypted.

## Custom domain (self-host)

On a self-hosted instance (the default — `PLATFORM_DOMAIN_SUFFIX` is **blank**) you own both DNS and
the server, so a makerspace's custom domain is **trusted the moment a superadmin sets it** — there is
no DNS TXT challenge. (The TXT-verification flow only exists to defend the shared managed `space-works.tech`
box; it stays dormant here.) End-to-end:

1. **Point DNS at the server.** Create an `A`/`AAAA` record for the hostname (for example
   `tools.example.org`) pointing at this deployment's public IP.
2. **Enable automatic HTTPS.** Staff login on a custom domain requires HTTPS — the staff-auth
   allowlist only trusts the `https://` origin (localhost dev is the sole `http` exception). Set the
   TLS env and bring up the Caddy overlay:

   ```env
   PUBLIC_DOMAIN=tools.example.org
   CSRF_TRUSTED_ORIGINS=https://tools.example.org
   # Django's own host check (CommonMiddleware) is separate from the tenant host
   # middleware — add every custom hostname here or requests 400 with DisallowedHost.
   ALLOWED_HOSTS=localhost,127.0.0.1,tools.example.org
   ```

   ```bash
   SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled up -d
   ```

   Caddy (`deploy/Caddyfile`) terminates HTTPS and forwards both the public site and the `/admin`
   staff console to this deployment.
3. **Set the domain in Settings.** As a **superadmin**, open the makerspace's **Settings → Domain & access → Custom
   domain**, enter the hostname, and Save. It shows **Active** immediately (no TXT record, no Verify
   step). Only a superadmin may set it — the staff-auth/CORS allowlist is process-global (not
   tenant-scoped), so on a multi-makerspace box an untrusted Space Manager must never be able to inject
   a globally-trusted origin. This holds even for a makerspace hidden from the superadmin
   (`superadmin_access_enabled=False`): to set its domain, have its Space Manager re-enable superadmin
   access, set the domain as the superadmin, then re-hide it.
4. **Point the branded frontend at this backend.** Set the frontend container's
   `TENANT_ORIGIN_BOOTSTRAP=true` (resolve the makerspace by request origin) **or**
   `TENANT_TOKEN=<public_code>`, plus `TENANT_API_URL=/api`. See
   [single-tenant-frontend.md](single-tenant-frontend.md). `docker-compose.prod.yml` does not pass
   these to the `frontend` service, so on the bundled stack the domain serves the central layout
   (public catalogue at `/m/<slug>`, console at `/admin`) until you add them to that service's
   `environment:`. Staff sign-in and origin scoping work either way.

If an instance flips from managed → self-host after deploy, run
`python manage.py reconcile_selfhost_domains` once to promote any existing custom domains to trusted
(the migration does this automatically on a fresh self-host deploy).

## Environment reference

The installer (`setup.sh`) generates every secret marked *generated* below and writes `.env` for
you; this table is for checking or hand-editing it. Values reach the backend only through the
`environment:` block of the Compose file, so a variable listed as *not forwarded* has no effect when
set in `.env` on the bundled stack. After any `.env` edit, rerun `bash scripts/init-host-orchestration.sh`
and `scripts/spaceworks-compose.sh bundled up -d`.

**Secrets that must be set, and backed up, in production:**

| Variable | Generated | Without it |
|---|---|---|
| `SECRET_KEY` | yes (50 chars) | The backend does not start. A value under 32 characters, with fewer than 5 distinct characters, or containing a placeholder word (`replace-with`, `change-me`, `changeme`, `insecure`) fails system check `accounts.E001` when `DEBUG=False`, so `migrate` and every update refuse |
| `API_CLIENT_ENC_KEY` | yes (Fernet) | Saving a Telegram token, SMTP password or chat webhook returns **503** (`secret_storage_unavailable`); API-client, payment and platform-email secrets fail to save. Changing it makes every stored secret unreadable |
| `AUDIT_MAC_MASTER_KEY` | yes (Fernet) | Warning `audit.W001`; audit rows are not sealed with a per-scope MAC. An invalid value is error `audit.E001` |
| `BACKUP_AGE_RECIPIENT`, `BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY`, `BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY` | yes (the age identity lives in `/var/lib/spaceworks/ops/work/age-identity.txt`) | Backups and tenant exports refuse to run. Without the age identity a backup cannot be decrypted |
| `POSTGRES_PASSWORD`, `POSTGRES_APP_PASSWORD`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | yes | The stack does not start |

Keep an offline copy of `.env` and the age identity file. A restore writes the archived continuity keys
(`SECRET_KEY`, `API_CLIENT_ENC_KEY`, `AUDIT_MAC_MASTER_KEY`, …) back into `.env`.

| Variable | Required | Purpose |
|---|---|---|
| `POSTGRES_PASSWORD` | yes | Maintenance/owner database password; never used by application processes |
| `POSTGRES_APP_PASSWORD` | yes | Separate non-owner runtime database password used by backend/worker/beat/cron |
| `SECRET_KEY` | yes | Django cryptographic secret. With `DEBUG=False`, a placeholder or a value under 32 characters fails system check `accounts.E001`, so `migrate` refuses to run |
| `ALLOWED_HOSTS` | yes | Comma-separated hostnames the backend will serve |
| `TRUSTED_PROXY_COUNT` | yes (bundled default `1`) | Reverse proxies in front of the backend, used to find the client IP for rate limits. With `DEBUG=False` an unset value stops the backend; use `0` only when clients reach Django directly |
| `DATABASE_URL` | no | Never put this in static `.env`; the atomic ops pointer is its only Compose source |
| `CORS_ALLOWED_ORIGINS` | yes | Browser origins allowed to call the API (exact `scheme://host`, comma-separated). The bundled install writes its own origin |
| `PUBLIC_APP_BASE_URL` | yes | Absolute frontend base URL for links in email (invitations, member-area and machine-job links) and payment returns. Unset falls back to `http://localhost:5000`. Password reset sends a code, not a link |
| `API_CLIENT_ENC_KEY` | yes | See the secrets table above |
| `AUDIT_MAC_MASTER_KEY` | yes | See the secrets table above |
| `TOMBSTONED_APPS` | no | App labels whose runtime surfaces are removed deployment-wide; get the line from `manage.py suggest_tombstones` |
| `GITHUB_API_TOKEN` | no | Enables the GitHub contribution count on maker profiles. Not forwarded by the bundled Compose files yet |
| `TELEGRAM_BOT_TOKEN` | no | Deployment-wide fallback bot for makerspaces without their own token. Not forwarded by `docker-compose.prod.yml`; set tokens in the console ([notifications-setup.md](notifications-setup.md)) |
| `TELEGRAM_WEBHOOK_SECRET` | no | Authenticates Telegram's webhook calls, which are acknowledged and ignored (alerts are outbound only). Not forwarded by `docker-compose.prod.yml` |
| `SPACEWORKS_REPOSITORY` | no (default `SpaceWorks-HQ/SpaceWorks`) | GitHub `owner/repo` whose latest release the host follows; fresh installs derive image names from its lowercased owner |
| `MAKERSPACE_BACKEND_IMAGE` | no (default `ghcr.io/spaceworks-hq/spaceworks-backend`) | Backend image name without a tag; set explicitly for a fork on an existing host |
| `MAKERSPACE_FRONTEND_IMAGE` | no (default `ghcr.io/spaceworks-hq/spaceworks-frontend`) | Frontend image name without a tag; keep it paired with the backend image |
| `SPACEWORKS_DEPLOY_RUNNER` | repository variable for automatic deploys | Set `true` in GitHub Actions variables after runner setup; `false` disables automatic deployment jobs. This is not a host `.env` setting |
| `CHECKIN_API_URL` | for `checked_in` mode, unless every such makerspace sets its own roster | **Deployment default** public upstream roster URL; matching establishes presence eligibility, not identity. A makerspace can set its own roster URL in **Settings → Domain & access → Check-in** (or `set_request_access --checkin-api-url`), which overrides this for that makerspace only |
| `CHECKIN_PROVIDER_NAME` | no | Default name of your check-in system shown to borrowers; empty means "TinkerHub" for a TinkerHub roster URL, otherwise neutral wording. A makerspace with its own roster URL does not inherit it. See [checkin-mode.md](checkin-mode.md) |
| `CHECKIN_REQUIRED_PURPOSE` | no (default `Working on a project`) | Default required roster purpose; a makerspace may override it. The makerspace mode and upstream space ID are set in the console's Check-in card or with `manage.py set_request_access --mode checked_in --checkin-space-id N`. See [checkin-mode.md](checkin-mode.md) |
| `CHECKIN_TIMEOUT`, `CHECKIN_CACHE_SECONDS` | no (`5.0`, `30`) | Roster request timeout (must be positive; checked at startup) and name-search cache, in seconds. Apply to every roster, the deployment's and each makerspace's |
| `MINIO_IMAGE` | no (default `pgsty/silo`) | Server image repository only; optional registry port, no `:tag` or `@digest` |
| `MINIO_IMAGE_TAG` | no (default `RELEASE.2026-09-16T00-00-00Z`) | Server image tag; must exist in `MINIO_IMAGE` |
| `MC_IMAGE` | no (default `pgsty/mc`) | Client image repository only; optional registry port, no `:tag` or `@digest` |
| `MC_IMAGE_TAG` | no (default `RELEASE.2026-09-16T00-00-00Z`) | Client image tag; must exist in `MC_IMAGE` |
| `MINIO_ROOT_USER` | yes | MinIO/S3 access key used by the backend |
| `MINIO_ROOT_PASSWORD` | yes | MinIO/S3 secret key used by the backend |
| `AWS_STORAGE_BUCKET_NAME` | no (default `evidence`) | Private object-storage bucket for evidence and print files |
| `PUBLIC_IMAGE_BUCKET` | no (default `public-images`) | Anonymous-read bucket for public item photos and makerspace logo/cover images |
| `PUBLIC_IMAGE_BASE_URL` | yes for public images | Browser public base URL for `PUBLIC_IMAGE_BUCKET` (for example `https://files.inventory.example.org/public-images`) |
| `PUBLIC_IMAGE_MAX_BYTES` | no (default `5242880`) | Maximum public image upload size |
| `PUBLIC_IMAGE_URL_TTL_SECONDS` | no (default `300`) | Presigned upload URL lifetime for public images |
| `AWS_S3_ENDPOINT_URL` | no (default `http://minio:9000`) | Backend-to-MinIO endpoint inside Compose |
| `AWS_S3_PUBLIC_ENDPOINT_URL` | yes for uploads | Browser-reachable MinIO/S3 endpoint used in presigned URLs |
| `STORAGE_DOMAIN` | when the TLS overlay serves object storage | Hostname of the Caddy site proxying `minio:9000`; must match the host in `AWS_S3_PUBLIC_ENDPOINT_URL` |
| `MINIO_CORS_ALLOWED_ORIGINS` | yes for uploads | Comma-separated frontend origins allowed to POST/GET objects (sets MinIO's `MINIO_API_CORS_ALLOW_ORIGIN`; defaults to `*`) |
| `PUBLIC_DOMAIN` | when using the TLS overlay | Application hostname served by Caddy |
| `ENABLE_HTTPS` | no (default false) | Turns on SSL redirect, Secure cookies, HSTS |
| `AUTH_COOKIE_SAMESITE` | topology-dependent (code default `None`; setup writes `Lax`) | `Lax` for the bundled same-origin frontend; `None` for a frontend on a separate origin ([deploy-netlify.md](deploy-netlify.md)) |
| `AUTH_COOKIE_SECURE` | topology-dependent (code default `True`; setup writes `False`) | `False` only for plain HTTP; the TLS overlay forces `True` |
| `TRUST_X_FORWARDED_PROTO` | no (default false) | Trusts `X-Forwarded-Proto` only for the TLS proxy overlay |
| `CSRF_TRUSTED_ORIGINS` | when HTTPS | `https://` origin(s) trusted for login POSTs |
| `AXES_FAILURE_LIMIT` | no (default 5) | Failed admin logins before lockout |
| `HTTP_PORT` | no (default 80) | Published frontend port |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | for password recovery | Platform SMTP sender, used when neither the superadmin's Platform email settings nor a makerspace's own SMTP apply. Without any sender, **Forgot password?** is hidden. See [notifications-setup.md](notifications-setup.md#email) |
| `MANAGED_POSTGRES` | no (default `False`) | `True` on managed Postgres (Supabase): purge suspends immutability triggers via a custom GUC instead of `session_replication_role` (which needs superuser) |
| `CONN_MAX_AGE` | no (default `0`) | Persistent DB connection lifetime; keep `0` on the Supabase transaction pooler |
| `DISABLE_SERVER_SIDE_CURSORS` | no (default `False`) | Set `True` on the Supabase transaction pooler (no server-side cursors) |
| `STORAGE_PRESIGN_METHOD` | no (default `post`) | `put` for Supabase Storage presigned PUT uploads (server re-validates size at attach) |
| `CRON_SECRET` | no (default empty) | Enables `POST /api/v1/internal/cron/return-reminders` (header `X-Cron-Secret`); 404s while unset |

> **Supabase free-tier deployment** (managed Postgres + Storage, env-toggled, demo/pilot scope):
> see **[supabase-deployment.md](supabase-deployment.md)** for the full runbook. All five vars
> above default to the self-hosted behavior, so this Compose stack is unaffected unless you set them.

## Object Storage

Production Compose includes MinIO because the backend stores evidence photos and 3D-print files in
S3-compatible object storage by default. The backend talks to MinIO at `http://minio:9000`; browsers
use `AWS_S3_PUBLIC_ENDPOINT_URL` in presigned upload/download URLs, so that value must be reachable
from staff/requester browsers.

Public catalog images use a separate `PUBLIC_IMAGE_BUCKET` that is anonymous-readable by design.
The bundled Compose bootstrap creates it, sets `download` policy, and applies the same upload CORS
policy. Keep evidence and print files in the private `AWS_STORAGE_BUCKET_NAME`; only item photos and
makerspace logo/cover images belong in the public bucket.

For HTTPS deployments, put MinIO behind the same TLS proxy as the frontend, for example:

```env
AWS_S3_PUBLIC_ENDPOINT_URL=https://files.inventory.example.org
MINIO_CORS_ALLOWED_ORIGINS=https://inventory.example.org
```

If you expose MinIO directly on a LAN during a local pilot, set `AWS_S3_PUBLIC_ENDPOINT_URL` to the
server address and port that browsers can reach, for example `http://192.168.1.20:9000`. The MinIO
console binds to `127.0.0.1:9001` by default; keep it private or put it behind authenticated VPN/admin
access.

### Object storage images

Both Compose files default to `pgsty/silo:RELEASE.2026-09-16T00-00-00Z` and
`pgsty/mc:RELEASE.2026-09-16T00-00-00Z`: Pigsty's maintained MinIO fork (AGPL-3.0, amd64 + arm64).
MinIO's Docker Hub repositories return 404 and Quay refuses anonymous pulls; distroless variants and
Chainguard lack the shell/curl needed by the healthcheck and bucket bootstrap, while Bitnami Legacy is
frozen.

`MINIO_IMAGE` and `MC_IMAGE` take repository names only (`registry/namespace/name`, optional registry
port, no `:tag` or `@digest`); tags go in `MINIO_IMAGE_TAG` and `MC_IMAGE_TAG`. For a private mirror:

```env
MINIO_IMAGE=registry.example.org:5000/mirror/silo
MINIO_IMAGE_TAG=RELEASE.2026-09-16T00-00-00Z
MC_IMAGE=registry.example.org:5000/mirror/mc
MC_IMAGE_TAG=RELEASE.2026-09-16T00-00-00Z
```

Remove or replace any `MINIO_IMAGE_TAG` / `MC_IMAGE_TAG` pin to an upstream `RELEASE.2025-*` tag,
whether in `.env` or exported in the shell: those tags do not exist under `pgsty`. Exported shell
variables override `.env` during Compose interpolation.

#### Existing installations

`scripts/update.sh` never fetches Compose files. Existing installations keep running only while the
old `minio/minio` image remains in the local Docker cache; `docker image prune -a` would break the next
`up`. To adopt the new images, back up `minio_data` first (see [Backups](#backups)), while the current
topology record still validates. Install the new `docker-compose.prod.yml` and any overlays changed by
the release, remove or replace stale image tags, then run:

```bash
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled pull
scripts/spaceworks-compose.sh bundled up -d
```

Use the deployment's `SPACEWORKS_COMPOSE_LAYER=...` prefix on initialization and every wrapper command
if it uses a layer (for example `SPACEWORKS_COMPOSE_LAYER=tls`). Changes to `.env` or the active Compose
files require rebuilding the topology record; shell-exported overrides are not detected (see
[Host configuration changes](#host-configuration-changes)).

Switching an existing `minio_data` volume to Silo is a one-way data migration in practice: going back
means restoring the backup, not just reverting the image. The [Silo migration guide](https://silo.pigsty.io/compatibility/migration/)
asks operators to test the exact version pair before switching. The pair this repository moves between
was tested on 2026-10-13: a volume written by MinIO `RELEASE.2025-09-07T16-13-09Z` (the previous default)
was served by Silo `RELEASE.2026-09-16T00-00-00Z` with object versions, delete markers, versioning state
and bucket policies intact, and with presigned POST (MIME and size conditions enforced) and PUT
uploads working. If you pinned a different MinIO release, test your own pair.

## Backups

Operational data lives in Postgres and object files live in the `minio_data` Docker volume. Back up
both before upgrades. Stop writers and MinIO, retaining their containers and leaving the database running;
Silo has no `tar`, so a temporary Alpine container archives the stopped MinIO container's volume.

If the deployment uses a layer, prefix every wrapper command below with its
`SPACEWORKS_COMPOSE_LAYER=...` (for example `SPACEWORKS_COMPOSE_LAYER=tls`), including the command
inside `cid="$(...)"`.

```bash
scripts/spaceworks-compose.sh bundled stop frontend backend worker beat minio
scripts/spaceworks-compose.sh bundled exec -T db \
  pg_dump -U makerspace makerspace_manager > backup-$(date +%F).sql

mkdir -p backups
cid="$(scripts/spaceworks-compose.sh bundled ps -a -q minio)"
if [ -z "$cid" ]; then
  printf '%s\n' 'MinIO container not found; services remain stopped.' >&2
else
  docker run --rm --volumes-from "$cid":ro -v "$PWD/backups:/backup" \
    alpine:3.24.2 tar -czf /backup/minio-$(date +%F).tgz -C /data . && \
    scripts/spaceworks-compose.sh bundled up -d
fi
```

Also keep a copy of your `.env` (it holds `API_CLIENT_ENC_KEY`, without which encrypted integration
secrets are unrecoverable, and the MinIO credentials needed to read object backups).

Restore order is database first, then object files. Stop the same services and restore the Postgres
dump into the still-running `db` service before replacing the object files below. Replace
`YYYY-MM-DD` with the backup date. The archive is read in full first; only if it is intact is the volume
cleared and the archive extracted, so a mistyped date or corrupt file leaves the existing objects untouched.

```bash
scripts/spaceworks-compose.sh bundled stop frontend backend worker beat minio
# Restore the Postgres dump into db before continuing.
cid="$(scripts/spaceworks-compose.sh bundled ps -a -q minio)"
if [ -z "$cid" ]; then
  printf '%s\n' 'MinIO container not found; services remain stopped.' >&2
else
  docker run --rm --volumes-from "$cid" -v "$PWD/backups:/backup:ro" \
    alpine:3.24.2 sh -c 'a=/backup/minio-YYYY-MM-DD.tgz; tar -tzf "$a" >/dev/null && find /data -mindepth 1 -delete && tar -xzf "$a" -C /data' && \
    scripts/spaceworks-compose.sh bundled up -d
fi
```

After startup, check `/api/v1/health/readiness/`.

## Tenant Frontends

One backend can serve **many makerspaces**. A makerspace without its own server can be hosted as an
additional tenant on another makerspace's instance — each tenant gets its own makerspace record,
public URL/slug, branding, and (optionally) its own branded domain, all isolated by makerspace
scoping. To give a tenant its own branded site, set its **Custom domain**
(`Makerspace.frontend_domain`) under **Settings → Domain & access**; that single field drives CORS,
bootstrap resolution, and the staff-auth allowlist. See `docs/single-tenant-frontend.md`.

Browser frontends must use publishable configuration only. Do not place HMAC secrets in JavaScript bundles.

Use `GET /api/v1/bootstrap?tenant=<public-code>` or `GET /api/v1/bootstrap?slug=<makerspace-slug>`
(or simply serve the branded site from its `frontend_domain`, which bootstrap resolves by origin) to load:

- makerspace identity
- enabled modules and workflows
- theme and branding
- publishable public API hints

The React public and staff frontends use `enabled_modules` as live navigation gates. If a tenant does
not see a workflow, check the makerspace module flags first: a module that is off is absent from
both the public site and the console, not shown empty. For example the `inventory.self_checkout`
feature gates public self-checkout and staff direct handout, `printing` gates 3D printing, `stocktake`
gates stocktake, `containers` gates container tools, `qr_print_batches` gates QR tools, `scanner` the
scanner, `reports` the reports, and `membership` the Members tab. The full map is in
[MODULES.md](MODULES.md).

A makerspace's `frontend_domain` and its `cors_allowed_origins` (API-client origins) are used for
per-tenant browser access; only the `frontend_domain` origin may hold a staff session.

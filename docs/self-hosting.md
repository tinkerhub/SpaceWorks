# Self-Hosting Guide

This project is Docker-first for operators who do not want to build Django or Vite locally.

For a new makerspace, use the official
[SpaceWorks-Labs project and its current installation guide](https://github.com/SpaceWorks-Labs/SpaceWorks).
This checkout is TinkerHub's customized edition. Its release archives, images and host runtime must
come from a compatible release of that edition; do not combine an upstream image with this checkout's
host scripts. The unreleased 0.9.0 host bundle requires its matching future release archive.

## Pinned curl install

The supported fresh-install path needs no Git clone:

```bash
curl -fsSL https://raw.githubusercontent.com/SpaceWorks-Labs/SpaceWorks/main/install.sh | bash
```

The installer defaults to `/opt/spaceworks`; override it on the `bash` process with, for example,
`curl -fsSL https://raw.githubusercontent.com/SpaceWorks-Labs/SpaceWorks/main/install.sh | SPACEWORKS_DIR="$HOME/SpaceWorks" bash`.
These commands fetch the official project's installer. For this customized edition, obtain its
installer from the selected compatible tagged release, configure `SPACEWORKS_REPOSITORY` and both
image names explicitly, or use the source-build instructions below. Public availability of this
edition's published images has not been established by the local audit; private registries need
their normal authentication. Existing configured installations are not switched by these links.
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
scripts/spaceworks-compose.sh bundled pull
# Rebind after the final pull, which may have moved the backend tag.
bash scripts/init-host-orchestration.sh
unset SPACEWORKS_OCI_DIGEST
scripts/spaceworks-compose.sh bundled up -d --pull never
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

Source setup pulls infrastructure images before building the apps, while startup still forbids implicit pulls.

Source setup clears any stale `SPACEWORKS_OCI_DIGEST` and prints recovery instructions. A local build
has no claimed registry identity, so signed FULL deployment backups refuse before source capture.
Ordinary makerspace backups remain available. To enable FULL, publish and pull the actual backend
image, select that repository/tag, then provision and refresh configuration as described below;
neither the Docker config Id nor a tag is a repository digest.

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

For checked-in borrowing, the guided installer asks for a staff username and password as the
credentials. It leaves the admin email empty and skips Google sign-in configuration. Visitors use
the eligible check-in roster without an account or second factor; staff sign in with their own
username and password. Other request modes retain the email and optional Google prompts. See
[check-in setup](checkin-mode.md).

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
`scripts/restore.sh` and the recovery supervisors require `flock`.

For a manual deployment, set `MAKERSPACE_IMAGE_TAG` to a release such as
`0.5.1-main.42.a1b2c3d4e5f6`, then run:

```bash
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled pull
bash scripts/init-host-orchestration.sh
unset SPACEWORKS_OCI_DIGEST
scripts/spaceworks-compose.sh bundled up -d --pull never
```

Do not schedule a blind container watcher: application images must not restart without the migration
service and readiness gate. Manual dependency audit: `pip install pip-audit && pip-audit -r backend/requirements.txt`.

### Host configuration changes

Published-image setup and init automatically inspect the pulled backend image and atomically persist
its actual repository digest in `SPACEWORKS_OCI_DIGEST`, preserving unrelated `.env` bytes and secrets,
ownership and mode `0600`. The host helper requires Python 3's standard library and Docker access;
the backend gets neither Docker access nor the host socket. It validates the common backend
entrypoint, requires one distinct digest for the selected repository, and checks the image again
before persistence. Standard `docker.io`/`index.docker.io` and implicit `library` aliases are normalized;
other registries must match explicitly. Missing or ambiguous RepoDigests refuse without changing `.env`.
Docker documents [repository digests and immutable pulls](https://docs.docker.com/reference/cli/docker/image/pull/).
The [Compose startup reference](https://docs.docker.com/reference/cli/docker/compose/up/) documents the
`--pull never` policy used below.

Guided setup provisions again after its last Compose pull and refreshes trusted records before
starting with `--pull never`. Later setup restarts also forbid implicit pulls. Post-provision host
helpers likewise use [`docker run --pull=never`](https://docs.docker.com/reference/cli/docker/container/run/#set-the-pull-policy---pull);
a missing cached image refuses before startup instead of pulling another image. The updater clears an
inherited OCI override, provisions in its init child after deployment begins, and starts with
`--pull never`; the persisted environment supplies its identity. Rollback re-provisions the previous
actual backend and refreshes only trusted Compose records before startup. Failure in either step
blocks rollback startup. The previous producer proof is restored byte-for-byte, never regenerated;
forward database migrations stay in place and the pre-update database backup is retained.

For manual bundled operation, pull all required images before the final
`bash scripts/init-host-orchestration.sh`, unset inherited `SPACEWORKS_OCI_DIGEST`, then use
`scripts/spaceworks-compose.sh bundled up -d --pull never`. Do not pull or build again between final
provisioning and startup. An unavailable admitted image must fail startup instead of being repulled.

For an already initialized cloud topology, provision its explicit durable env file after all image
pulls, then refresh its existing trusted record before startup (substitute the exact backend tag and
your established paths/group; keep the existing database pointer and producer proof):

```bash
backend_image=ghcr.io/spaceworks-hq/spaceworks-backend:YOUR_RELEASE_TAG
docker pull "$backend_image"
sudo python3 -I -B scripts/provision-runtime-image.py \
  --env-file /etc/spaceworks/cloud.env --image "$backend_image"
unset SPACEWORKS_OCI_DIGEST
docker run --rm --user 0:0 --entrypoint python \
  -v "$PWD:/repo:ro" -v /etc/spaceworks:/config:ro \
  -v /var/lib/spaceworks/ops:/ops "$backend_image" \
  /repo/scripts/configure-compose-wrapper.py record-config \
  --topology cloud --static-env /config/cloud.env \
  --pointer /ops/database-pointer.env --record /ops/compose-topology.json \
  --compose-file /repo/docker-compose.cloud.yml --reader-gid "$(id -g)"
sudo scripts/spaceworks-compose.sh cloud up -d --pull never
```

The selected cloud backend image/tag must match `cloud.env`. Initial cloud environment rendering
must be completed before this sequence; provisioning changes that file's fingerprint, so the trusted
record must be refreshed afterwards. The helper refuses symlinked, hardlinked, non-private or unsafe
dotenv inputs and duplicate OCI assignments. On a persistence/fsync refusal, resolve the error and
rerun provisioning plus record refresh before startup. Never hand-fill a digest-shaped placeholder.

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

**2026-10: migration-package capability fingerprint (unreleased).** The producer capability now
includes source/data files within installed migration packages, including extracted SQL helpers and
nested helper modules; compiler caches are excluded. An upgraded image can require capability
regeneration even when numbered migrations are unchanged. Install the reviewed matching image and
host bundle through the normal initialization/update flow. Migration-byte drift continues to refuse
backup production: do not hand-edit the marker or replace its digest with a version label. No database
migration is required for this fingerprint correction.

**2026-10: actual runtime OCI identity (unreleased).** Adopt the release's host bundle through the
pinned curl installer to install `scripts/provision-runtime-image.py` and the updated setup/updater.
Published setup/update now provision `SPACEWORKS_OCI_DIGEST` automatically; existing manual bundled
hosts must rerun init after pulling, and cloud hosts must provision their `cloud.env` and refresh
trusted records using [Host configuration changes](#host-configuration-changes). Recreate application
containers with `--pull never` so they receive the provisioned environment. Source builds clear the
digest and cannot create signed FULL archives until their actual backend is published and pulled.
No database migration is required. Rollback refuses startup when the old image identity or trusted
record refresh fails, and preserves the old producer proof instead of issuing a new one.

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

**2026-10: backend signal handling (unreleased).** Base, production and cloud Compose now
`exec` Gunicorn after successful `collectstatic`, so Docker's SIGTERM reaches Gunicorn directly.
Existing hosts must rerun the [pinned curl installer](#pinned-curl-install) and choose update to adopt
the release's host bundle; an ordinary update replaces images only. Refresh the trusted topology per
[Host configuration changes](#host-configuration-changes), then recreate the backend through
`scripts/spaceworks-compose.sh bundled up -d --force-recreate backend` (use `cloud` instead of
`bundled` for cloud hosts), preserving the configured layer. This change requires no database migration.

**2026-10: security environment forwarding (unreleased).** Base, production and cloud Compose
now forward the complete existing scoped-PII and signed-client settings through their shared
application environments. Previously ignored `PII_ENCRYPTION_ENABLED=True` and
`API_CLIENT_AUTH_REQUIRED=True` values now become effective: inspect existing configuration before
restarting any process. Defaults still leave both features off and keys blank. PII activation
**requires the [staged rollout](scoped-pii-encryption.md#dual-read-rollout-sequence)**, including
independent keys, preflight, fencing, exclusive fleet replacement, backfill and readiness verification;
do not simply flip the flag or perform a rolling mixed-flag restart. Preserve the previous local
wrapping key during rotation. KMS additionally needs the optional dependency and operator IAM access
documented in that runbook; forwarding settings does not establish provider readiness.

Signed-client enforcement rejects unsigned requests on `HMAC_PROTECTED_PATH_PREFIXES` when they lack
existing accepted client authentication, including browser requests to those routes. Existing
browser/publishable-client authentication and middleware exemptions still apply. Keep
`API_CLIENT_AUTH_REQUIRED=False` unless ingress is deliberately configured for signed clients;
never distribute `HMAC_SECRET` to a browser or frontend.
After adopting the Compose changes or editing operator configuration, rebuild the trusted records
with `bash scripts/init-host-orchestration.sh` as described under
[Host configuration changes](#host-configuration-changes), before the planned restart. Bootstrap and
orchestration-ready environments remain minimal and receive no application secrets.

**2026-10: staged upload policy (unreleased).** POST and PUT uploads now target `staging/`;
accepted final objects are never client-writable. Existing installations need the release's host
runtime bundle, not only new application images: rerun the pinned curl installer and choose update
(see [Host configuration changes](#host-configuration-changes)). The bundle adds
`deploy/init-object-buckets.sh`, mounted by both bundled Compose files. After adoption, apply its
policy to existing buckets:

```bash
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled up -d --force-recreate createbuckets
```

The bootstrap honors custom bucket names, preserves private evidence and signed staging reads, and
denies anonymous public-image staging reads including historical versions. Final-file cleanup now requires
verified enabled versioning and exact version identities, plus backend `s3:GetBucketVersioning`,
`s3:ListBucketVersions` and `s3:DeleteObjectVersion` permissions. This prevents deleting a newly imported or
reattached object after a stale cleanup check. Unsupported/disabled versioning leaves bytes in place
and grants no quota credit. Use a versioned S3-compatible backend for complete production cleanup;
weak-provider upload/read compatibility does not imply equivalent deletion guarantees. A partial
cleanup failure may conservatively overcount usage until an operator reconciles it. Tenant storage
changes serialize under a dedicated advisory lock connection in addition to the source boundary;
include those pinned connections when sizing the database pool.

New machine manual, warranty and receipt presigns bind the exact resource ID. Existing attached
legacy files remain readable/deletable; an unfinished legacy-flat upload must be uploaded again for
its intended resource. A raw User/membership cascade with profile/project images is refused: clear
the images through their normal guarded paths before deleting the account or membership.

External S3-compatible storage needs the equivalent staging policy. Already-issued legacy direct-final upload URLs remain valid
until their original expiry; stop issuing them before changing releases and allow their configured
TTL to pass. Backup capture now falls back to staging only when the final object is genuinely absent;
permission, transport, version or integrity failures abort capture rather than substituting bytes.

**2026-10: production-flow audit fixes (unreleased).** Apply all migrations before starting web and
worker processes: the certificate trigger migration permits cancellation/recovery while retaining
immutable certificate snapshots. Restart workers with the web release. Pending exports now recover
after their deadline, expire download tokens at archive expiry, and retain their object locator when
byte deletion fails; a broker dispatch outage returns 503 with the job ID, so check that job before
submitting another export. Backup reconciliation respects an active producer operation lock.

Backup publication now verifies the encrypted staging object in a private, seekable temporary
file before the storage SDK uploads it. Budget an additional encrypted-archive-sized file in
the producer or reconciliation container's writable temporary storage. Memory use stays bounded;
insufficient temporary space fails publication. Default SDK checksums, size/hash verification
and create-only final-object protection remain enabled.

Integration health now includes per-room diagnostics for enabled chat channels, including disabled
rooms and legacy configuration. It exposes configuration state and safe failure reasons rather than
webhook credentials. Storage recalculation includes event-series images and activated certificate
PDFs, including revoked issued PDFs retained for accountability. API-client usage telemetry retries
detached Redis buckets after worker/database failure; it remains best-effort within its two-day Redis
retention and never substitutes for the durable audit log.

Run `recompute_storage` as a top-level management command outside any transaction (autocommit on).
It pauses writes for each selected tenant while draining existing writers, reading canonical
records/storage and committing that tenant's counter; schedule it during maintenance, especially for
large tenants or slow storage. Recovery, migration and unfinished purge states refuse reconciliation.
A storage read failure leaves the counter unchanged. If commit acknowledgement is lost, the outcome is
uncertain: rerun for a fresh scan before relying on the total.

Accepted procurement receipts and warranty documents now charge their validated final byte size
against finite managed storage limits when their metadata is attached. Repeating a successful
attachment does not charge it again. Only an actual managed debit records local provenance in the
immutable added audit event. Explicit or cascading deletion can release that debit once after
successful deletion of a nonempty accepted data-version snapshot and an unreferenced-key check.
Failed, empty or marker-only snapshots and legacy, foreign, source-prefixed or unproven events grant
no invented credit. Procurement module purge freezes proven receipt obligations in managed mode before strict
byte-first cleanup and settles them with its graph checkpoint; later cleanup retries cannot refund
again. A pending payable receipt refuses graph settlement if accounting mode or provenance changes;
a new self-host purge keeps its legacy zero-credit behavior. Whole-tenant purge deletes the Maker
and needs no additional refund.
`recompute_storage` preserves valid live unreleased proof amounts even when HEAD sees missing or
changed bytes; legacy/unproven documents retain HEAD-only reconciliation. There is no automatic
callback retry queue. Ordinary deletion failures can leave usage conservatively high; use the existing
`recompute_storage` command for operator reconciliation. Unfinished module purges retain their explicit
receipt retry and block reconciliation until resolved. Self-host/unlimited behavior is unchanged;
this is not a billing change. These document quota changes are unreleased.

Evidence expiry credits only a proven local debit for the accepted bytes. Legacy, imported or
otherwise unproven records can expire without a quota credit; reconciliation uses actual retained
objects instead of trusting a declared upload size. Retention keeps the immutable evidence metadata
and audit trail after deleting eligible object versions.

Before tenant purge, take a fresh database backup. Purge uses an explicit two-step confirmation/retry
in `/control/`. The first confirmed attempt commits irreversible purge intent and reports the fixed
retry time; it prevents reopening the tenant. A storage outage retains the tenant graph and cleanup
locators for retry. Successful graph removal creates a read-only purge receipt with the last verified
storage time. An already-admitted upload can finish after its URL expires, so retain the receipt and
use its explicit superadmin retry if late bytes remain. Retry refuses restored/current tenant IDs,
changed storage origins, active references, recovery or invalidated authority. Receipts never run
as background jobs; restored receipt authority is invalidated before readiness. Purge and receipt
cleanup require complete object-version listing/deletion support.

**0.9.0: hardware handover safeguards (unreleased).** Individually tracked tools must be repaired or
scrapped through their individual unit status actions; aggregate repair quantities cannot reconcile
their physical units. Box QR checkout supports quantity stock stored directly in that box.
Individually tracked tools require their own unit QR scans. A parent box with available stock in
nested containers requires explicit contents selection, so lending the parent cannot leave nested
hardware recorded as available. Staff can select a container separately; containers remain optional.

Public self-checkout and staff direct loans must use their respective return flows. Reviewed-request
returns no longer accept their backing requests. A public loan with previously resolved or inconsistent
stock history refuses automatic settlement to prevent another debit or credit. Investigate and
reconcile that historical ledger with verified physical stock; retrying or editing a status alone is
not a repair. Existing photos, scan records and audit history must remain intact.

Evidence compliance reports distinguish terminal byte expiry from retained metadata, including old
rolled periods. Their byte metric is recorded historical metadata, not current storage/quota usage;
the live-reference count does not prove that an upload exists. See [report semantics](evidence-reporting.md).

**0.9.0: request status, cancellation and machine alerts (unreleased).** Apply the new hardware,
encryption and notification-choice migrations before restarting web and worker processes. Staff with
request-review authority may cancel accepted requests only before handover, with a protected reason;
inconsistent reservations refuse atomically instead of being repaired. Check-in visitors retain private
status links without accounts or another roster lookup; a typed name cannot recover lost history.
Signed-in personal accounts can view their own requests without an active community membership.
Printing and generic machine Telegram alerts now default on when configured. Existing explicit off
preferences remain off; no credentials or preference rows are overwritten. Review
[notification controls](notifications-setup.md) and [check-in status access](checkin-mode.md).

**0.9.0: checked-in setup credentials (unreleased).** New guided installs using checked-in borrowing
ask for staff username and password, leave the admin email empty, and skip Google configuration.
Reusing an existing `.env` introduces no identity-setting changes. Blank-password generation and its
existing one-time display remain available. Public visitors continue to use the eligible roster
without an account or second factor; staff authentication and permissions are unchanged.
On macOS, cleanup of the retired `updates` tombstone now replaces the old assignment while
preserving other keys, comments and surviving module labels, matching Linux behavior.

**0.9.0: walk-in account conversion (unreleased).** Conversion waits until every linked makerspace
is writable, including links through inactive or revoked memberships. Credentials and claim-created
presence change together or remain unchanged. A multi-makerspace attempt from a dedicated origin
may need a fresh attempt from the central origin to preserve lock order. Native password changes
show a retry message; OIDC callbacks return the typed source-gate refusal.

Rejected claim tokens still return the generic authentication failure. Defensive cleanup of
inconsistent legacy presence waits for its actual makerspace to become writable; deferred cleanup
never restores token access. Normal claim revocation already ends matching presence atomically,
and normal presence expiry is bounded by the claim deadline.

**0.9.0: archive reads across split storage endpoints (unreleased).** Backend downloads and
maintenance archive exports now read through `AWS_S3_ENDPOINT_URL`. Browser presigning continues
to use `AWS_S3_PUBLIC_ENDPOINT_URL`. Redeploy the updated backend image for all application and
maintenance roles; updating the host bundle alone does not install this fix.

**0.9.0: module deletion and restore proofs (unreleased).** Module purges also retain a durable,
source-local receipt. Storage versions are removed before the frozen graph; provider failure keeps
that graph and its cleanup locators. Pending intents block reinstall, capture and storage recalculation.
Successful deletion settles only the original verified charge obligations. Explicit late-byte retries
are available to an active superadmin in `/control/`, grant no additional quota credit, and refuse
changed tenants, references, recovery generations or storage origins. Receipts are excluded from
portable exports and invalidated by recovery; never copy one as deletion authority. There is no force
rebind. A changed frozen graph requires a verified pre-intent recovery point or deliberate whole-tenant
purge. See [module deletion](MODULES.md#deleting-a-modules-data).

Compound captures and static artifact validation now require protocol 2 and independently frozen source
facts. Older compound protocol-1 input is refused with an upgrade message. This does not install a
sovereign compound restore coordinator: the installed host refuses compound restoration, including
protocol 2. See the [supported recovery formats](#supported-recovery-formats) below.
Lane D version-2 restores authenticate the selected
outer artifact and inner projection proof on every invocation, including resumes without API-client
reissue. They copy and verify `database.dump` into a private, invocation-owned file before effects and
recheck it immediately before restore. Budget an additional dump-sized temporary file under the
operations directory, plus full copy/hash I/O. Insufficient disk or fsync failure refuses safely.
Actual version-1 Lane D artifacts remain explicitly legacy-unverified and cannot reissue API clients.

The supervised restore tail retains rollback object rows, bytes and their quota instead of invoking a
second cleanup process while holding the operation lock. Expiry or explicit standalone cleanup
requires a confirmed completed restore and normal recovery state under the same source/operation
fences. Failed and aborted restores retain their copies and quota; expiry alone cannot prove recovery
completed. Never edit a restore stage to force deletion.

Expiry traversal records a private, non-authoritative cursor at
`BACKUP_OPS_DIR/rollback-cleanup-progress.json`. Keep it in the runtime-owned shared work directory,
not beside the separately mounted root-owned operation lock. Retained or frozen rows do not starve later
eligible cleanup. A `rollback_cleanup_progress_unconfirmed` diagnostic means some individual cleanup
may already have completed: preserve the actual cleaned/skipped counts, repair local permissions or
capacity, and retry. Settled rows prevent duplicate quota credit. Refresh the installed host bundle with
this release so scripts and application agree; retained rollback usage is expected.

Browser session recovery now requires a per-tab intended-identity pin. Existing sessions without one,
and genuinely new tabs without an inherited pin, require an explicit sign-in once. The pin contains
identity/context identifiers, never an access or refresh token. A late refresh cookie belonging to a
previous account cannot select that account after reload. Browsers with blocked session storage may
operate in memory only after an older pin is safely invalidated; an unconfirmed durable sign-out is
reported truthfully. This does not promise independent persistent accounts in different tabs sharing
one refresh-cookie jar.

A central staff frontend must be declared in `PLATFORM_STAFF_ORIGINS`. A verified makerspace custom
domain intentionally scopes every actor, including superadmins, to that space. For a shared console,
configure its exact HTTPS origin as a platform staff origin and review any conflicting dedicated-domain
assignment. Do not bypass tenant-origin checks to make the chooser work.

Email quota refusals are terminal skipped deliveries (`daily_email_limit_reached`), including legacy
failed rows with that refusal. Waiting until the next day does not retry that old dispatch; a new
logical notification needs its own quota reservation. Queued chat deliveries recheck their current
destination and scope before sending. Provider transport retries still reuse an already reserved
email slot.

Online payment conversion now validates exact provider minor units before creating or starting a
charge. `backend/apps/payments/currency_rules.py` holds the complete published provider catalogues:
[Stripe charge currencies](https://docs.stripe.com/currencies), including its
[three-decimal currencies](https://support.stripe.com/questions/which-payments-methods-and-products-are-available-in-the-uae),
and [Razorpay currencies](https://razorpay.com/docs/payments/international-payments/).
The ledger retains two major-unit decimal places, so exact values such as KWD 1.23 convert to 1230
minor units; KWD 1.234 is refused. Three-decimal fees round HALF_UP to a quantum of 10 minor units
and are capped at the charge (a 5000-bps fee on KWD 1.23 is 620). That quantum is local ledger
policy, not a universal Stripe API restriction; Razorpay separately requires a trailing zero for
[three-decimal payment-link amounts](https://razorpay.com/docs/api/payments/payment-links/create-standard/).
Unsupported currencies or fractions are refused; offline recording is unchanged. Existing pending
charges with an invalid legacy fee snapshot need operator reconciliation rather than a new checkout
link or a rewritten financial snapshot. Provider account/country currency availability still applies:
the published catalogues do not guarantee that every account can charge every listed currency.

**2026-10: public machine service by type.** No migration or environment change. Public clients can
choose a machine type and submit an unassigned job; staff choose its machine later. Enable public
inventory, `machines` and `machine_service`, then explicitly publish at least one active machine
of the type in idle/running/reserved state. Printers also require `printing`; this gate now applies
to legacy machine-id submissions too. Adding a private machine does not publish it. The first
authorized real upload/submission POST reuses a same-type active queue (name/id order), or creates
an audited `Public Requests - type <id>` default if no queue exists; catalog GET never creates one.
An inactive-only type or a conflicting default name returns 409: staff must deliberately configure
or reactivate a queue. The existing scoped staff printer setup action still enables `Public Requests`.
Uploads return a queue pin; submissions with files must retain that exact active queue. Public printer
material choices now exclude unbound legacy pools and private/foreign/inactive-machine pools;
use an explicitly public compatible printer-type pool or one on a published eligible printer.
Existing printer URLs remain available. New catalog/upload/token routes require explicit API-client
`public:read`/`public:write` grants and are not added to the frozen `legacy:v1` capability.

**2026-10 (0.8.5): default currency is INR.** The payment-settings default moved from `usd` to
`inr`, and the migration flips every makerspace still set to `usd` to `inr` (any other currency is
left alone; payments already raised keep their own currency). A makerspace that really charges in
US dollars must set it back under Settings → Payments → Currency after upgrading.

**2026-10 (0.8.5): machine-type settings per makerspace.** No manual step. Built-in machine
types are no longer fixed: a Space Manager can set a built-in type's metering unit, whether it
needs a booking, and whether it uses consumables for their own makerspace (Machines → Machine
types; "Use built-in settings" undoes it). The migration gives CNC Mill, PCB Mill and Other the
minutes unit they never had (they were priced by weight on the server and by count in the console,
so a priced one refused every manual-usage log), and resets those three types' "free below" from
the old 20 g default to 0. A makerspace that was already running one of them by weight (an active
consumable pool or a per-unit price) keeps weight through a makerspace override, and keeps its
threshold, so its pools and rates mean what they did; switch it to minutes in the type's settings
when you are ready. Consumable
pools tied to a type now always take that type's unit.

**2026-10 (0.8.5): item codes.** No manual step. The migration gives every makerspace a
platform-unique item-code prefix (initials of its name, e.g. "Tinkerspace Kochi" → `TK`), codes the
old default categories (Microcontrollers → `MCU`, Sensors → `SNS`, Actuators → `ACT`, Cables → `CBL`,
Accessories → `MOD`), adds the missing standard categories and gives every categorised item a letter.
Nothing is renamed or deleted; the old "SBCs" and "Microprocessors" categories stay without a code for
you to merge into `MCU`. Check or change the prefix under Settings → General → Item codes. Details:
[docs/item-codes.md](item-codes.md).

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
and `scripts/spaceworks-compose.sh bundled up -d --pull never`. Unset an inherited
`SPACEWORKS_OCI_DIGEST` before launching. For PII activation, use the fenced fleet-switch
procedure below instead of an ordinary restart.

**Secrets that must be set, and backed up, in production:**

| Variable | Generated | Without it |
|---|---|---|
| `SECRET_KEY` | yes (50 chars) | The backend does not start. A value under 32 characters, with fewer than 5 distinct characters, or containing a placeholder word (`replace-with`, `change-me`, `changeme`, `insecure`) fails system check `accounts.E001` when `DEBUG=False`, so `migrate` and every update refuse |
| `API_CLIENT_ENC_KEY` | yes (Fernet) | Saving a Telegram token, SMTP password or chat webhook returns **503** (`secret_storage_unavailable`); API-client, payment and platform-email secrets fail to save. Changing it makes every stored secret unreadable |
| `AUDIT_MAC_MASTER_KEY` | yes (Fernet) | Warning `audit.W001`; audit rows are not sealed with a per-scope MAC. An invalid value is error `audit.E001` |
| `BACKUP_AGE_RECIPIENT`, `BACKUP_ARCHIVE_SIGNING_PRIVATE_KEY`, `BACKUP_ARCHIVE_VERIFY_PUBLIC_KEY` | yes (the age identity lives in `/var/lib/spaceworks/ops/work/age-identity.txt`) | Backups and tenant exports refuse to run. Without the age identity a backup cannot be decrypted |
| `POSTGRES_PASSWORD`, `POSTGRES_APP_PASSWORD`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | yes | The stack does not start |

Keep an offline copy of `.env` and the age identity file. Supported signed FULL disaster recovery can
install the archived continuity keys (`SECRET_KEY`, `API_CLIENT_ENC_KEY`, `AUDIT_MAC_MASTER_KEY`, …).
Non-reset rollback instead requires the archive to match the installed keys.

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
| `PII_ENCRYPTION_ENABLED` | no (default `False`) | Opt-in scoped PII encryption; requires the complete [staged rollout](scoped-pii-encryption.md#dual-read-rollout-sequence) |
| `PII_ENCRYPTION_DUAL_READ` | no (default `True`) | Allows legacy plaintext reads during the bounded rollout window |
| `PII_KEY_BROKER` | no (default `local`) | Existing `local` or `aws_kms` wrapping broker; KMS requires `backend/requirements-kms.txt` and operator IAM encrypt/decrypt access |
| `PII_MASTER_KEY` | for enabled local broker (default empty) | Independent wrapping secret; back up separately from the search, API-client and audit keys |
| `PII_MASTER_KEY_PREVIOUS` | during local wrapping-key rotation (default empty) | Retained old wrapping key until rewrap and verification finish; see the runbook's rotation procedure |
| `PII_SEARCH_HASH_KEY` | for enabled encryption (default empty) | Independent search secret bound to the persisted search generation; preserve for recovery |
| `PII_DEK_CACHE_TTL_SECONDS` | no (default `300`) | In-process DEK cache lifetime in seconds |
| `PII_AWS_KMS_KEY_ID` | for `aws_kms` broker (default empty) | KMS key or alias; local master-key settings are unused with this broker |
| `PII_AWS_KMS_REGION`, `PII_AWS_KMS_ENDPOINT_URL` | no (both default empty) | Optional KMS region and approved compatible endpoint |
| `API_CLIENT_AUTH_REQUIRED` | no (default `False`) | Rejects unsigned requests lacking existing accepted client authentication on configured protected prefixes; existing middleware exemptions apply. Leave off unless signed-client ingress is intentional; never give browser clients the HMAC secret |
| `HMAC_CLIENT_ID`, `HMAC_SECRET` | for legacy signed-client configuration (both default empty) | Server-side legacy client credentials, separate from `API_CLIENT_ENC_KEY` |
| `HMAC_MAX_CLOCK_SKEW_SECONDS` | no (default `300`) | Allowed signed-request timestamp skew in seconds |
| `APICLIENT_REQUIRE_NONCE` | no (default `False`) | Requires a nonce on signed-client requests |
| `HMAC_PROTECTED_PATH_PREFIXES` | no (default `/api/public/,/api/v1/public/`) | Comma-separated protected route prefixes; widening requires registered routes. See [API client protocol](api-client-protocol.md) |
| `TOMBSTONED_APPS` | no | App labels whose runtime surfaces are removed deployment-wide; get the line from `manage.py suggest_tombstones` |
| `GITHUB_API_TOKEN` | no | Enables the GitHub contribution count on maker profiles. Not forwarded by the bundled Compose files yet |
| `TELEGRAM_BOT_TOKEN` | no | Deployment-wide fallback bot for makerspaces without their own token. Not forwarded by `docker-compose.prod.yml`; set tokens in the console ([notifications-setup.md](notifications-setup.md)) |
| `TELEGRAM_WEBHOOK_SECRET` | no | Authenticates Telegram's webhook calls, which are acknowledged and ignored (alerts are outbound only). Not forwarded by `docker-compose.prod.yml` |
| `SPACEWORKS_REPOSITORY` | no (default `SpaceWorks-HQ/SpaceWorks`) | GitHub `owner/repo` whose latest release the host follows; fresh installs derive image names from its lowercased owner |
| `MAKERSPACE_BACKEND_IMAGE` | no (default `ghcr.io/spaceworks-hq/spaceworks-backend`) | Backend image name without a tag; set explicitly for a fork on an existing host |
| `MAKERSPACE_FRONTEND_IMAGE` | no (default `ghcr.io/spaceworks-hq/spaceworks-frontend`) | Frontend image name without a tag; keep it paired with the backend image |
| `SPACEWORKS_OCI_DIGEST` | for signed FULL backup | Actual backend repository digest, exactly `sha256:` plus 64 lowercase hex digits. Host setup/init/update provision it after pulling; manual/cloud hosts use the host helper and refresh trusted records before startup. Source builds clear it; never substitute config Id or tag. |
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

The PII and signed-client variables above reach every consumer of the shared application environment
in base, production and cloud Compose, including migration and existing management-command consumers.
Compose `.env` is interpolation input; it does not implicitly populate containers. Before restarting,
review any previously ignored true flags. PII keys are operator-provisioned, not installer-generated;
follow [scoped-pii-encryption.md](scoped-pii-encryption.md) for independent keys, readiness, backfill,
rotation and rollback. Retain the previous wrapping key for the documented local rotation window.

> **Supabase free-tier deployment** (managed Postgres + Storage, env-toggled, demo/pilot scope):
> see **[supabase-deployment.md](supabase-deployment.md)** for the full runbook. All five vars
> above default to the self-hosted behavior, so this Compose stack is unaffected unless you set them.

## Object Storage

Production Compose includes MinIO because the backend stores evidence photos and 3D-print files in
S3-compatible object storage by default. The backend talks to MinIO at `http://minio:9000`; browsers
use `AWS_S3_PUBLIC_ENDPOINT_URL` in presigned upload/download URLs, so that value must be reachable
from staff/requester browsers.

The bucket bootstrap passes `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` as literal
arguments to `mc alias set`, including credentials beginning with a hyphen (`-`).

Public catalog images use a separate `PUBLIC_IMAGE_BUCKET` that is anonymous-readable by design.
The bundled Compose bootstrap creates it and permits anonymous reads of final images while denying
anonymous reads of `staging/` (including object versions). Signed backend staging reads remain
available. The same upload CORS policy applies. Keep evidence and print files in the private `AWS_STORAGE_BUCKET_NAME`; only item photos and
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

### Supported recovery formats

FULL capture requires the host-provisioned `SPACEWORKS_OCI_DIGEST`. A missing or malformed value raises
a typed backup build refusal with a stable reason and operator guidance, after FULL custody selection
but before source identity queries, database dump or object capture. The admitted value is frozen for
the signed archive; later environment changes cannot replace it. Capture never downgrades to another
format. Makerspace and non-FULL capture retain their existing behavior.

The installed `scripts/restore.sh` admits the following complete deployment archives only after its
protected-host, archive identity and readback checks. Passing static artifact validation alone does
not establish that the installed host can restore an archive.

| Archive | Installed host support |
| --- | --- |
| Signed FULL (`spaceworks-deployment-full-v1`) | Supported route for registered recovery and externally pinned cross-host import. Signature trust, complete archive facts and target compatibility must pass before effects. |
| Historical `spaceworks-phase5a-v1`, `v2` or `v3` without a protocol declaration | Registered same-host recovery only, bound to its stored encrypted artifact hash. This is not a cross-host import route. |
| Sovereign compound, including protocol 2 | Refused: no sovereign compound restore coordinator is installed. Protocol-2 capture/static validation does not make host restoration available. |
| Lane D tenant dump | A separate tenant-migration artifact, not a deployment archive for this host restore route. |

Do not change an archive's format fields or route an unsupported compound archive through FULL
admission. No conversion procedure is provided here. Complete an isolated end-to-end restore drill
with the exact release, installed host bundle and deployment before relying on recovery.
The earlier host wrapper also refused compound execution; protocol validation and coordinator library
code did not supply an installed launcher. This limitation is not resolved by refreshing host files alone.

### Manual database and object-volume copies

The following commands create separate database and object-volume copies; they do not produce a
signed FULL or compound archive and do not exercise the supervised restore/quarantine/resume path.

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

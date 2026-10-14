# Deploy tinkerhub/SpaceWorks on AWS EC2

This runbook installs the `tinkerhub/SpaceWorks` fork on one Ubuntu server and enables automatic
redeploys from `main`. Keep the [Self-Hosting Guide](self-hosting.md) for the full environment and
recovery reference, and [Setup for Makerspaces](setup-for-makerspaces.md) for the guided setup.
Run the server commands below in your SSH session unless stated otherwise.

## What you get

The deployment chain is:

```text
Owner pushes main -> CI (tests + pip-audit) -> release images and GitHub Release
  -> successful Continuous Release -> self-hosted Actions runner -> host updater
  -> database backup -> pull immutable images
  -> migrate and restart -> readiness check -> record installed version
                                            -> on failure: application rollback
```

GitHub CI runs only `pip-audit`: pull requests run `security-audit.yml` directly, and main pushes run
it through `ci.yml`. The backend and frontend test suites run locally before pushing, not in CI.

`release.yml` waits for CI's `workflow_run` completion on `main` and proceeds only if its conclusion
is `success` and its original event is `push`. A red main produces no release. Manual dispatch is
also refused unless the ref is `main` and successful push CI exists for that exact SHA. Both images
must finish, and the commit must still be the main head, before the release becomes latest.

Expect about a minute for CI, plus image build/publish time and time to back up and deploy.
Runner queues, image downloads and database size add time. `deploy.yml` starts only after release
promotion finishes, and the host updater independently checks GitHub for the release.

## One-time GitHub setup

1. Enable Actions in `tinkerhub/SpaceWorks`, and keep `main` as the default branch: `workflow_run`
   uses the release workflow from the default branch. Ensure these updated workflows are on `main`.
2. Check organization/repository Actions policy allows the workflow's `GITHUB_TOKEN` to write
   packages. The release workflow requests `packages: write` and `contents: write`; organization
   policy and existing package access must permit publication. See GitHub's
   [publishing guide](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images).
3. After the first successful main CI and release, open **tinkerhub → Packages**, then change both
   **spaceworks-backend** and **spaceworks-frontend** to **Public** in each package's settings.
   Their image names are `ghcr.io/tinkerhub/spaceworks-backend` and
   `ghcr.io/tinkerhub/spaceworks-frontend`. The workflow lowercases the repository owner.

Public packages allow anonymous pulls. If keeping packages private, the host must first run
`docker login ghcr.io -u YOUR_GITHUB_USERNAME`, using a token with package read access as the password.
Authenticate as the same Linux user that runs setup and the updater, so unattended pulls find the
credentials. See GitHub's [Container registry authentication guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
The curl installer still needs a published latest release before it can install anything.

## Create the instance

In the AWS EC2 console, launch **Ubuntu Server 24.04 LTS**, **t3.medium minimum** (2 vCPU, 4 GB RAM),
with a **30 GB gp3** root disk. Choose a key pair and keep the private key on your computer.
Use a public subnet with internet access, then allocate and associate an **Elastic IP** so DNS and
your browser-facing storage address remain stable.

Configure the security group's inbound TCP rules:

| Port | Source | Use |
|---|---|---|
| 22 | Your current public IP only (`/32`) | SSH administration |
| 80 | Anywhere (`0.0.0.0/0`; `::/0` if using IPv6) | HTTP and certificate validation |
| 443 | Anywhere (`0.0.0.0/0`; `::/0` if using IPv6) | HTTPS |
| 9000 | Browser clients; anywhere if the HTTP site is public | Plain-HTTP setups only: browsers upload evidence directly to MinIO here |

With the TLS overlay, close port 9000: Caddy serves storage on HTTPS port 443 instead.
Keep Postgres, Redis, backend ports and MinIO's console port 9001 private. Ensure outbound traffic
can reach GitHub/GHCR, the check-in API and certificate services. AWS's
[security group examples](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-rules-reference.html)
explain the SSH and web rules.

## Install

From your computer, replace the key path and IP:

```bash
ssh -i /path/to/your-key.pem ubuntu@YOUR_ELASTIC_IP
```

In that SSH session:

```bash
curl -fsSL https://raw.githubusercontent.com/tinkerhub/SpaceWorks/main/install.sh | SPACEWORKS_REPOSITORY=tinkerhub/SpaceWorks bash
```

The installer checks the host, installs missing supported dependencies, downloads the fork's latest
tagged archive into `/opt/spaceworks`, and pins the matching images. On a fresh install it forwards
the repository and derived backend/frontend image names to `setup.sh`, which saves them in
`.env`. Keep the setup output and generated admin password safely.

For the prompts:

- **Web address:** your Elastic IP initially, or the app hostname already pointing to it; omit
  `http://` and any path. Setup starts with plain HTTP; configure HTTPS below.
- **Makerspace name:** the name shown to your users.
- **Who can submit borrow requests?:** choose **4** for the check-in roster mode. Supply the full
  check-in API URL, your upstream **space ID**, and the required purpose (default
  **Working on a project**). The URL must use HTTP/HTTPS with a host and no spaces; the space ID must
  be a positive integer up to `2147483647`. URL/purpose values must be safe to save in `.env`.
  Invalid input falls back to requiring an account; read warnings before continuing.
- **Admin username/email/password:** choose credentials or save the generated password. Google
  sign-in and Stripe are optional; leave them blank if you are not configuring them.
- **Module selection:** review the check-in defaults described below.
- **Enable automatic production updates from main?:** answer **Y** for runner setup instructions.
  Setup prints them after the stack starts; it does not generate or save a deployment token.
  **No** skips those instructions; the runner installer and updater retire old release polling jobs.

Option 4 writes `CHECKIN_API_URL` and `CHECKIN_REQUIRED_PURPOSE` to `.env`, starts the makerspace with
the `checkin` module profile, then sets `checked_in` request mode and the upstream space ID in the
database. The default timeout is `CHECKIN_TIMEOUT=5.0` seconds and lookup cache lifetime is
`CHECKIN_CACHE_SECONDS=30` seconds. If applying the mode fails, setup retains account-required access.

**Trust boundary:** the roster is public. A match proves presence eligibility, not identity; anyone
can enter another checked-in person's name. Staff still accept every borrow request and record
hand-over evidence. Read [Check-in gated requests](INVARIANTS.md#check-in-gated-requests) before
choosing this policy.

Reconnect SSH if Docker group membership was added. Register the runner as the current, non-root
install owner in `/opt/spaceworks`; Linux x64/arm64, running systemd and sudo are required.
The installer verifies the pinned Actions runner v2.338.0 archive's SHA-256 before extracting it into
`$HOME/spaceworks-actions-runner`. Its systemd service runs as the install owner.

**Public repository warning:** `tinkerhub/SpaceWorks` is public. A fork PR can add a workflow targeting
the repository-level production runner and execute it once a maintainer approves the run. Review all
workflow changes before approving fork PR runs; approval alone does not isolate the runner. The stronger
boundary is an organization runner group restricted to `deploy.yml@main`, which needs an org administrator.

Configure these two settings in **tinkerhub/SpaceWorks**:

1. **Settings → Actions → General → Fork pull request workflows:** require approval for **all outside
   collaborators** (`all_external_contributors`). When `gh` is available, the installer checks this policy
   and refuses an unsafe result unless `SPACEWORKS_RUNNER_ACCEPT_RISK=1`; if it cannot check, verify it
   yourself before proceeding.
2. **Settings → Secrets and variables → Actions → Variables:** set `SPACEWORKS_DEPLOY_RUNNER=true`, or
   run `gh variable set SPACEWORKS_DEPLOY_RUNNER --body true --repo tinkerhub/SpaceWorks` with authenticated `gh`.

Then install the runner on the server, as the install owner. Any of these runs the same installer,
which asks for a one-time registration token at a hidden prompt and prints where to get one
(**Settings → Actions → Runners → New self-hosted runner**, or the `registration-token` API):

- answer **Y** to "Enable automatic production updates from main?" during guided setup;
- rerun the curl installer on an existing host and choose **Set up automatic deploys (GitHub runner)**;
- or run it directly:

```bash
bash scripts/install-deploy-runner.sh
```

For unattended use, export `RUNNER_TOKEN` instead (for example
`RUNNER_TOKEN="$(gh api -X POST repos/tinkerhub/SpaceWorks/actions/runners/registration-token --jq .token)"`).
The token reaches runner configuration only through `ACTIONS_RUNNER_INPUT_TOKEN`, never argv, files or
output. The runner's `.env` supplies `SPACEWORKS_INSTALL_DIR`; the workflow does not choose the path.
`deploy.yml` never checks out or runs repository code: it runs installed `update.sh --no-module-changes`
after successful Continuous Release on `main`, or manual dispatch on `main`, and waits for the update lock.
Confirm the runner is **Idle** in GitHub's runner settings. Rerun the installer without a token to repair
the same-repository configured runner; it refreshes the path and restarts without extraction or registration.

## Enabling the modules and Telegram

Option 4 uses the `checkin` profile and forces on `reports`, `telegram`, `guest_handover`, `machines`,
`machine_service`, `printing` and `maintenance` in setup's module selection, with `membership` off.
The request workflow and staff ledger are core. Review the final module selection; enabling membership
conflicts with account-less check-in requests and prevents the mode from being applied.

Enabling Telegram does not configure its credentials. Log into the React staff console at `/admin`,
select this makerspace and, as a Super Admin, open **API access → Integration settings**. Enter the
**Telegram bot token** and **Telegram group chat ID**, save, then use **Send Telegram test alert**.
Add the bot to that group first. To configure additional destinations, open
**Settings → Notification channels → Rooms → Add a room**, choose Telegram, and enter its
**Telegram chat ID**. Rooms share this makerspace's bot token. Telegram sends alerts; request
accept/reject decisions remain in the staff console.

## HTTPS with a domain

Create DNS **A** records for `inventory.example.org` and `files.inventory.example.org`, both pointing
to the Elastic IP. Replace those example hostnames with yours. Wait until both resolve correctly.
Edit `/opt/spaceworks/.env`, replacing existing entries for these keys rather than adding duplicates:

```env
ALLOWED_HOSTS=inventory.example.org,localhost,127.0.0.1,backend
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

Apply the change with the TLS layer selected before rebuilding configuration records:

```bash
cd /opt/spaceworks
printf '%s\n' tls > .spaceworks-layer
bash scripts/init-host-orchestration.sh
scripts/spaceworks-compose.sh bundled up -d
```

Any `.env` edit requires rerunning `init-host-orchestration.sh`: it rebuilds trusted configuration
records, and the Compose wrapper refuses configuration drift. It resolves the backend image from
shell → `.env` → upstream default and its tag from shell → `.env` → `.spaceworks-version` → `latest`,
matching the wrapper. The TLS overlay forces secure cookies and makes MinIO reachable through the
`files.` HTTPS hostname. The wrapper reads `.spaceworks-layer`, so unattended updates and rollback
retain the TLS topology. Close the security group's 9000 rule and follow the
[HTTPS reference](self-hosting.md#https--security-hardening)
for further details.

## Verifying a deploy

In GitHub Actions, confirm **CI** succeeded for the pushed main SHA and **Continuous Release** finished.
Inspect the **Production Deploy** job log, and on the server compare
`.spaceworks-version` with the latest GitHub release tag (the marker omits its leading `v`).
Run `bash scripts/update.sh` for an immediate update when the installed version differs from the latest
release; add `--force` to reinstall it. Update controls and results are managed on the host.

```bash
curl -fsS https://inventory.example.org/api/v1/health/readiness/
```

Use `http://YOUR_ELASTIC_IP/api/v1/health/readiness/` before HTTPS. Also verify staff login and an
evidence upload in the browser; readiness alone does not check browser storage URLs or CORS.
For an immediate image-only update on TLS, run
`SPACEWORKS_COMPOSE_LAYER=tls bash scripts/update.sh --force --no-module-changes`.

## Adopting this on an existing host

Fresh installs now pull `pgsty/silo` + `pgsty/mc`. Before an existing host adopts the new
`docker-compose.prod.yml`, back up `minio_data`, then rerun `bash scripts/init-host-orchestration.sh`
after installing it. See [Object storage images](self-hosting.md#object-storage-images) for image
overrides and migration steps.

To adopt the runner tooling on an existing curl install, rerun the install command and choose
**Update** or **Update, then change modules**. It downloads the pinned release into staging and uses
that release's updater to back up the database before adopting its host scripts, Compose and proxy
files. It preserves private `.env`, version/layer markers, backups, volumes and host orchestration state.
The installer follows the repository in the installed `.env`; direct `update.sh` calls may override it. Ordinary runner updates
replace images; rerun the installer when a release changes host tooling. No Git checkout is needed.

Replace/add these keys in the existing `.env`:

```env
SPACEWORKS_REPOSITORY=tinkerhub/SpaceWorks
MAKERSPACE_BACKEND_IMAGE=ghcr.io/tinkerhub/spaceworks-backend
MAKERSPACE_FRONTEND_IMAGE=ghcr.io/tinkerhub/spaceworks-frontend
```

Direct updater calls resolve the repository from shell → `.env` → `SpaceWorks-HQ/SpaceWorks`. Clear
old exported overrides so `.env` wins. On an existing host, selecting the repository does not derive
new image names; set both explicitly. A static `MAKERSPACE_IMAGE_TAG` also overrides the version
marker for ordinary Compose commands; remove a stale pin if you want the marker to select releases.
When switching from upstream to a fork, first confirm the installed marker's tag exists in the fork's
image packages too. If it does not, use a valid fork release tag for a manual deployment before
enabling its updater; the new image names alone cannot make an upstream-only tag pullable.
For TLS, save `tls` in `.spaceworks-layer` before rerunning
`bash scripts/init-host-orchestration.sh` and recreating the stack through the Compose wrapper.
Register the runner and configure the two GitHub settings as described above.

Existing setup does not ask the first-run check-in questions again. To adopt that mode, set the
check-in URL/purpose in `.env`, rerun orchestration initialization, recreate the stack using its
correct layer, enable the required modules and disable membership through the module selector, then run:

```bash
SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled run --rm --no-deps -T backend --role management \
  python manage.py set_request_access --makerspace YOUR_SLUG --mode checked_in --checkin-space-id N
```

Replace `YOUR_SLUG` and `N`; omit the TLS prefix on HTTP hosts. This command selects the request
policy and upstream space ID; setting the URL alone does not enable the policy.

## Rolling back

If migration, replacement or readiness fails after deployment starts, the updater tries the previous
retained application release and checks readiness again. It keeps the database backup, does not advance
the version marker, and runner-triggered runs record the result in the Actions job log. Database migrations
are not reversed. The release workflow retains the current and immediately previous builds for this purpose.

For a deliberate manual rollback, set the repository variable `SPACEWORKS_DEPLOY_RUNNER=false` and
wait for any running deploy job to finish, then identify the previous image tag and follow [manual deployment and recovery](self-hosting.md#automatic-and-manual-upgrades).
Set `MAKERSPACE_IMAGE_TAG` to that tag in `.env`, rerun `bash scripts/init-host-orchestration.sh`, and
pull/start through the wrapper with the same TLS prefix if applicable. Verify readiness before
recording the restored version. After readiness succeeds, replace `PREVIOUS_TAG` below with the
same immutable tag (without a leading `v`):

```bash
printf '%s\n' 'PREVIOUS_TAG' > .spaceworks-version
```

Do not assume old application code can run against incompatible new migrations; if it cannot, restore
the database recovery point using the documented restore procedure.

## Backups

The updater writes compressed pre-update PostgreSQL dumps to `backups/` and retains them for 14 days.
They contain database records and photo metadata, not object bytes. Back up Docker's **minio_data**
volume separately for evidence, images and print files; see the [backup instructions](self-hosting.md#backups).
Keep an encrypted/offline copy of **.env**, especially **API_CLIENT_ENC_KEY**: losing it makes stored
Telegram/SMTP/API-client secrets unreadable. Preserve the host orchestration state and backup recovery
keys as part of host recovery planning.

Keep copies off the instance. Schedule EBS snapshots of the volumes holding Docker data and host
state, alongside application/database backups; use a quiesced or coordinated snapshot for consistent
recovery. Test recovery before relying on snapshots. See AWS's
[EBS snapshot guide](https://docs.aws.amazon.com/ebs/latest/userguide/ebs-creating-snapshot.html).

## Merging and publishing

The owner reviews and merges `dev` into `main`, then pushes `main` to this fork. Nothing in this guide
merges or pushes for you. That push starts CI; only its successful completion can publish the release
that the EC2 host subsequently installs.

# Deploy tinkerhub/SpaceWorks on AWS EC2

This runbook installs the `tinkerhub/SpaceWorks` fork on one Ubuntu server and enables automatic
redeploys from `main`. Keep the [Self-Hosting Guide](self-hosting.md) for the full environment and
recovery reference, and [Setup for Makerspaces](setup-for-makerspaces.md) for the guided setup.
Run the server commands below in your SSH session unless stated otherwise.

## What you get

The deployment chain is:

```text
Owner pushes main -> CI (tests + pip-audit) -> release images and GitHub Release
  -> host polls latest release -> database backup -> pull immutable images
  -> migrate and restart -> readiness check -> record installed version
                                            -> on failure: application rollback
```

CI runs on `dev` and `main` pushes. The backend suite takes about 60 minutes and has a 90-minute
timeout; the former 45-minute limit cancelled it. Main pushes have a separate concurrency group,
so a PR cannot cancel their release-gating CI. `security-audit.yml` is callable by CI, which includes
`pip-audit` on pushes.

`release.yml` waits for CI's `workflow_run` completion on `main` and proceeds only if its conclusion
is `success` and its original event is `push`. A red main produces no release. Manual dispatch is
also refused unless the ref is `main` and successful push CI exists for that exact SHA. Both images
must finish, and the commit must still be the main head, before the release becomes latest.

With the five-minute schedule below, expect roughly an hour for CI, plus image build/publish time,
up to five minutes until the next host poll, and time to back up and deploy. This is an estimate;
runner queues, image downloads and database size add time. The host polls GitHub; GitHub does not SSH
into EC2. Polling uses the server's cron timezone.

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
curl -fsSL https://raw.githubusercontent.com/tinkerhub/SpaceWorks/main/install.sh | SPACEWORKS_REPOSITORY=tinkerhub/SpaceWorks SPACEWORKS_UPDATE_SCHEDULE='*/5 * * * *' bash
```

The installer checks the host, installs missing supported dependencies, downloads the fork's latest
tagged archive into `/opt/spaceworks`, and pins the matching images. On a fresh install it forwards
the repository, derived backend/frontend image names and schedule to `setup.sh`, which saves them in
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
- **Enable automatic production updates from main?:** answer **Y**.

Option 4 writes `CHECKIN_API_URL` and `CHECKIN_REQUIRED_PURPOSE` to `.env`, starts the makerspace with
the `checkin` module profile, then sets `checked_in` request mode and the upstream space ID in the
database. The default timeout is `CHECKIN_TIMEOUT=5.0` seconds and lookup cache lifetime is
`CHECKIN_CACHE_SECONDS=30` seconds. If applying the mode fails, setup retains account-required access.

**Trust boundary:** the roster is public. A match proves presence eligibility, not identity; anyone
can enter another checked-in person's name. Staff still accept every borrow request and record
hand-over evidence. Read [Check-in gated requests](INVARIANTS.md#check-in-gated-requests) before
choosing this policy.

Reconnect SSH after installation if Docker group membership was added, then confirm the scheduler:

```bash
cd /opt/spaceworks
sudo systemctl enable --now cron
crontab -l
```

Expect a `*/5 * * * *` job calling `scripts/update.sh`. If installation reported a scheduling failure,
run `bash scripts/install-auto-update.sh` from this directory and check again. The default without an
override is `0 3 * * 0` (Sunday 03:00). The scheduler installer reads shell → `.env` → default and
strictly validates five cron fields, rejecting `%`, CR/LF and out-of-range values.

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

Apply the change and reinstall the updater **with the TLS layer on both commands**:

```bash
cd /opt/spaceworks
bash scripts/init-host-orchestration.sh
SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled up -d
SPACEWORKS_COMPOSE_LAYER=tls bash scripts/install-auto-update.sh
```

Any `.env` edit requires rerunning `init-host-orchestration.sh`: it rebuilds trusted configuration
records, and the Compose wrapper refuses configuration drift. It resolves the backend image from
shell → `.env` → upstream default and its tag from shell → `.env` → `.spaceworks-version` → `latest`,
matching the wrapper. The TLS overlay forces secure cookies and makes MinIO reachable through the
`files.` HTTPS hostname. The updater's installed cron command records the layer; omitting the TLS
prefix when reinstalling it leaves unattended updates using plain HTTP. Check `crontab -l`, close
the security group's 9000 rule, and follow the [HTTPS reference](self-hosting.md#https--security-hardening)
for further details.

## Verifying a deploy

In GitHub Actions, confirm **CI** succeeded for the pushed main SHA and **Continuous Release** finished.
On the server, inspect `backups/auto-update.log` with `tail -n 100 backups/auto-update.log` and compare
`.spaceworks-version` with the latest GitHub release tag (the marker omits its leading `v`).
As Super Admin, open **Platform settings → Software updates** to see installed/available versions,
automatic installation state and update results. **Update now** queues work for the next host poll.

```bash
curl -fsS https://inventory.example.org/api/v1/health/readiness/
```

Use `http://YOUR_ELASTIC_IP/api/v1/health/readiness/` before HTTPS. Also verify staff login and an
evidence upload in the browser; readiness alone does not check browser storage URLs or CORS.
For an immediate image-only update on TLS, run
`SPACEWORKS_COMPOSE_LAYER=tls bash scripts/update.sh --force --no-module-changes`.

## Adopting this on an existing host

`scripts/update.sh` replaces application images only; it does not download new host scripts,
Compose files or Caddyfiles. Rerunning the curl installer on an existing install invokes its local
updater, so it cannot repair stale host files. Its shell `SPACEWORKS_REPOSITORY` override is ignored
on that path: the existing `.env` decides which fork it follows.

Back up first. Download the matching release's source archive to a separate staging directory and
copy the changed host files into the installation: `install.sh`, `setup.sh`, `scripts/update.sh`,
`scripts/install-auto-update.sh`, `scripts/init-host-orchestration.sh`, plus the new
`scripts/env-file.sh`, `scripts/host-image.sh` and `scripts/request-access-selection.sh`.
Alternatively, re-extract the release archive into staging and install its host bundle after reviewing
differences. Preserve `.env`, `.spaceworks-version`, backups, Docker volumes and `/var/lib/spaceworks/ops`;
never unpack blindly over live state. Install related Compose/deploy files if that release changes them.

Replace/add these keys in the existing `.env`:

```env
SPACEWORKS_REPOSITORY=tinkerhub/SpaceWorks
MAKERSPACE_BACKEND_IMAGE=ghcr.io/tinkerhub/spaceworks-backend
MAKERSPACE_FRONTEND_IMAGE=ghcr.io/tinkerhub/spaceworks-frontend
SPACEWORKS_UPDATE_SCHEDULE=*/5 * * * *
```

Direct updater calls resolve the repository from shell → `.env` → `SpaceWorks-HQ/SpaceWorks`. Clear
old exported overrides so `.env` wins. On an existing host, selecting the repository does not derive
new image names; set both explicitly. A static `MAKERSPACE_IMAGE_TAG` also overrides the version
marker for ordinary Compose commands; remove a stale pin if you want the marker to select releases.
When switching from upstream to a fork, first confirm the installed marker's tag exists in the fork's
image packages too. If it does not, use a valid fork release tag for a manual deployment before
enabling its updater; the new image names alone cannot make an upstream-only tag pullable.
Rerun `bash scripts/init-host-orchestration.sh`, reinstall the updater with
`SPACEWORKS_COMPOSE_LAYER=tls bash scripts/install-auto-update.sh` for HTTPS (omit that prefix for
plain HTTP), and run `sudo systemctl enable --now cron`. Check the resulting `crontab -l`.

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
the version marker, and records the result in Software updates. Database migrations are not reversed.
The release workflow retains the current and immediately previous builds for this purpose.

For a deliberate manual rollback, turn automatic installation off in **Software updates**, identify
the previous immutable image tag, and follow [manual deployment and recovery](self-hosting.md#automatic-and-manual-upgrades).
Set `MAKERSPACE_IMAGE_TAG` to that tag in `.env`, rerun `bash scripts/init-host-orchestration.sh`, and
pull/start through the wrapper with the same TLS prefix if applicable. Verify readiness before
recording the restored version. After readiness succeeds, replace `PREVIOUS_TAG` below with the
same immutable tag (without a leading `v`):

```bash
printf '%s\n' 'PREVIOUS_TAG' > .spaceworks-version
SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled run --rm --no-deps -T backend --role management \
  python manage.py update_control complete --version 'PREVIOUS_TAG'
```

Omit the TLS prefix on HTTP hosts. Do not assume old application code can run against incompatible
new migrations; if it cannot, restore the database recovery point using the documented restore procedure.

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

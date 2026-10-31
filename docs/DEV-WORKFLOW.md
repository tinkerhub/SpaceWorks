# SpaceWorks dev workflow — program state and build conventions

> **This is the how-we-build half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that file
> crossed the harness's memory-file size warning; nothing was dropped in the move. It has no
> `AGENTS.md`-style twin — both names of that document point at this one path, so edit it in place.
>
> Read it before starting a build on this program: it carries the current program state, the Codex
> gates, the worktree/test-harness conventions and the three ways to run the stack locally. The
> non-negotiable one-liners are quoted in `CLAUDE.md`; everything else — the *why*, and every trap
> that has already cost a session — is here.

## Current work — FabLab expansion (branch `dev`)

Active multi-part FabLab program built on `dev`. This is a **Codex-driven workflow** (Codex writes specs and
code in parallel where files don't collide; Claude orchestrates and verifies). **What has shipped is listed
in `docs/PROJECT-HISTORY.md`** — do not maintain a second copy of that list here.

**Programs already shipped on `dev`**, each with its rules in `docs/INVARIANTS.md` and its dated entry in
`docs/PROJECT-HISTORY.md`: the FabLab modules (Events, Bookings, Maintenance, Analytics/reports, Machine
Manager role, public self-booking + shared custom forms, the notification matrix, scoped PII encryption
H1–H4, custom editable roles L); **Phase C** (capabilities toggles, Stripe payments, advisory geofenced
check-in, custom machine-type config, per-space pricing, Stripe Connect, reconciliation, native device
sessions + push + PaymentSheet, social sign-in); machine-scoped `MANAGE_MACHINES`; deployment-removable
`payments`/`updates` + install profiles + `suggest_tombstones`; generic OIDC providers; phone + SMS login;
one module key per notification channel; **Notifications v2**; the **module-architecture program**
(operator-facing module groups, the `payments`/`accounts`/`mobile`/`updates` keys, Razorpay behind a
provider seam, a superadmin modules console, cloud/full deploy profiles and a beat-less scheduler, the
**account-less identity seam + staff-created walk-in members**, **four platform login-method switches**,
**opt-in maker profiles and a member directory**, **staff-side event registration** — its security and
loophole audit is **done and pushed**, `a465a2d`); the **events program** (presence split out of
registration, opt-in attended-events on the maker profile, QR event check-in, cross-makerspace
collaborative events with a host-waiver acceptance); **phases 8, 7, 4 and 5A** (emailed-OTP recovery,
account-less member surfaces, Space-Manager data export, deployment backup/restore); and the
**audit-attestation / API-scope / organizations program** of 2026-08-19 (per-row audit MACs plus signed
Merkle batches, organizations conferring actions across their makerspaces, and a frozen registry of every
protected route behind a `legacy:v1` cutover) — its rules are the two newest sections of
`docs/INVARIANTS.md`.

**The Stage-1/2/4 Codex gates are LIVE, subject to a fresh `codex doctor` check when work starts.**
Use the current global `~/.claude/CLAUDE.md` and its `~/.claude/commands/run-codex.md` definition as
the authority for invocation mode, model, reasoning effort and runtime requirements. Do not copy an old
CLI/model constant from this document or assume the interactive `~/.codex/config.toml` defaults are
the gate's settings. If credentials are unavailable, report the gates as blocked and follow the global
instructions; a previous owner's waiver is not a standing exemption.

Stage 1 requires plan review and owner approval before Stage 2 implementation; Stage 4 requires the
background review through the current global `/run-codex` workflow. Preserve the mandatory owner QA
gate below: no early commit before that approval.

**The commit-trailer rule is attribution, not ceremony:** name Codex in a `Co-Authored-By` trailer only on
work Codex actually wrote. A Codex trailer on work it did not write is false attribution, and that overrides
the unconditional three-trailer rule in the global config — so the trailer set is decided per commit by who
really wrote the code, never by the branch or the program.

Per owner direction, the **single user QA is deferred to the very end** (after all Parts) — no per-Part QA
gate. Specs live (gitignored) under `docs/superpowers/specs/2026-07-1*`. Commits sit **local and unpushed on
`dev`**; **pushing is the owner's call alone.** Ask `git rev-list --count origin/dev..dev` rather than
trusting any number written here.

**Phase 5B (per-makerspace tenant migration, managed → self-host) is BUILT on `dev`.** All three review
lenses approved `2026-08-16-phase5b-plan-v13.md` after thirteen adversarial rounds, the owner signed off,
and every part is merged. Its load-bearing conclusions are under **Backup, restore and tenant migration** in
`docs/INVARIANTS.md`. The one deferred end-to-end owner QA is still outstanding.

**Review prompts must be scoped to the DELTA once a plan is large.** Two round-13 reviewers ran **6h11m**
(against a normal 5–10 min) still grepping migrations, because they were handed the full ~900-line
cumulative plan plus the standing "verify every claim against the real code" instruction — unbounded when
the document carries hundreds of `file:line` citations. Re-running them against a 48-line `diff -u v12 v13`
plus their prior verdict returned both approvals in minutes.

## Standing build conventions for this program

- **Parallel Codex via git worktree.** A second track runs in a sibling worktree (e.g. `../IM-nbuild` on its
  own branch) with a dedicated test DB, so two Codex builds don't collide on shared files (`rbac.py`,
  `origin_scope.py`, `admin_api/urls.py`, `openapi-schema.json`, `api.ts`). Worktrees are fresh checkouts →
  **gitignored files (e.g. `backend/.env`) must be copied in**. Cap at 2 heavy builds. At the end: merge the
  worktree branch → `dev`, `git worktree remove`, drop its DB.
- **Codex gotchas.** Follow the current global `/run-codex` instructions for foreground implementation,
  background Stage-4 review, flags and reading the captured result file. Do not substitute a copied
  command from an older CLI. The historical Windows `-1073741502` / "host exited during handshake"
  workaround was to stop only Codex PIDs, never harness/MCP `node.exe` processes.
  **Never `git add`/stage before a Codex workspace-write run** — a non-empty staged index makes
  Codex's `apply_patch` silently fail with a
  misleading "workspace/tests/ is read-only" error and no files written. Keep the index clean during
  implementation. Before Stage 4, ensure new untracked files are included in the review: the current
  global uncommitted-review mode includes them without staging. Verify visibility for the selected mode;
  do not stage merely to make files visible, and return to a clean index before another workspace-write run.
- **Test harness.** Use the Docker commands under [Tests](#tests), with the database-owner override and
  an ephemeral encryption key. Base [Compose](../docker-compose.yml) publishes Postgres on :5432 and
  MinIO on :9000 (console :9001); Redis has no host port by default. Machine overrides may change these.
  **Never run two `pytest` procs against one DB** (TRUNCATE-FK teardown races +
  false concurrency failures) and **never run the full suite concurrently with `codex review`** (it runs its
  own pytest). If a background full-suite is killed by the environment, run it as **foreground chunks**
  using the same child-shell environment below and scoped test paths. Consult [AGENTS.md](../AGENTS.md)
  for the explicitly named environmental exceptions and known ordering flake; there is no blanket
  exemption for other failures and no current pass count asserted here.
- **Local dev topology — three ways to run.** Defaults come from the committed Compose files;
  `docker-compose.override.yml` is optional, gitignored and machine-specific. Root `.env` supplies Compose
  interpolation; host Django reads `backend/.env`. Do not interchange their network addresses.
  1. **Everything in Docker with live reload — the default.** `./scripts/dev-docker.sh up -d --build`.
     `docker-compose.dev.yml` (committed) layers onto the base file: `./backend` and `./frontend` are
     bind-mounted, Django runs under autoreloading `runserver` with `DEBUG=True`, and the frontend is the
     Vite dev server with HMR instead of nginx. Frontend :5000, backend + `/control/` + `/docs/` on :8000.
     No host virtualenv, no host `npm install`.
  2. **Everything in Docker, production-shaped.** `docker compose up -d --build` — gunicorn + nginx serving
     the baked `dist`. Base defaults are frontend :80 and backend :8001; a machine override may replace
     them. Code changes need a rebuild. This is a separate topology requiring explicit non-DEBUG
     configuration, including a real `SECRET_KEY` (32+ random characters) and a process-visible
     `TRUSTED_PROXY_COUNT`; see [Local development](#local-development).
  3. **Infrastructure only in Docker, apps on the host — advanced fallback.** Configure the host
     virtualenv, frontend dependencies and service URLs manually as described below. There is no
     committed host-launcher script to supply the rewrites.

  **`scripts/dev-docker.sh` exists because passing any `-f` to `docker compose` disables the automatic merge
  of `docker-compose.override.yml`.** It spells the chain out as base → override → dev, in that order: the
  optional override can supply infrastructure port remaps, and the dev layer must come last so its app-service
  commands, ports and bind mounts win. Every argument is forwarded verbatim, so it is a drop-in prefix for
  any compose subcommand. Use `./scripts/dev-docker.sh config` to inspect the merged configuration
  locally (it contains secrets; do not publish it). Three traps this topology already hit:
  - **The base file hands `backend`'s environment to `migrate`/`worker`/`beat` through a YAML anchor**, so a
    patch to `backend` alone never reaches them. Apply browser-facing storage URL changes to all
    four (the Celery worker builds public image URLs into outbound mail).
  - **`tsc -b` must not emit `vite.config.js` next to `vite.config.ts`** — Vite resolves `.js` first, so a
    stale artifact silently shadows the real config; `tsconfig.node.json` therefore emits into
    `node_modules/.tmp/`.
  - **The dev frontend must carry its own `image:` tag** (`spaceworks-frontend-dev`): `frontend` is the only
    service overriding `build.target`, so without it both topologies derive the same `spaceworks-frontend`
    name, whichever built last owns the tag, and a later prod `docker compose up -d` **without `--build`**
    silently runs the dev image — `CMD` is `npm run dev`, nginx never starts, and its published port
    points at a dead nginx listener. The container sits **unhealthy while its logs read a perfectly
    normal "VITE ready"**. The
    instant tell is the port: the dev stage is `FROM deps` (no source), so without the dev layer's
    `./frontend:/app` mount there is no `vite.config.ts` and Vite falls back to its default **:5173**
    instead of the configured **:5000**.
- **Migration heads drift.** Specs quote stale migration numbers; every Codex prompt must
  `ls backend/apps/<app>/migrations/` and chain off the **actual** leaf, not the spec number. A new
  migration whose dep is a rewound app can break migration-executor tests (rewind the full graph forward in
  the test's `finally`).

## Local development

Start with the root `.env.example` and the local settings in
[DEVELOPMENT.md](../.github/DEVELOPMENT.md#1-configure-a-local-docker-environment). The default path
needs Git, Docker and a current Compose plugin, with no host Python/npm setup. Run commands from the
repository root. Migrations run automatically before application services start:

```bash
./scripts/dev-docker.sh config              # inspect locally; output contains secrets
./scripts/dev-docker.sh up -d --build       # first run; drop --build afterwards
./scripts/dev-docker.sh logs -f backend
./scripts/dev-docker.sh restart worker beat # Celery has no autoreload
./scripts/dev-docker.sh down                # retains data volumes
```

**Optional synthetic local fixtures only:** on a disposable local database, run the following after
startup. It creates demo accounts and resets demo inventory; never run it against production data.

```bash
./scripts/dev-docker.sh run --rm --no-deps backend --role management python manage.py seed_demo
```

- Public catalog: `http://localhost:5000`; the seed includes `http://localhost:5000/m/alpha-lab`.
- Staff console: `http://localhost:5000/admin/`; Django control plane: `http://localhost:8000/control/`.
- API: `http://localhost:8000/api`; Swagger `/docs/`, ReDoc `/redoc/`, schema `/schema/` on that backend.

The frontend Docker image uses **Node 22 Alpine**. For intentional dependency changes, use that image
to regenerate `frontend/package-lock.json`, then rebuild and renew the dev dependency volume:

```bash
docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine npm install --package-lock-only
./scripts/dev-docker.sh up -d --build -V frontend
```

**Production-shaped Docker is separate.** Stop the dev stack first. `docker compose up -d --build`
uses gunicorn/nginx with base defaults of `http://localhost` and `http://localhost:8001` for the backend,
subject to the optional automatic machine override. Configure `DEBUG=False`, a non-placeholder
`SECRET_KEY`, local origins/storage URLs and the actual proxy topology before using it. The base
environment does not forward `TRUSTED_PROXY_COUNT`: provide it to Django/Celery processes, including
`migrate`, through a local Compose override. The bundled nginx path has one proxy; direct backend
access has none. Use the [self-hosting guide](self-hosting.md) for deployment configuration.

**Advanced host applications with container infrastructure:** stop the Docker application stack first,
then start only infrastructure:

```bash
./scripts/dev-docker.sh down
./scripts/dev-docker.sh up -d db redis minio createbuckets
```

Manually create `backend/.venv` with Python 3.12+, install `backend/requirements.txt`, and copy
`backend/.env.example` to `backend/.env` if it does not already exist. Set a local `SECRET_KEY`,
`DEBUG=True`, HTTP development cookies (`AUTH_COOKIE_SAMESITE=Lax`, `AUTH_COOKIE_SECURE=False`),
and `DATABASE_URL` using the actual published Postgres port (base :5432). Set both
`AWS_S3_ENDPOINT_URL` and `AWS_S3_PUBLIC_ENDPOINT_URL` to the host-reachable MinIO endpoint (base
`http://localhost:9000`), and align `PUBLIC_IMAGE_BASE_URL`. Container service names are not host URLs.

Redis is not published by default. If the host apps need Redis, explicitly publish it in your local
override and configure the host-facing `CELERY_BROKER_URL` / `CACHE_URL`; this project does not read a
`REDIS_URL` setting. Otherwise leave the broker unset for eager tasks and the database cache. Configure
any other host-run workers the same way. From `backend/`, with the virtualenv activated, run
`python manage.py migrate` and `python manage.py runserver`. In a separate terminal, use Node 20.19+
or 22.12+, install frontend dependencies with `npm ci`, configure `frontend/.env` from its example
(`VITE_API_URL=http://localhost:8000/api`), and run `npm run dev` from `frontend/`.

**Never run host and Docker application stacks simultaneously:** they share the database and dev app
ports (:8000, :5000). A parallel worktree needs its own database and non-conflicting service mappings.

## Tests

Documented commands are not evidence of a passing run. Before pushing, run the required local backend
suite and frontend checks: GitHub CI only runs `pip-audit`. Keep the existing owner QA gate and API
generation requirements in [AGENTS.md](../AGENTS.md); schema changes still require both generated
artifacts, using spectacular's `--format openapi-json`.

For the backend, use the running dev stack and the **database owner**: runtime `spaceworks_app` lacks
`CREATEDB`. Generate a fresh Fernet `API_CLIENT_ENC_KEY` inside the child shell using the image's installed
`cryptography`; the normally empty container setting otherwise breaks encrypted-secret tests. The key
is captured in the shell, not printed or persisted, and applies only to that test process:

```bash
./scripts/dev-docker.sh exec -T backend sh -c '
  export DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager
  export API_CLIENT_ENC_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  python -m pytest -q --create-db
'
```

Use the dedicated worktree database URL instead when running a parallel track. Never run two pytest
processes against one database, or the full suite alongside Codex review. For environmental exceptions,
consult [AGENTS.md](../AGENTS.md): it names `test_host_orchestration_surface_h1a.py` and
`test_host_update_boundary.py`, whose repository paths require a host checkout, plus the isolated-pass
ordering flake in `tests/backup/test_compound_archive_verification_e3.py`. Inspect every other failure;
do not broaden those exceptions into a general allowance.

`backend/tests/backup` and `backend/tests/tenant_migration` require PostgreSQL client tools matching the
server major (**16** in base Compose). The resolver checks `/usr/lib/postgresql/{major}/bin` and
`/usr/pgsql-{major}/bin`, then accepts tools on `PATH` only when their major matches. A host lacking
matching tools fails with `PostgresClientUnavailable`; this is an environment issue, so use Docker:

```bash
./scripts/dev-docker.sh exec -T backend sh -c '
  export DATABASE_URL=postgres://makerspace:makerspace@db:5432/makerspace_manager
  export API_CLIENT_ENC_KEY=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
  python -m pytest tests/backup tests/tenant_migration -q --create-db
'
```

The backend image deliberately installs clients 16 and 17: deployment-local dump/restore selects the
server's major, while migration from newer supported sources needs the newer dump client.

For the frontend, the regression harness specifically uses **Node 20**, independently of the Node 22
Docker image build. From the repository root:

```bash
docker run --rm -v "$PWD/frontend:/app" -w /app node:20 sh -c "npm ci && npx tsc -b && npm test && npm run build"
```

If host-platform dependencies or a live dev process share `frontend/node_modules`, add
`-v spaceworks-node20-test-deps:/app/node_modules` to that command while retaining the
`-v "$PWD/frontend:/app"` source mount. This isolates Node 20 dependencies in a test-only volume.
Use plain `npx tsc -b`; `--noEmit` fails this composite configuration. Host Node 26's native experimental
`localStorage` conflicts with jsdom, so it is not the regression harness.

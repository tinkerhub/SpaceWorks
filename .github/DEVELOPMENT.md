# Space Works — Development

> **This is TinkerHub's customized SpaceWorks setup for TinkerSpace.** Other makerspaces should use
> the official [SpaceWorks-Labs/SpaceWorks](https://github.com/SpaceWorks-Labs/SpaceWorks) project.

This guide is for local development and contributions to this fork. For installation, see the
[self-hosting guide](../docs/self-hosting.md). Read [AGENTS.md](../AGENTS.md) and the
[development workflow](../docs/DEV-WORKFLOW.md) for architecture, mandatory gates and owner QA.

**Prerequisites:** Git, Docker and a current Docker Compose plugin supporting `!override` / `!reset`.
Docker bundles the application toolchains. Host applications need Python 3.12+ and Node 20.19+
(or 22.12+, for Vite 8); the regression test harness specifically uses **Node 20**.

## 0. Get the code

```bash
git clone https://github.com/tinkerhub/SpaceWorks.git
cd SpaceWorks
```

## 1. Configure a local Docker environment

From the repository root, copy the root example only if you do not already have a local `.env`:

```bash
cp .env.example .env
```

Edit `.env` before starting. It is a deployment template, so replace its example domain and secret.
Use a random `SECRET_KEY` of at least 32 characters. For this disposable local stack, set:

```env
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,backend
CORS_ALLOWED_ORIGINS=http://localhost:5000,http://localhost:5173
PUBLIC_APP_BASE_URL=http://localhost:5000
AWS_S3_PUBLIC_ENDPOINT_URL=http://localhost:9000
PUBLIC_IMAGE_BASE_URL=http://localhost:9000/public-images
MINIO_CORS_ALLOWED_ORIGINS=http://localhost:5000
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
AUTH_COOKIE_SAMESITE=Lax
AUTH_COOKIE_SECURE=False
```

The base [Compose file](../docker-compose.yml) fixes the local database owner to
`makerspace:makerspace` and MinIO credentials to `minioadmin:minioadmin`; its services do not consume
the template's `POSTGRES_PASSWORD` / `MINIO_ROOT_PASSWORD` values. These are local development
credentials. Keep `POSTGRES_APP_PASSWORD` consistent with the runtime role provisioned by Compose.
Leave `DATABASE_URL` and `AWS_S3_ENDPOINT_URL` unset in root `.env` to use Compose's container-facing
defaults (`db:5432`, `http://minio:9000`). For encrypted integration secrets, configure and retain
`API_CLIENT_ENC_KEY` using the generation instructions in [.env.example](../.env.example).

Root `.env` supplies Compose interpolation; `backend/.env` is for Django settings when running on
the host. Do not copy the host template's `localhost` database/storage addresses into Docker settings.
No host virtualenv or npm installation is needed for the Docker path.

## 2. Run with live reload

Run these commands from the repository root:

```bash
./scripts/dev-docker.sh config             # inspect merged configuration locally; includes secrets
./scripts/dev-docker.sh up -d --build
./scripts/dev-docker.sh logs -f backend
```

The wrapper uses base → optional `docker-compose.override.yml` → dev configuration. With no machine
override, the dev frontend is at `http://localhost:5000`, the backend at `http://localhost:8000`,
Postgres at host port 5432 and MinIO at 9000 (console 9001). Redis has **no published host port**.
If ports are occupied, configure a local override and inspect the merged configuration; its mappings
can differ. See the [three topologies and merge rules](../docs/DEV-WORKFLOW.md#standing-build-conventions-for-this-program).

Migrations run automatically before application services start. Django and Vite reload source changes;
restart Celery after changing task code:

```bash
./scripts/dev-docker.sh restart worker beat
./scripts/dev-docker.sh down               # stops the stack; keeps data volumes
```

- Public catalog: `http://localhost:5000` → pick a makerspace, or use `/m/<slug>`.
- Staff console: `http://localhost:5000/admin/`; Django control plane: `http://localhost:8000/control/`.
- API: `http://localhost:8000/api`; Swagger: `/docs/`, ReDoc: `/redoc/`, schema: `/schema/` on the backend.

**Optional: synthetic local fixtures only.** On a disposable local database, the seed creates demo
staff credentials and resets demo inventory. Never use it on production or real borrower data:

```bash
./scripts/dev-docker.sh run --rm --no-deps backend --role management python manage.py seed_demo
```

The seed includes `/m/alpha-lab`, `/m/beta-workshop` and `/m/gamma-fab`; its output lists demo logins.

## Dependencies and tests

The frontend [Dockerfile](../frontend/Dockerfile) uses `node:22-alpine` for image dependencies and
builds. When intentionally changing dependencies, regenerate the lockfile with that image's toolchain:

```bash
docker run --rm -v "$PWD/frontend:/app" -w /app node:22-alpine npm install --package-lock-only
./scripts/dev-docker.sh up -d --build -V frontend
```

The second command refreshes the dev container's dependency volume. The separate **Node 20** regression
harness runs installation, type checking, tests and build from the repository root:

```bash
docker run --rm -v "$PWD/frontend:/app" -w /app node:20 sh -c "npm ci && npx tsc -b && npm test && npm run build"
```

See the [canonical test commands](../docs/DEV-WORKFLOW.md#tests) for the backend DB-owner override,
ephemeral encryption key, Postgres client requirements and frontend dependency-volume isolation.
For production-shaped Docker or manually configured host applications, use the
[local development topologies](../docs/DEV-WORKFLOW.md#local-development). Never run host and Docker
application stacks simultaneously.

## Releases (maintainers)

GitHub CI runs only `pip-audit`: pull requests run `security-audit.yml` directly, and main pushes call
it through `ci.yml`. Run the backend and frontend test suites locally before pushing; CI no longer does.
`.github/workflows/release.yml` runs on `workflow_run` when CI completes on `main`, and proceeds only
for a successful run whose original event was `push`. It does not run directly on pushes.
Manual dispatch is refused unless the ref is `main` and a successful push CI run exists for that exact SHA.

The release builds and publishes `ghcr.io/<lowercased repo owner>/spaceworks-backend` and
`ghcr.io/<lowercased repo owner>/spaceworks-frontend`, then creates a tagged GitHub Release with generated
notes. The release title shows `SpaceWorks v<version from VERSION>`,
while its internal tag remains immutable, such as
`<version>-main.<run>.<sha>`, so host updates always select one exact build.

After both images succeed, the current `main` build is promoted to the rolling `:X.Y`, `:main`, and
`:latest` tags. The workflow then removes older Releases and GHCR versions while retaining the current
and immediately previous builds for automatic application rollback. If a newer commit reaches `main`
while an older build is running, the older build cannot promote or clean up the newer release.

The root **`VERSION`** file selects the release series. Bump it to a semantic version such as `1.0.0`
when starting a new series; ordinary commits should leave it unchanged.

> One-time org setup: the `spaceworks-backend` and `spaceworks-frontend` GHCR packages must be set to **Public**
> (org → Packages → each package → visibility) so anyone can `docker compose pull` without logging in.

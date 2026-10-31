# SpaceWorks project status — what exists today

> **This is the what-exists-today half of `CLAUDE.md` / `AGENTS.md`.** It was split out when that
> file crossed the harness's memory-file size warning; nothing was dropped in the move. It has no
> `AGENTS.md`-style twin — both names of that document point at this one path, so edit it in place.
>
> This is a description of the shipped platform, not a rule set: the superadmin control plane, the
> security posture, the non-technical installer, the release-title convention, per-tenant
> integrations and overall implementation status. The rules these areas impose live in
> `docs/INVARIANTS.md`; when a feature landed is in `docs/PROJECT-HISTORY.md`.

## Admin control plane (superadmin-only)

The **Unfold Django admin is the Super Admin's sole control plane**, mounted at **`/control/`** (NOT
`/admin/` — that belongs to the React staff console SPA route), locked to superadmins, and **not exposed on
the public frontend port** (`frontend/nginx.conf` does not proxy it, so makerspace staff on port 80 can
never reach the Django console). Gated two ways: `config.admin_access.AdminSuperuserOnlyMiddleware` (denies
any authenticated non-superadmin; the `/api/v1/admin/...` React staff APIs are NOT gated) and
`config.admin_access.SuperuserOnlyModelAdmin` (first base of every `ModelAdmin`). Superadmin operations are
Django admin **actions that route through the existing services** (never mutating status directly);
issue/return remain React-only. Superadmin monitoring surfaces (QR ZIP, inline QR/photo previews, print file
downloads) are read-only and guard storage failures. Design spec:
`docs/superpowers/specs/2026-06-13-superadmin-admin-control-plane-design.md`.

The React staff console also has a global **Platform settings** entry at `/admin/platform` for an
active superadmin using an explicitly trusted shared portal. It lists API-authorized makerspaces and
shared email/sign-in settings without requiring a selected makerspace; managed Stripe controls require
the payments runtime. A dedicated makerspace origin cannot operate global settings. Auth payloads
report this distinction through optional `staff_context`, and missing context withholds the controls.
Blank custom domains use shared portal paths; a custom hostname stays exclusive to one makerspace.

**U-SEC:** django-axes admin-login lockout, scoped `login`/`public_request_submit` throttles + write-only
`website` honeypot on public submit, production-gated security headers, always-on CSP via django-csp 4, and
a `pip-audit` CI job. The global CSP `script-src` omits `'unsafe-eval'`; a tiny
`config.admin_access.AdminCspEvalMiddleware` appends `'unsafe-eval'` to `script-src` **and** the S3 public
origin to `img-src` **only for `/control/` responses** (django-unfold ships eval-requiring Alpine.js; the
JSON API + public docs stay on the strict policy).

**Django admin coverage** is complete (every domain model registered except deliberately unregistered
retired/unused pages: auth Groups, axes access/failure logs, printing-cutover state/repair;
immutable/workflow-owned models read-only; a `list_filter` per makerspace-scoped admin).
The Unfold sidebar (`config/unfold.py`) is curated
into grouped sections and a test asserts every sidebar link resolves. `tests/test_admin_hidden_scope.py`
walks every registered admin and forces an explicit scoped/global decision (via `NESTED_MAKERSPACE_LOOKUPS`
/ `GLOBAL_ADMIN_MODELS`) so a new admin can't silently leak across the superadmin hide/archive scoping.

**Non-technical install:** the root `install.sh` curl flow on supported Linux families (on Windows, inside WSL2)
(preflight → tagged source archive → published-image pull → `setup.sh` secrets/instance/live module ticks →
version marker), with `SPACEWORKS_DIR` override and an existing-install update/module menu.
`setup.sh --build` is the explicit source-build path via `docker/compose.build.yml`. Windows is
WSL2-only for every host script (native Git Bash/PowerShell lack `flock`, AF_UNIX sockets, root-owned-file
trust and unconverted Docker bind paths; `setup.ps1`/`scripts/update.ps1` only refuse). The updater keeps
its crash-recoverable PID/timestamp lock for hosts without `flock`. See
`docs/setup-for-makerspaces.md`. TLS is env-gated (`ENABLE_HTTPS`, default off). First-run
`setup_instance` requires an explicit superadmin password (`--password` or `SETUP_SUPERADMIN_PASSWORD`);
there is no default credential. `must_change_password` (surfaced by login + `/auth/me`, cleared by
`/auth/change-password`) now marks only temporary passwords from a staff reset or superadmin recovery.

Releases now run through `release.yml`'s `workflow_run` only after CI (including `pip-audit`) succeeds
for a main push; manual dispatch requires `main` and successful push CI for the exact SHA.
Hosts can follow a fork with `SPACEWORKS_REPOSITORY` and matching image overrides. `deploy.yml`
runs after successful Continuous Release completion on `main`, or manual dispatch on `main`, through
an install-owner self-hosted Actions runner. That privileged job has no checkout: it invokes installed
`update.sh`, then verifies the installed marker, backend OCI revision and private readiness in the same
container. A separate hosted job verifies Netlify's public build revision when
`PRODUCTION_FRONTEND_URL` is configured; the final report distinguishes verified, failed, skipped and
unconfigured checks. Both must pass before the complete deployment is reported verified. These are
observations at check time, not a replacement for functional browser QA.
Setup prints registration instructions after startup; no deployment secret is saved in `.env`.
The runner installer retires old polling and checks fork PR approval policy when `gh` is available;
deploy jobs require `SPACEWORKS_DEPLOY_RUNNER=true` in repository variables. Public repositories retain a fork-PR
runner risk even with approval required; see [deploy-ec2.md](deploy-ec2.md).
**Follow-up:** the next release deletes `apps/updates` and drops `updates_platformupdatesettings`
in the same change (its classification entries go with it); it is kept now only so this release's
rollback and compound backup capture remain compatible. This retention does not install a compound
host restore coordinator; see the [supported recovery formats](self-hosting.md#supported-recovery-formats).

**Releases are titled `SpaceWorks <version>`** (owner convention, 2026-08-15), where the version is the
git-tag form `v<semver>-<branch>.<n>.<sha>` — e.g. `SpaceWorks v0.5.1-main.12.a9cd82c0dd89`. **The
`SpaceWorks ` prefix is a display title, not part of the version value:** the installed version lives in
`.spaceworks-version` on the host, without the leading `v` (e.g. `0.5.1-main.12.a9cd82c0dd89`). The host
updater compares it with the latest release tag after stripping that tag's leading `v`; display titles
must never be written into the marker. In-app update controls are retired.

**Per-makerspace integrations are backend-only and never leak.** `Makerspace` holds per-tenant
`telegram_bot_token` + `smtp_*`; secrets are encrypted at rest with `API_CLIENT_ENC_KEY` via
`apps/makerspaces/secrets.py` and decrypted only in delivery code. The staff serializer exposes them
**write-only** + a `*_set` boolean. Bootstrap returns only frontend-safe config (module flags, not secrets).
No shared-integration entity exists — makerspaces sharing SMTP/Telegram enter the same credentials per space
(stored/encrypted independently).

**Implementation status.** The multi-frontend platform and open operations/reporting PRDs are implemented
end-to-end (public browse, auth/RBAC, API-client HMAC, QR/box, audit/evidence, 3D Printing Manager, Hardware
Request Workflow, procurement "To Buy", stock transfers incl. true cross-makerspace movement, stocktake,
analytics/ledger/exports, Users CRUD, and the FabLab modules). The detailed PRDs (`docs/prd-*.md`) are
**internal planning docs kept local only** (gitignored); "PRD §N" references point to those. Google Sheets
OAuth publishing, native apps, and physical label-printer control remain out of scope.

Stack (in use):

- **Backend:** Django 6 + Django REST Framework (`backend/`). Requires Python 3.12+.
- **Frontend:** React 19 + Vite 8 + TypeScript (`frontend/`). Requires Node 20.19+ / 22.12+.
- **Server-state management:** TanStack Query v5
- **Database:** PostgreSQL 16 (via `docker-compose.yml`)
- **Styling:** Tailwind CSS 4 (CSS-first; `src/index.css` uses `@import "tailwindcss"` + `@config
  "../tailwind.config.ts"`; PostCSS via `@tailwindcss/postcss`) with CSS-variable light/dark theme tokens.
  Light default; dark toggle persisted locally.
- **API documentation:** drf-spectacular / OpenAPI (snapshot `frontend/openapi-schema.json` + generated
  `frontend/src/generated/api.ts`; regenerate both when routes/models change — spectacular needs
  `--format openapi-json`).
- **Admin theme:** django-unfold; site name via `ADMIN_SITE_NAME` (default "Space Works").
- **Telegram:** request alerts and test alerts. Outbound only — the webhook acknowledges and discards
  callbacks; decisions are made in the staff console or `/control/`.

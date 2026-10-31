# Split deployment: frontend on Netlify, API on your server

The React app is static, so it can be served from Netlify (or any static host) while the API, worker,
database and object storage run on your own server. This is a supported topology and the one the
Tinkerspace Kochi production uses. It has more moving parts than the bundled same-origin install,
because the browser now talks to **three origins**:

| Origin | Example | Serves |
|---|---|---|
| Site | `https://tools.example.org` (or `https://your-site.netlify.app`) | The React app, from Netlify |
| API | `https://api.example.org` | Django behind the bundled Caddy TLS overlay |
| Files | `https://files.example.org` | MinIO, for uploads and public images |

Every cross-origin setting below exists because one of those three must trust another. Miss one and
the symptom is usually a CORS error in the browser console, not a server error.

## 1. Netlify

`netlify.toml` already sets the base directory (`frontend`), the build command, the publish
directory, Node 22 and the catch-all rewrite to `index.html`. You only set environment variables, in
**Site configuration → Environment variables**. They are read **at build time**, so trigger a new
deploy after changing one.

| Variable | Required | Value |
|---|---|---|
| `VITE_API_URL` | yes | Your API root including `/api`, e.g. `https://api.example.org/api` |
| `VITE_TENANT_TOKEN` | no | A makerspace's **public code**. Set it to make the site that one makerspace's site, with clean routes (`/`, `/admin`, `/checkout`). Leave it unset for the central portal (`/`, `/m/<slug>`, `/admin`) |

Do not put any secret in a `VITE_` variable: everything in it ships in the JavaScript bundle.

### Deployment status in Actions

Set Netlify's production branch to `main`. In GitHub **Settings → Secrets and variables → Actions →
Variables**, set `PRODUCTION_FRONTEND_URL` to this site's production HTTPS address, for example
`https://tools.example.org`. Use the final canonical address: redirects, credentials, query strings
and fragments are rejected. The server's `SPACEWORKS_DEPLOY_RUNNER` setting remains independent.

After each successful Continuous Release, **Production Deploy** waits for Netlify's asynchronous
build and checks `/deployment.json` against the exact released commit. `npm run build` writes this
small public file using Netlify's automatic `COMMIT_REF`; it contains only the commit revision and
has a `no-store` cache header. Do not override `COMMIT_REF`. Other build systems may supply
`SPACEWORKS_BUILD_REVISION`, a full 40-character lowercase hexadecimal commit SHA. If both are supplied,
they must agree; malformed or conflicting values fail the build. Local builds with neither write
`{"revision":null}`, which cannot pass a production verification check.

No Netlify API token is required. A `200` response containing the SPA, an old revision, an HTTP error
or a redirect does not pass. The check has a bounded retry budget; inspect Netlify's build logs if it
times out. Configure the GitHub variable only after adopting a build that publishes this file. An empty
variable is reported as **Not configured / not verified**. The final Actions report calls the entire
deployment **Verified** only when both server and frontend checks succeed. This verifies the revision
served at check time; keep the browser checks in section 5 for functional behaviour.

## 2. Server `.env`

Start from a working install with the TLS overlay (see [self-hosting.md](self-hosting.md#https--security-hardening)),
using the API hostname as `PUBLIC_DOMAIN`. Then set these, replacing existing lines rather than adding
duplicates:

```env
PUBLIC_DOMAIN=api.example.org
ALLOWED_HOSTS=api.example.org,localhost,127.0.0.1,backend
ENABLE_HTTPS=true
TRUSTED_PROXY_COUNT=1

# The site origin(s): exact scheme://host, no trailing slash, comma-separated.
CORS_ALLOWED_ORIGINS=https://tools.example.org
CSRF_TRUSTED_ORIGINS=https://tools.example.org,https://api.example.org

# Cross-site refresh cookie. setup.sh writes Lax/False for the bundled same-origin
# install; a frontend on another origin needs None, and None requires Secure.
AUTH_COOKIE_SAMESITE=None
AUTH_COOKIE_SECURE=True

# Links in email (invitations, member-area links) must point at the SITE, not the API.
PUBLIC_APP_BASE_URL=https://tools.example.org

# Object storage, browser-facing.
STORAGE_DOMAIN=files.example.org
AWS_S3_PUBLIC_ENDPOINT_URL=https://files.example.org
PUBLIC_IMAGE_BASE_URL=https://files.example.org/public-images
MINIO_CORS_ALLOWED_ORIGINS=https://tools.example.org
```

Apply it (every `.env` edit needs the orchestration rerun):

```bash
cd /opt/spaceworks
bash scripts/init-host-orchestration.sh
SPACEWORKS_COMPOSE_LAYER=tls scripts/spaceworks-compose.sh bundled up -d
```

`MINIO_CORS_ALLOWED_ORIGINS` becomes MinIO's `MINIO_API_CORS_ALLOW_ORIGIN` and only takes effect when
the `minio` container is recreated; `up -d` does that when the value changed. Its default is `*`.

The bundled Caddyfile still serves the server's own copy of the app at `https://api.example.org/`.
That is harmless; if you would rather send visitors to the Netlify site, add a redirect for non-API
paths to your installed `deploy/Caddyfile`. Updates never overwrite an edited Caddyfile: they write the
release's version beside it as `deploy/Caddyfile.release` for you to merge (see
[Upgrade notes](self-hosting.md#upgrade-notes-manual-steps-per-release)).

If you use both the Netlify address and a custom domain, list **both** origins in
`CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS` and `MINIO_CORS_ALLOWED_ORIGINS`.

Storage URLs are baked into presigned uploads and every public image `src`, so a `localhost` or
`http://` value works only from the server and shows broken or mixed-content images everywhere else.
On R2 or S3 instead of the bundled MinIO, also set `STORAGE_PRESIGN_METHOD=put` and allow the site
origin in the bucket's CORS rules in the provider dashboard.

The public-image bucket must allow anonymous final-image reads while denying anonymous reads of
`staging/` and staging versions. Apply the release's `deploy/init-object-buckets.sh` policy through
the bundled bootstrap; on external storage, configure the equivalent policy while allowing signed
backend staging reads. Keep the evidence bucket private. Upload failure diagnosis should check the
browser-facing storage URL, running storage service, credentials and bucket CORS separately: a
successful presign response alone does not prove the browser can upload bytes.

## 3. Register the site origin for staff sign-in

`CORS_ALLOWED_ORIGINS` lets the browser *call* the API. It does **not** let staff stay signed in:
the refresh endpoint only trusts a **verified makerspace custom domain** (or an origin in
`PLATFORM_STAFF_ORIGINS`, a comma-separated list of exact origins the compose files pass to the
backend). Without it, staff
can sign in but are signed out on the next page load (the refresh call answers
`403 Origin not allowed.`).

Choose the deployment's intended scope before registering the host:

- **Shared central portal:** a privileged deployment operator adds the portal's exact scheme and
  host to `PLATFORM_STAFF_ORIGINS`, for example `https://portal.example.org` (no path or trailing
  slash). Configure `CORS_ALLOWED_ORIGINS` separately as above; staff trust does not replace CORS.
  Leave `VITE_TENANT_TOKEN` and runtime `tenantToken` unset, with runtime `originBootstrap` off for
  central bootstrap mode. Apply server environment changes
  through the orchestration commands in section 2 and recreate the backend containers so they receive
  the new environment. Rebuild/redeploy the frontend when changing its `VITE_` variables.
- **Dedicated makerspace site:** sign in as the superadmin, open **Settings → Domain & access →
  Custom domain**, enter that makerspace's site host (no scheme), and save. On a self-hosted instance
  it is **Verified** immediately; there is no DNS TXT step. Bind the frontend with
  `VITE_TENANT_TOKEN` set to its public code and rebuild/redeploy. This site stays origin-locked.

If a shared portal host was previously registered as one makerspace's `frontend_domain`, first
configure deployment trust, then coherently remove that shared host from the makerspace or reassign
the makerspace to its dedicated host with the matching frontend binding. Otherwise public
origin-bootstrap can still resolve the shared portal as that one makerspace and put the app in
single mode even without `VITE_TENANT_TOKEN`. Reload after applying the coordinated changes.

Start a fresh staff session after changing origin trust. On a trusted shared portal, a superadmin's
`/admin` chooser offers **Platform settings** at `/admin/platform`, with the accessible makerspaces
and shared deployment settings. It does not require a selected makerspace. The API supplies the staff
context that enables this entry; a missing context or a dedicated makerspace origin withholds it.
Leaving a makerspace's frontend domain blank uses the shared site's `/m/<slug>` and
`/m/<slug>/admin` addresses. Setting a dedicated domain does not automatically hide its public
directory entry; **Hide from central directory** is a separate option and is not an inventory privacy
control.

On an older install, confirm `docker-compose.prod.yml` forwards `PLATFORM_STAFF_ORIGINS` in the
backend's shared environment anchor; current production, cloud and development Compose files do.
An `.env` value alone cannot reach Django when that forwarding entry is missing. After updating an
installed Compose file, rerun orchestration initialization and recreate the application containers.
Check the running backend's setting before removing a tenant's old domain binding.

`staff_origin_scope` gives `PLATFORM_STAFF_ORIGINS` precedence over makerspace domain matches.
This is privileged operator policy, never a client hint: do not add a dedicated makerspace origin to
global trust merely to enable switching. Only a superadmin can set a custom domain on a self-hosted
instance because it feeds the process-wide staff-origin allowlist. Configure the chosen trust path
in the first sign-in visit so refresh can survive the next reload.

### What an origin-locked site means

On a dedicated site whose verified custom domain is not in `PLATFORM_STAFF_ORIGINS`, every staff
request from that origin is pinned to that makerspace:

- Staff actions that target another makerspace are refused. The backend filters the switcher list
  to makerspaces allowed for this account from this site; an unavailable deep link cannot grant
  access to another space. A dedicated frontend binding also hides the global chooser. A shared
  central portal can offer only the spaces its API-returned list authorizes.
- **Platform-wide** staff endpoints (anything not tied to one makerspace) answer `403` from that
  origin, even for the superadmin. Do platform work (creating makerspaces, platform login methods) in
  the Django control plane at `/control/` on the backend.
- Staff sessions are bound to the origin they were created on: a session started on the locked site
  does not carry over to another origin.
- Public pages, member pages and the borrow form keep working for everyone.

## 4. Custom request headers must be allowed

The SPA sends these non-standard headers to the API, and a cross-origin browser only sends a request
whose headers the preflight allowed:

| Header | Sent by |
|---|---|
| `X-Publishable-Key` / `X-Client-Id` | Public catalogue and borrow calls |
| `Idempotency-Key` | Account-less and check-in borrow submits |
| `X-Refresh-CSRF` | Staff and member session refresh / sign-out |
| `X-Station-CSRF` | Event check-in PIN stations |

All of them are listed in `CORS_ALLOW_HEADERS` in `backend/config/settings.py`. `Idempotency-Key` was
missing until release `0.8.5-main.11`, which made **every** public borrow submit from a separate origin
fail its preflight even though same-origin installs worked. Any new header the frontend sends must be
added to that list in the same change.

Check a preflight from your workstation (replace the three values):

```bash
curl -si -X OPTIONS https://api.example.org/api/v1/public/YOUR_SLUG/requests \
  -H 'Origin: https://tools.example.org' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type,idempotency-key,x-publishable-key' \
  | grep -i '^access-control'
```

A working setup prints `access-control-allow-origin: https://tools.example.org`,
`access-control-allow-credentials: true` and an `access-control-allow-headers` line containing
`idempotency-key`. No `access-control-*` lines at all means the origin is not in
`CORS_ALLOWED_ORIGINS` (and not a verified custom domain).

## 5. Verify

1. `curl -fsS https://api.example.org/api/v1/health/` answers `200`.
2. The preflight above passes.
3. Open the site, sign in to `/admin`, **reload the page** and confirm you are still signed in (this
   is the refresh-cookie and staff-origin check).
4. Upload an item photo and an evidence photo (this is the storage CORS check).
5. Submit a borrow request from the public page in a private window.
6. If email is set up, request a password reset from **Forgot password?** on the sign-in page: a
   6-digit code arrives within a minute (it is sent by the Celery worker and beat, so both must run).

## Keep a scheduler

Hosting the frontend elsewhere does not affect scheduled work, but the backend profile does:
`docker-compose.prod.yml` runs Celery `beat`, while `docker-compose.cloud.yml` has no beat and relies
on its `cron` service (if you use the cloud profile, drop only its `frontend` service, never `cron`).
Without a scheduler, return reminders, the evidence-retention sweep, password-reset code delivery and
event-series extension silently never happen.

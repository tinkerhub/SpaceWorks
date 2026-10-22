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

## 3. Register the site origin for staff sign-in

`CORS_ALLOWED_ORIGINS` lets the browser *call* the API. It does **not** let staff stay signed in:
the refresh endpoint only trusts a **verified makerspace custom domain** (or an origin in
`PLATFORM_STAFF_ORIGINS`, a comma-separated list of exact origins the compose files pass to the
backend). Without it, staff
can sign in but are signed out on the next page load (the refresh call answers
`403 Origin not allowed.`).

Sign in as the superadmin, open **Settings → Domain & access → Custom domain**, enter the site host
(`tools.example.org` or `your-site.netlify.app`, no scheme) and save. On a self-hosted instance it is
**Verified** immediately; there is no DNS TXT step. The site is now **origin-locked** to that
makerspace (below), so one Netlify site serves one makerspace's staff; give a second makerspace its
own site.

Only a superadmin can set the custom domain on a self-hosted instance, because that value feeds the
process-wide staff-origin allowlist. Before it is set, a sign-in on the site works but does not survive
a reload, so set it in the same visit, straight after your first sign-in.

### What an origin-locked site means

Once a makerspace's custom domain is the site's host, every staff request from that origin is pinned
to that makerspace:

- Staff actions that target another makerspace are refused. Build with `VITE_TENANT_TOKEN` set to
  that makerspace's public code so the console also hides the makerspace switcher; without it the
  switcher still lists other makerspaces, and choosing one only produces `403`s.
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

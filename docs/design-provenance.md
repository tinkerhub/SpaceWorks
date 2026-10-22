# Design provenance

## Current design (2026-10 redesign)

The frontend uses a token-based design system built on Radix primitives and
lucide icons, with the SpaceWorks colour palette unchanged.

- **Type:** Bricolage Grotesque (display and headings), Figtree (UI and body) and
  JetBrains Mono (codes, IDs, QR values), self-hosted through `@fontsource`
  packages imported in `main.tsx`. All three are under the SIL Open Font License.
- **Tokens:** semantic roles (canvas, subtle, muted, emphasis, line, ink, primary,
  status soft/strong pairs) map onto the existing `--color-*` variables in
  `frontend/src/index.css`, in light and dark. Radius, elevation, motion and
  breakpoints (sm 640, md 960, lg 1200) live in the same theme layer.
- **Components:** `frontend/src/components/ui` (buttons, fields, dropdowns, choice
  controls, tabs, menus, dialogs, toasts, tables, display pieces), exported from
  `components/ui/index.ts`. Shared classes live in `frontend/src/styles/`
  (`type.css`, `components.css`, `controls.css`, `chrome.css`).
- **Shells:** the staff console uses a collapsible sidebar (`features/staff/shell`);
  public pages share `components/chrome/SiteHeader` and `SiteFooter`; sign-in pages
  use `components/chrome/AuthLayout`.

`frontend/src/index.css` keeps the root theme tokens because the backend contrast
guard (`backend/tests/test_frontend_theme_contrast.py`) reads that exact file. The
dark theme, 44px primary control targets, visible focus rings and reduced-motion
preferences are retained.

## Earlier design

Before this redesign SpaceWorks used a "blueprint" look adapted from
[tinkerhub/kanakku-pusthakam](https://github.com/tinkerhub/kanakku-pusthakam),
revision `a8781b3d248135e51dde3c1b6b2807be85976b46`, a community-maintained fork of
SpaceWorks under AGPL-3.0-or-later (see the repository LICENSE and NOTICE). Its
grid background, hard offset shadows, card tilts and Clash Display / Instrument Sans
fonts have been removed.

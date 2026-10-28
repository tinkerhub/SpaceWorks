# Space Works Brand

The logo is the **Tinker Space Inventory** tile: white "TINKER SPACE / Inventory" lettering on a
black rounded square. It replaced the earlier "Parts-Crate" marks, which have been removed. The product
name in text stays **Space Works**.

## The one logo file, and where it is used

[`logo.png`](logo.png) (220 × 220 PNG) is the master copy. The same image is used everywhere:

| Where | File |
|---|---|
| Browser favicon, Apple touch icon, link previews (`og:image`, `twitter:image`) | `frontend/public/favicon.png` |
| Every in-app logo (headers, staff sidebar, footer, sign-in) | `frontend/src/components/SpaceWorksLogo.tsx`, which renders `/favicon.png` |
| `/control/` header icon and favicon | `backend/apps/makerspaces/static/brand/logo.png`, wired in `backend/config/unfold.py` |
| README header | `docs/brand/logo.png` |

To change the logo, replace all three PNGs with the new image (they must stay identical).

## Colour

The UI palette (Tailwind theme tokens) keeps the four accent colours. Each pastel **fill** has a dark
**ink** companion for legible text on top of it.

| Role | Fill | Ink (text on fill) |
|---|---|---|
| Blue | `#7dd3fc` | `#00374a` |
| Yellow | `#fcdf46` | `#3d3400` |
| Mint | `#74dd9c` | `#00321b` |
| Pink | `#f9a8d4` | `#5a1633` |

Neutrals:

| Role | Hex |
|---|---|
| Ink (near-black bg) | `#0c0d10` |
| Charcoal | `#16181d` |
| Cream (light page) | `#faf9f4` |
| Surface (light panel) | `#efeee9` |

## Usage

**Do**
- Use the tile as supplied, on any background; its own black square provides the contrast.
- Give it clear space of at least a quarter of its width on all sides.

**Don't**
- Recolour, stretch, crop or redraw the tile.
- Add shadows, gradients or outlines.

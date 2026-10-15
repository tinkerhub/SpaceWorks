# Blueprint design provenance

SpaceWorks adapts the visual design from
[tinkerhub/kanakku-pusthakam](https://github.com/tinkerhub/kanakku-pusthakam),
revision `a8781b3d248135e51dde3c1b6b2807be85976b46`.
Kanakku Pusthakam is a community-maintained fork of SpaceWorks, distributed under
AGPL-3.0-or-later. See the repository LICENSE and NOTICE for the project terms.

## Adapted presentation

- Cream canvas and 24px blueprint grid, ink outlines, hard offset shadows and
  pastel header bands from the reference frontend's `index.css` and Tailwind theme.
- Directory and catalog cards from `App.tsx` and `ProductCard.tsx`, including
  technical labels, subtle directory tilts and pill quantity controls.
- Shared forms, buttons, navigation, badges, tables, panels, dialogs and request
  progress styling, applied to the current React components.
- Instrument Sans variable body font, self-hosted alongside the existing Clash
  Display headings and JetBrains Mono technical labels. Instrument Sans is under
  the SIL Open Font License; its notice accompanies the font in `frontend/public/fonts`.

## Integration decisions

The port keeps SpaceWorks branding, current routes, catalog search and quick-view
behavior, staff dock navigation, module gates, permissions and request workflows.
Card colours and tilts derive from stable product IDs or makerspace slugs, so
searching or reordering does not change a card's appearance. Colours use the
existing semantic tokens; fixed `on-*` text remains readable on pastel fills in
both themes. The existing dark theme, 44px primary control targets, keyboard
focus indicators and reduced-motion preferences are retained.

`frontend/src/index.css` retains root theme tokens and font definitions because
the backend contrast guard reads that exact file. Shared components now live in
`frontend/src/styles/components.css`; solid chrome and motion overrides live in
`frontend/src/styles/chrome.css`. These files stay within the repository's module
size limit.

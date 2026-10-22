// Presentation idea adapted from tinkerhub/kanakku-pusthakam.
// See docs/design-provenance.md for the upstream source and license.
// Soft brand tints for a card's image placeholder. Picked by a stable identity, never by
// render order, so a card keeps its colour when search or sorting moves it.
const TINTS = [
  "bg-accent/25 text-accent-ink",
  "bg-secondary/30 text-secondary-ink",
  "bg-success/25 text-success-ink",
  "bg-warn/30 text-warn-ink",
] as const;

export function catalogPresentation(identity: string | number) {
  let hash = 0;
  for (const character of String(identity)) {
    hash = (Math.imul(hash, 31) + character.charCodeAt(0)) >>> 0;
  }
  return { tint: TINTS[hash % TINTS.length] };
}

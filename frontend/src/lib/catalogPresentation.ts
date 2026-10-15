// Blueprint presentation adapted from tinkerhub/kanakku-pusthakam.
// See docs/design-provenance.md for the upstream source and license.
const PRESENTATIONS = [
  { band: "bg-accent text-on-accent", shadow: "shadow-hardsoft-accent" },
  { band: "bg-secondary text-on-secondary", shadow: "shadow-hardsoft-secondary" },
  { band: "bg-success text-on-success", shadow: "shadow-hardsoft-success" },
  { band: "bg-warn text-on-warn", shadow: "shadow-hardsoft-warn" },
] as const;

/** Keep a card's colour and tilt unchanged when search or sorting moves it. */
export function catalogPresentation(identity: string | number) {
  let hash = 0;
  for (const character of String(identity)) {
    hash = (Math.imul(hash, 31) + character.charCodeAt(0)) >>> 0;
  }
  return {
    ...PRESENTATIONS[hash % PRESENTATIONS.length],
    tilt: hash % 2 === 0 ? "card-tilt-1" : "card-tilt-2",
  };
}

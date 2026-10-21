import { cn } from "../../lib/cn";

type SpinnerProps = {
  className?: string;
  /** Announced text. Ignored when `decorative`. */
  label?: string;
  /** Hide from assistive tech, e.g. inside a button that already says "Saving…". */
  decorative?: boolean;
};

/** Ring spinner. A bare `<Spinner />` announces "Loading" as a status. */
export function Spinner({ className, label = "Loading", decorative = false }: SpinnerProps) {
  const ring = (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className={cn("size-8 animate-spin text-accent-ink motion-reduce:animate-none", className)}>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  );
  if (decorative) return ring;
  return (
    <span role="status" className="inline-flex items-center gap-3 text-muted">
      {ring}
      <span className="sr-only">{label}</span>
    </span>
  );
}

const DOTS = ["bg-accent", "bg-secondary", "bg-ink"] as const;

/** Three dots (sky, pink, ink) hopping in turn. For page and panel loading; rests with reduced motion. */
export function Loader({ label = "Loading", className }: { label?: string; className?: string }) {
  return (
    <span role="status" className={cn("inline-flex items-end gap-1.5 py-2", className)}>
      {DOTS.map((tone, index) => (
        <span
          key={tone}
          aria-hidden="true"
          className={cn("sw-dot-jump block size-2.5 rounded-full", tone)}
          style={{ animationDelay: `${index * 160}ms` }}
        />
      ))}
      <span className="sr-only">{label}</span>
    </span>
  );
}

/** Loader centred in the viewport, for route-level loading screens. */
export function PageLoader({ label = "Loading" }: { label?: string }) {
  return (
    <div className="fixed inset-0 z-40 grid place-items-center">
      <Loader label={label} />
    </div>
  );
}

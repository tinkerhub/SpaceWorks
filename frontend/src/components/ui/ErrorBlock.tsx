import { AlertCircle } from "lucide-react";

import { cn } from "../../lib/cn";

/** Inline error from a failed query or mutation. Renders nothing for non-Error values. */
export function ErrorBlock({ error, className = "" }: { error: unknown; className?: string }) {
  if (!(error instanceof Error)) return null;
  return (
    <p className={cn("flex items-start gap-1.5 text-sm text-danger-fg", className)} role="alert">
      <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span className="min-w-0">{error.message}</span>
    </p>
  );
}

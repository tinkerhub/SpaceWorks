import { AlertCircle } from "lucide-react";

/** Boxed error message (what went wrong + how to fix). Renders nothing without a message. */
export function ErrorText({ message }: { message?: string | null }) {
  if (!message) return null;
  return (
    <p role="alert" className="flex items-start gap-2 rounded-lg bg-danger-bg px-3.5 py-2.5 text-sm text-danger-fg">
      <AlertCircle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span className="min-w-0">{message}</span>
    </p>
  );
}

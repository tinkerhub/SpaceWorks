import type { ReactNode } from "react";

type PendingToolCheckoutControlsProps = {
  payloads: string[];
  isPending: boolean;
  submitDisabled: boolean;
  showScanWhenEmpty?: boolean;
  pendingLabel?: string;
  children?: ReactNode;
  onRemove: (payload: string) => void;
  onScanAnother: () => void;
  onSubmit: () => void;
};

export function PendingToolCheckoutControls({
  payloads,
  isPending,
  submitDisabled,
  showScanWhenEmpty = false,
  pendingLabel = "Checking out...",
  children,
  onRemove,
  onScanAnother,
  onSubmit,
}: PendingToolCheckoutControlsProps) {
  return (
    <>
      {payloads.length > 0 ? (
        <div className="mt-3 space-y-2" aria-label="Pending tools">
          {payloads.map((payload, index) => (
            <div
              className="flex items-center justify-between gap-3 rounded-lg border border-line px-3 py-2 text-sm"
              key={payload}
            >
              <span className="min-w-0">
                <span className="block font-semibold">Tool {index + 1}</span>
                <span className="block truncate font-mono text-xs text-muted">
                  {payload}
                </span>
              </span>
              <button
                className="desk-button shrink-0"
                type="button"
                aria-label={`Remove tool ${index + 1}`}
                onClick={() => onRemove(payload)}
              >
                Remove
              </button>
            </div>
          ))}
        </div>
      ) : null}
      {showScanWhenEmpty || payloads.length > 0 ? (
        <button
          className="desk-button mt-3 w-full"
          disabled={isPending}
          type="button"
          onClick={onScanAnother}
        >
          {payloads.length > 0 ? "Scan another" : "Scan QR"}
        </button>
      ) : null}
      {children}
      <button
        className="desk-button-primary mt-3 w-full disabled:cursor-not-allowed disabled:opacity-50"
        disabled={submitDisabled || isPending}
        type="button"
        onClick={onSubmit}
      >
        {isPending
          ? pendingLabel
          : `Check out ${payloads.length} ${payloads.length === 1 ? "tool" : "tools"}`}
      </button>
    </>
  );
}

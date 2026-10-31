import type { ReactNode } from "react";
import { QrCode } from "lucide-react";

import { Button } from "../../components/ui";

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
  pendingLabel = "Checking out…",
  children,
  onRemove,
  onScanAnother,
  onSubmit,
}: PendingToolCheckoutControlsProps) {
  return (
    <>
      {payloads.length > 0 ? (
        <ul className="mt-3 divide-y divide-line rounded-md border border-line" aria-label="Pending tools">
          {payloads.map((payload, index) => (
            <li className="flex items-center justify-between gap-3 px-3 py-2" key={payload}>
              <span className="min-w-0">
                <span className="block text-label text-ink">Tool {index + 1}</span>
                <span className="block truncate font-mono text-xs text-ink-muted">{payload}</span>
              </span>
              <Button variant="quiet" size="sm" aria-label={`Remove tool ${index + 1}`} disabled={isPending} onClick={() => onRemove(payload)}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {showScanWhenEmpty || payloads.length > 0 ? (
        <Button className="mt-3" fullWidth startIcon={<QrCode />} disabled={isPending} onClick={onScanAnother}>
          {payloads.length > 0 ? "Scan another" : "Scan QR"}
        </Button>
      ) : null}
      {children}
      <Button
        className="mt-3"
        variant="primary"
        fullWidth
        disabled={submitDisabled || isPending}
        loading={isPending}
        loadingLabel={pendingLabel}
        onClick={onSubmit}
      >
        {`Check out ${payloads.length} ${payloads.length === 1 ? "tool" : "tools"}`}
      </Button>
    </>
  );
}

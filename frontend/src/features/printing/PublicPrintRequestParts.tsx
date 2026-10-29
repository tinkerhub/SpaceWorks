import type { ChangeEvent, Dispatch, SetStateAction } from "react";
import { useEffect, useState } from "react";
import { Check } from "lucide-react";

import { Button, Callout, Chip, ErrorText, Field, Input, Skeleton, Textarea } from "../../components/ui";
import { cn } from "../../lib/cn";
import type { PrintStatus } from "./publicApi";

export type TextInputProps = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  type?: string;
  optional?: boolean;
  helperText?: string;
  maxLength?: number;
};

const steps = [
  { key: "pending", label: "Requested" },
  { key: "accepted", label: "Accepted" },
  { key: "in_progress", label: "In progress" },
  { key: "completed", label: "Ready to collect" },
  { key: "collected", label: "Collected" },
];

export function TextInput({ label, value, onChange, required = false, type = "text", optional, helperText, maxLength }: TextInputProps) {
  return (
    <Field label={label} optional={optional} helperText={helperText}>
      <Input required={required} type={type} maxLength={maxLength} value={value} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

export function TextArea({ label, value, onChange, optional, helperText }: TextInputProps) {
  return (
    <Field label={label} optional={optional} helperText={helperText}>
      <Textarea value={value} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

export function FilePicker({
  label,
  accept,
  files,
  setFiles,
}: {
  label: string;
  accept: string;
  files: File[];
  setFiles: Dispatch<SetStateAction<File[]>>;
}) {
  function addFiles(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []);
    setFiles((current) => [...current, ...selected]);
    event.target.value = "";
  }

  return (
    <div className="min-w-0 space-y-2">
      <Field label={label}>
        <input
          accept={accept}
          className="block min-h-11 w-full min-w-0 rounded-md border border-line-strong bg-canvas p-1 text-sm text-ink-muted file:mr-3 file:min-h-9 file:rounded-full file:border-0 file:bg-fill file:px-3.5 file:py-1.5 file:text-sm file:font-semibold file:text-ink hover:file:bg-emphasis focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-60"
          multiple
          type="file"
          onChange={addFiles}
        />
      </Field>
      {files.length === 0 ? (
        <p className="text-caption text-ink-muted">No files selected.</p>
      ) : (
        <ul className="divide-y divide-line rounded-md border border-line">
          {files.map((file, index) => (
            <li className="flex min-w-0 items-center justify-between gap-3 py-1 pl-3 pr-1" key={`${file.name}-${file.lastModified}-${index}`}>
              <span className="min-w-0 truncate text-body-ui text-ink">{file.name}</span>
              <Button
                variant="danger-quiet"
                size="sm"
                aria-label={`Remove ${file.name}`}
                onClick={() => setFiles((current) => current.filter((_, fileIndex) => fileIndex !== index))}
              >
                Remove
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function printTimeLeftLabel(status: PrintStatus, now: number): string | null {
  if (
    status.status !== "in_progress" ||
    !status.started_at ||
    status.estimated_minutes == null
  ) {
    return null;
  }
  const finish = new Date(status.started_at).getTime() + status.estimated_minutes * 60_000;
  const remainingMs = finish - now;
  if (remainingMs <= 0) {
    return "Finishing up - past the estimate";
  }
  const totalMinutes = Math.ceil(remainingMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return hours > 0 ? `~${hours}h ${minutes}m left` : `~${minutes}m left`;
}

function queuePositionDetail(status: PrintStatus): string {
  const approvedAhead = status.queue_approved_ahead ?? 0;
  const awaitingReviewAhead = status.queue_awaiting_review_ahead ?? 0;
  if (approvedAhead === 0 && awaitingReviewAhead === 0) {
    return "You're next in line";
  }
  return [
    `${approvedAhead} approved job${approvedAhead === 1 ? "" : "s"} ahead`,
    `${awaitingReviewAhead} awaiting review`,
  ].join(" / ");
}

export function StatusStepper({ status }: { status: PrintStatus }) {
  const currentIndex = steps.findIndex((step) => step.key === status.status);
  const terminalError = status.status === "rejected" || status.status === "failed";

  // Live tick so the printing countdown updates without a refetch.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (status.status !== "in_progress") return;
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, [status.status]);
  const timeLeft = printTimeLeftLabel(status, now);

  if (terminalError) {
    return (
      <Callout tone="danger" role="status">
        {status.title} is {status.status}.
      </Callout>
    );
  }

  return (
    <div className="space-y-4">
      <ol className="space-y-0">
        {steps.map((step, index) => {
          const done = index < currentIndex;
          const current = index === currentIndex;
          return (
            <li key={step.key} className="relative flex min-h-9 items-center gap-3 pb-1 last:pb-0" aria-current={current ? "step" : undefined}>
              {index < steps.length - 1 ? (
                <span aria-hidden="true" className={cn("absolute left-[11px] top-7 h-[calc(100%-1.25rem)] w-0.5 rounded-full", done ? "bg-success" : "bg-emphasis")} />
              ) : null}
              <span
                aria-hidden="true"
                className={cn(
                  "relative inline-flex size-6 shrink-0 items-center justify-center rounded-full border-[1.5px] text-[11px] font-bold",
                  done && "border-success bg-success text-on-success",
                  current && "border-accent-ink bg-accent text-on-accent",
                  !done && !current && "border-line-strong bg-canvas text-ink-muted",
                )}
              >
                {done ? <Check className="size-3.5" strokeWidth={3} /> : index + 1}
              </span>
              <span className={cn("break-words text-body-ui", current ? "font-semibold text-ink" : done ? "text-ink" : "text-ink-muted")}>
                {step.label}
                {done ? <span className="sr-only"> (done)</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
      {status.queue_position != null ? (
        <div aria-live="polite" className="rounded-lg bg-subtle px-4 py-3 text-center">
          <p className="font-display text-2xl font-extrabold text-ink">#{status.queue_position} in the queue</p>
          <p className="mt-0.5 text-caption text-ink-muted">{queuePositionDetail(status)}</p>
        </div>
      ) : null}
      {timeLeft ? (
        <p className="text-center">
          <Chip tone="info">{timeLeft}</Chip>
        </p>
      ) : null}
      <p className="text-body-ui text-ink-muted">
        Current status: <span className="font-semibold text-ink">{status.status.replace("_", " ")}</span>
      </p>
    </div>
  );
}

export function StatusResult({
  isPending,
  error,
  status,
}: {
  isPending: boolean;
  error: Error | null;
  status?: PrintStatus;
}) {
  if (isPending) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label="Loading service request status">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (error) {
    return <ErrorText message={error.message} />;
  }

  return status ? (
    <div className="space-y-4">
      <div>
        <h3 className="break-words text-title text-ink">{status.title}</h3>
        <p className="mt-0.5 text-caption text-ink-muted">Created {new Date(status.created_at).toLocaleString()}</p>
      </div>
      <StatusStepper status={status} />
    </div>
  ) : null;
}

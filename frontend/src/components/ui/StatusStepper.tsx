import { Check, X } from "lucide-react";

import { StatusChip } from "./Chip";

const STAGES = ["Requested", "Approved", "Collected", "Returned"] as const;

function statusStageIndex(status: string): number {
  switch (status) {
    case "accepted":
      return 1;
    case "issued":
    case "partially_returned":
      return 2;
    case "returned":
    case "closed_with_issue":
      return 3;
    case "draft":
    case "pending_approval":
    case "rejected":
    default:
      return 0;
  }
}

export function statusStageLabel(status: string): string {
  if (status === "rejected") return "Rejected";
  return STAGES[statusStageIndex(status)] ?? STAGES[0];
}

type StepState = "completed" | "current" | "upcoming" | "issue";

const markClasses: Record<StepState, string> = {
  completed: "border-transparent bg-success-bg text-success-fg",
  current: "border-accent-ink bg-primary text-on-primary",
  upcoming: "border-dashed border-line-strong bg-canvas text-ink-muted",
  issue: "border-transparent bg-danger-bg text-danger-fg",
};

function StepBox({ step, label, state }: { step: number; label: string; state: StepState }) {
  return (
    <span className="flex w-full min-w-0 flex-col items-center gap-1.5" aria-current={state === "current" ? "step" : undefined}>
      <span aria-hidden="true" className={`inline-flex size-8 items-center justify-center rounded-full border-[1.5px] text-sm font-bold ${markClasses[state]}`}>
        {state === "completed" ? <Check className="size-4" strokeWidth={3} /> : state === "issue" ? <X className="size-4" strokeWidth={3} /> : step + 1}
      </span>
      <span className={`min-w-0 break-words text-xs font-semibold ${state === "upcoming" ? "text-ink-muted" : "text-ink"}`}>{label}</span>
    </span>
  );
}

function RejectedBadge() {
  return <StatusChip tone="danger">Rejected</StatusChip>;
}

export function StatusStepper({ status }: { status: string }) {
  const rejected = status === "rejected";
  const activeIndex = rejected ? 0 : statusStageIndex(status);
  // A clean fully-returned request shows the final step as DONE (green) — the
  // flow is finished. A closure WITH an issue (lost/damaged) must NOT read as a
  // clean success: its final step renders as danger (red) instead.
  const complete = status === "returned";
  const closedWithIssue = status === "closed_with_issue";

  return (
    <nav
      aria-label={`Request status: ${statusStageLabel(status)}`}
      className="w-full"
    >
      <ol className="grid grid-cols-4 items-start gap-2">
        {STAGES.map((stage, index) => {
          const state =
            index < activeIndex
              ? "completed"
              : index === activeIndex
                ? closedWithIssue
                  ? "issue"
                  : complete
                    ? "completed"
                    : "current"
                : "upcoming";

          return (
            <li
              className="flex min-w-0 flex-col items-center text-center"
              key={stage}
            >
              <span className="flex w-full min-w-0 flex-col items-center gap-1">
                <StepBox step={index} label={stage} state={rejected && index === 0 ? "issue" : state} />
                {rejected && index === 0 ? <RejectedBadge /> : null}
              </span>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

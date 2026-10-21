import { StatusStepper, statusStageLabel } from "../../components/ui/StatusStepper";
import type { PublicRequestStatus } from "../../types/inventory";

export function RequestSummary({ request }: { request: PublicRequestStatus }) {
  return (
    <div className="min-w-0 rounded-lg border border-line bg-canvas p-4 text-ink [overflow-wrap:anywhere]">
      <StatusStepper status={request.status} />
      <p className="mt-3 text-caption text-ink-muted">Status</p>
      <p className="mt-0.5 text-title">{statusStageLabel(request.status)}</p>
      {request.rejection_reason ? <p className="mt-2 text-body-ui text-danger-fg">{request.rejection_reason}</p> : null}
      {request.requested_for ? <p className="mt-2 line-clamp-2 text-body-ui text-ink-secondary">{request.requested_for}</p> : null}
      <ul className="mt-3 space-y-1">
        {request.items.map((item) => (
          <li
            className="flex justify-between gap-3 text-body-ui text-ink-secondary"
            key={`${request.public_token ?? request.created_at}-${item.product_name}`}
          >
            <span className="min-w-0 flex-1">{item.product_name}</span>
            <span className="shrink-0 font-mono tabular-nums">×{item.requested_quantity}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

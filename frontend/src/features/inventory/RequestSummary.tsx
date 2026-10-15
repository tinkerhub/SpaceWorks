import {
  StatusStepper,
  statusStageLabel,
} from "../../components/ui/StatusStepper";
import type { PublicRequestStatus } from "../../types/inventory";

export function RequestSummary({ request }: { request: PublicRequestStatus }) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-panel p-3 text-ink shadow-soft [overflow-wrap:anywhere]">
      <StatusStepper status={request.status} />
      <div className="flex items-start justify-between gap-3">
        <div className="mt-3">
          <p className="eyebrow text-secondary-ink">Status</p>
          <p className="mt-1 font-mono text-base font-semibold">
            {statusStageLabel(request.status)}
          </p>
        </div>
      </div>
      {request.rejection_reason ? (
        <p className="mt-2 text-sm text-danger">{request.rejection_reason}</p>
      ) : null}
      {request.requested_for ? (
        <p className="mt-2 line-clamp-2 text-sm opacity-80">
          {request.requested_for}
        </p>
      ) : null}
      <div className="mt-3 space-y-1">
        {request.items.map((item) => (
          <div
            className="flex justify-between gap-3 text-sm opacity-80"
            key={`${request.public_token ?? request.created_at}-${item.product_name}`}
          >
            <span className="min-w-0 flex-1">{item.product_name}</span>
            <span className="shrink-0 font-mono">x{item.requested_quantity}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

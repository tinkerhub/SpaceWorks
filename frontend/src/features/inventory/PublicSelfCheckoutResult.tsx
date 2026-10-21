import { Callout } from "../../components/ui";
import type { PublicToolLoanResult } from "./selfCheckoutApi";

function formatStatus(status: string) {
  const normalized = status.replace(/_/g, " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function PublicSelfCheckoutResult({ result }: { result: PublicToolLoanResult }) {
  return (
    <Callout tone="success" role="status" title={`${formatStatus(result.status)}: ${result.items.map((item) => item.product_name).join(", ") || "Tool loan"}`}>
      <ul className="mt-2 space-y-1">
        {result.items.map((item) => (
          <li className="flex items-center justify-between gap-3" key={item.product_name}>
            <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{item.product_name}</span>
            <span className="shrink-0 font-mono font-semibold tabular-nums">×{item.quantity}</span>
          </li>
        ))}
      </ul>
    </Callout>
  );
}

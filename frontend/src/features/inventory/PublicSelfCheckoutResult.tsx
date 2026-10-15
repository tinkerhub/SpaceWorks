import type { PublicToolLoanResult } from "./selfCheckoutApi";

function formatStatus(status: string) {
  const normalized = status.replace(/_/g, " ");
  return normalized.charAt(0).toUpperCase() + normalized.slice(1);
}

export function PublicSelfCheckoutResult({
  result,
}: {
  result: PublicToolLoanResult;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-success bg-success px-3 py-3 text-on-success [overflow-wrap:anywhere] dark:bg-success/15 dark:text-success-ink">
      <p className="eyebrow text-on-success dark:text-success-ink">
        {formatStatus(result.status)}
      </p>
      <h2 className="title-panel mt-1 text-on-success dark:text-success-ink">
        {result.items.map((item) => item.product_name).join(", ") || "Tool loan"}
      </h2>
      <div className="mt-3 space-y-2">
        {result.items.map((item) => (
          <div
            className="flex items-center justify-between gap-3 rounded-lg border border-on-success/20 bg-panel/80 px-3 py-2 text-sm"
            key={item.product_name}
          >
            <span className="min-w-0 flex-1">{item.product_name}</span>
            <span className="shrink-0 font-mono font-semibold">x{item.quantity}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

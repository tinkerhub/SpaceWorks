import { Callout, StatTile } from "../../../components/ui";
import { moduleEnabled } from "../../../lib/modules";
import { errorText, Panel, useStaffGet, type Makerspace } from "./shared";

type DashboardCounts = {
  scope_mode: "machine" | "full";
  overdue_loans?: number;
  pending_requests?: number;
  awaiting_issue?: number;
  open_problem_reports?: number;
  low_stock?: number;
  pending_prints?: number;
  active_prints?: number;
  prints_awaiting_collection?: number;
  failed_emails?: number;
  stocktakes_awaiting_approval?: number;
  warranty_expiring?: number;
  maintenance_overdue?: number;
  pending_payments?: number;
};

// `actionNeeded` tiles turn into the tinted "needs you" StatTile while their count is
// above zero; `danger` keeps the number in the danger colour when something is actually
// wrong. Everything else stays a calm, neutral tile.
type Tile = {
  key: Exclude<keyof DashboardCounts, "scope_mode">;
  label: string;
  actionNeeded: boolean;
  danger?: boolean;
  hint: string;
  // The optional module the count belongs to. A tile for a switched-off module is a
  // permanent zero for a surface that no longer exists, so it is not rendered.
  module?: string;
};

const TILES: Tile[] = [
  { key: "overdue_loans", label: "Overdue loans", actionNeeded: true, danger: true, hint: "Past their return date" },
  { key: "pending_requests", label: "Pending requests", actionNeeded: true, hint: "Waiting for a review" },
  { key: "awaiting_issue", label: "Awaiting issue", actionNeeded: true, hint: "Accepted, not handed out yet" },
  { key: "open_problem_reports", label: "Problem reports", actionNeeded: true, danger: true, hint: "Open and unresolved" },
  { key: "low_stock", label: "Out of stock", actionNeeded: true, danger: true, hint: "Nothing left to lend" },
  { key: "pending_prints", label: "Pending prints", actionNeeded: false, hint: "In the print queue", module: "printing" },
  { key: "active_prints", label: "Active prints", actionNeeded: false, hint: "Printing now", module: "printing" },
  { key: "prints_awaiting_collection", label: "Ready to collect", actionNeeded: false, hint: "Finished prints", module: "printing" },
  { key: "failed_emails", label: "Failed emails", actionNeeded: true, danger: true, hint: "Could not be delivered" },
  { key: "stocktakes_awaiting_approval", label: "Stocktakes awaiting approval", actionNeeded: true, hint: "Counted, need sign-off", module: "stocktake" },
  { key: "warranty_expiring", label: "Warranties expiring", actionNeeded: true, hint: "Within the warning window" },
  { key: "maintenance_overdue", label: "Maintenance overdue", actionNeeded: true, danger: true, hint: "Past the service date", module: "maintenance" },
  { key: "pending_payments", label: "Pending payments", actionNeeded: true, hint: "Waiting to be reconciled", module: "payments" },
];

const MACHINE_TILE_KEYS = new Set<Tile["key"]>([
  "pending_prints",
  "active_prints",
  "prints_awaiting_collection",
  "warranty_expiring",
  "maintenance_overdue",
]);

export function DashboardPanel({ makerspace, canManageMakerspace }: { makerspace: Makerspace; canManageMakerspace: boolean }) {
  const dashboard = useStaffGet<DashboardCounts>(
    ["dashboard", makerspace.id],
    `/admin/makerspace/${makerspace.id}/dashboard`,
  );
  const tiles = TILES.filter((tile) => (
    (dashboard.data?.scope_mode !== "machine" || MACHINE_TILE_KEYS.has(tile.key))
    && (tile.key !== "pending_payments" || canManageMakerspace)
    && (!tile.module || moduleEnabled(makerspace.enabled_modules, tile.module))
  ));

  return (
    <Panel title="Dashboard" description={`What needs attention at ${makerspace.name} right now.`}>
      {dashboard.error ? (
        <Callout tone="danger" role="alert" title="Could not load the dashboard" className="mb-4">
          {errorText(dashboard.error, "Try again in a moment.")}
        </Callout>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-busy={dashboard.isLoading || undefined}>
        {tiles.map((tile) => {
          const value = dashboard.data?.[tile.key] ?? 0;
          const needsAttention = tile.actionNeeded && value > 0;
          return (
            <StatTile
              key={tile.key}
              label={tile.label}
              value={dashboard.isLoading ? <ValuePlaceholder /> : value}
              hint={tile.hint}
              tone={needsAttention ? (tile.danger ? "danger" : "attention") : "default"}
            />
          );
        })}
      </div>
    </Panel>
  );
}

/** Inline pulse where the number will land; a span so it sits inside the tile's value line. */
function ValuePlaceholder() {
  return <span aria-hidden="true" className="inline-block h-8 w-12 animate-pulse rounded-md bg-emphasis align-middle motion-reduce:animate-none" />;
}

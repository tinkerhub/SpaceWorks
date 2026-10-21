import { Link } from "react-router-dom";
import { ChevronRight } from "lucide-react";

import { Chip, EmptyState, Skeleton, StatusChip, type StatusTone } from "../../../../components/ui";
import type { Machine, MachineType, MachineStatus } from "../../machinesApi";

type Props = {
  machineTypes: MachineType[];
  machines: Machine[];
  machinesLoading: boolean;
  machinesFailed: boolean;
  typesLoading: boolean;
  typesFailed: boolean;
  hrefFor: (machineType: MachineType) => string;
};

// Only the states worth surfacing on a card. `idle` is the resting state and says nothing;
// `reserved` is normal scheduling. What an operator scans this grid for is "what is busy"
// and "what is not usable".
const HIGHLIGHT: { status: MachineStatus; label: string; tone: StatusTone }[] = [
  { status: "running", label: "running", tone: "info" },
  { status: "maintenance", label: "in maintenance", tone: "warning" },
  { status: "offline", label: "offline", tone: "danger" },
];

/** The machines index: one flat card per reachable machine type.
 *
 * The card grid is built from the SERVER-SCOPED type list merged with the types nested in
 * the machines response -- never from effective action strings. A `MANAGE_MACHINES` grant
 * is scoped per ROLE through link tables, no links means no machines, and a membership with
 * a null `assigned_role` is EXEMPT: none of that is expressible client-side, and four
 * previous phases have shipped a bug by trying.
 */
export function MachineTypeCards({
  machineTypes,
  machines,
  machinesLoading,
  machinesFailed,
  typesLoading,
  typesFailed,
  hrefFor,
}: Props) {
  if (typesLoading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" role="status" aria-label="Loading machine types">
        {[0, 1, 2].map((slot) => (
          <div key={slot} className="grid gap-3 rounded-lg border border-line bg-canvas p-4">
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-1/3" />
          </div>
        ))}
      </div>
    );
  }

  // An empty grid is only honest after a SUCCESSFUL load -- the same rule the per-type
  // machine list follows. A failed request that renders "no machine types" tells an
  // operator their console is empty when it is merely broken.
  if (!typesFailed && !machineTypes.length) {
    return (
      <EmptyState
        title="No machine types available"
        description="No reachable machine types are configured for you in this makerspace. Ask a space manager to add a type or give your role access to one."
      />
    );
  }

  return (
    <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      {machineTypes.map((machineType) => {
        const owned = machines.filter((machine) => machine.machine_type.id === machineType.id);
        const highlights = HIGHLIGHT.map(({ status, label, tone }) => ({
          label,
          tone,
          count: owned.filter((machine) => machine.status === status).length,
        })).filter((entry) => entry.count > 0);

        return (
          <li key={machineType.id} className="min-w-0">
            <Link
              to={hrefFor(machineType)}
              className="group flex h-full min-w-0 items-start gap-3 rounded-lg border border-line bg-canvas p-4 transition-colors duration-180 ease-standard hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            >
              <span aria-hidden="true" className="inline-flex size-10 shrink-0 items-center justify-center rounded-full bg-fill text-lg text-ink">
                {machineType.icon || machineType.name.charAt(0).toUpperCase()}
              </span>
              <span className="grid min-w-0 flex-1 gap-2">
                <span className="truncate text-title text-ink">{machineType.name}</span>
                <span className="flex flex-wrap items-center gap-1.5">
                  {/* A count is stated as fact, so it must not be stated while the fleet is
                      still loading or after the request failed. */}
                  {machinesLoading ? (
                    <span className="text-caption text-ink-muted">Counting…</span>
                  ) : machinesFailed ? (
                    <span className="text-caption text-ink-muted">Count unavailable</span>
                  ) : (
                    <Chip size="sm">{owned.length} {owned.length === 1 ? "machine" : "machines"}</Chip>
                  )}
                  {!machinesLoading && !machinesFailed
                    ? highlights.map((entry) => (
                        <StatusChip key={entry.label} tone={entry.tone} size="sm">
                          {entry.count} {entry.label}
                        </StatusChip>
                      ))
                    : null}
                </span>
              </span>
              <ChevronRight aria-hidden="true" className="mt-2.5 size-[18px] shrink-0 text-ink-muted transition-transform duration-180 ease-standard group-hover:translate-x-0.5 motion-reduce:transition-none" />
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

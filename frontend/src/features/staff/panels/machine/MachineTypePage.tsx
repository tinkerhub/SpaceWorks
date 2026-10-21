import { Button, Card, EmptyState, FilterChip, SectionHeading, SkeletonRows, Table, TBody, TD, TH, THead, TR } from "../../../../components/ui";
import { ImageThumbnail } from "../../../../components/ui/ImageThumbnail";
import type { PrinterPool } from "../../../../generated/api";
import { isBuiltinPrinterType } from "../../machinesApi";
import type { Machine, MachineStatus, MachineType } from "../../machinesApi";
import { MachineServiceConsole } from "./MachineServiceConsole";
import { PrinterServiceConsole } from "./PrinterServiceConsole";
import { ConsumablePoolCreateForm } from "./ConsumablePoolCreateForm";
import { ConsumablePoolList } from "./SharedConsumablesSection";
import { MACHINE_STATUSES, MachineStatusChip, machineStatusLabel } from "./machineUi";
import type { ServiceDraft } from "./serviceDrafts";

export type StatusFilter = "all" | MachineStatus;

type Props = {
  makerspaceId: number;
  canManage: boolean;
  machineServiceEnabled: boolean;
  printingEnabled: boolean;
  reportsEnabled?: boolean;
  machineType: MachineType;
  allMachines: Machine[];
  visibleMachines: Machine[];
  statusFilter: StatusFilter;
  onStatusFilter: (filter: StatusFilter) => void;
  typePools: PrinterPool[];
  formPools: PrinterPool[];
  existingPools: PrinterPool[];
  machinesLoading: boolean;
  machinesFailed: boolean;
  onSelectMachine: (machineId: number) => void;
  draft: ServiceDraft;
  setDraft: (update: (draft: ServiceDraft) => ServiceDraft) => void;
};

/** One machine type's whole world: its machines, its bound consumables, its service queue.
 *
 * This replaces the collapsible `MachineTypeSection`. Every content rule that section
 * carried is preserved verbatim, because each was a bug someone already hit:
 * both empty states require a SUCCESSFUL load, and `type_payload.model` is displayed for
 * any type that records one -- the retired printer roster was the only place it was ever
 * shown, and `run_machine_model` reads it.
 */
export function MachineTypePage({
  makerspaceId,
  canManage,
  machineServiceEnabled,
  printingEnabled,
  reportsEnabled = true,
  machineType,
  allMachines,
  visibleMachines,
  statusFilter,
  onStatusFilter,
  typePools,
  formPools,
  existingPools,
  machinesLoading,
  machinesFailed,
  onSelectMachine,
  draft,
  setDraft,
}: Props) {
  const canCreate = canManage && machineType.can_create_machine === true;
  const loaded = !machinesLoading && !machinesFailed;

  return (
    <div className="grid gap-8">
      <section aria-label={`${machineType.name} machines`} className="grid gap-4">
        <SectionHeading title="Machines" description="Open a machine for its status, usage, maintenance, documents and operators." />
        {allMachines.length ? (
          <div role="group" aria-label="Filter by status" className="flex flex-wrap gap-2">
            {(["all", ...MACHINE_STATUSES] as StatusFilter[]).map((value) => (
              <FilterChip key={value} selected={statusFilter === value} onClick={() => onStatusFilter(value)}>
                {value === "all" ? "All statuses" : machineStatusLabel(value)}
              </FilterChip>
            ))}
          </div>
        ) : null}

        {/* Both empty states require a SUCCESSFUL load. A failed machines request also yields an
            empty array with `isLoading` false, and claiming "no machines are registered" beside
            the actual error tells the operator something untrue about their own fleet. */}
        {loaded && !allMachines.length ? (
          <EmptyState
            title="No machines yet"
            description="No machines are registered for this type."
          >
            {canCreate ? "Use Add machine to register the first one." : null}
          </EmptyState>
        ) : null}
        {loaded && allMachines.length > 0 && !visibleMachines.length ? (
          <EmptyState
            title="Nothing to show"
            description="No machines match the selected status."
            action={<Button size="sm" onClick={() => onStatusFilter("all")}>Show all statuses</Button>}
          />
        ) : null}
        {machinesLoading || visibleMachines.length ? (
          <Table label="Machine list">
            <THead>
              <tr>
                <TH>Name</TH>
                <TH>Status</TH>
                <TH className="text-right">Usage</TH>
              </tr>
            </THead>
            <TBody aria-busy={machinesLoading || undefined}>
              {machinesLoading ? <SkeletonRows rows={3} cols={3} /> : null}
              {visibleMachines.map((machine) => (
                <TR key={machine.id} className="cursor-pointer" onClick={() => onSelectMachine(machine.id)}>
                  <TD>
                    <span className="flex min-w-0 items-center gap-3">
                      {machine.image_url ? <ImageThumbnail src={machine.image_url} alt={machine.name} className="h-10 w-10 shrink-0" /> : null}
                      <span className="min-w-0">
                        <button
                          type="button"
                          onClick={(event) => { event.stopPropagation(); onSelectMachine(machine.id); }}
                          className="block max-w-full truncate rounded-sm text-left font-semibold text-ink hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                        >
                          <strong className="font-semibold">{machine.name}</strong>
                        </button>
                        <span className="block truncate text-caption text-ink-muted">
                          {[machine.type_payload?.model, machine.location || "No location"].filter(Boolean).join(" · ")}
                        </span>
                      </span>
                    </span>
                  </TD>
                  <TD><MachineStatusChip status={machine.status} /></TD>
                  <TD className="whitespace-nowrap text-right tabular-nums text-ink-secondary">{machine.usage_hours} h</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : null}
      </section>

      {machineServiceEnabled && canManage ? (
        <>
          <section className="grid gap-4" aria-labelledby={`consumables-${machineType.id}`}>
            <div>
              <h2 className="text-h4 text-ink" id={`consumables-${machineType.id}`}>Consumables</h2>
              <p className="mt-1 text-body-ui text-ink-muted">Stock used by this machine type and any pools reserved for one of its machines.</p>
            </div>
            <Card>
              <ConsumablePoolCreateForm makerspaceId={makerspaceId} machineType={machineType} existingPools={existingPools} />
            </Card>
            <div className="grid gap-3">
              <h3 className="text-title text-ink">Stock</h3>
              <ConsumablePoolList makerspaceId={makerspaceId} pools={typePools} />
            </div>
          </section>
          {isBuiltinPrinterType(machineType) ? (
            <PrinterServiceConsole makerspaceId={makerspaceId} canManage={canManage} printingEnabled={printingEnabled} reportsEnabled={reportsEnabled} machineType={machineType} machines={allMachines} pools={formPools} draft={draft} setDraft={setDraft} />
          ) : (
            <MachineServiceConsole makerspaceId={makerspaceId} canManage={canManage} machineType={machineType} machines={allMachines} pools={formPools} draft={draft} setDraft={setDraft} />
          )}
        </>
      ) : null}
    </div>
  );
}

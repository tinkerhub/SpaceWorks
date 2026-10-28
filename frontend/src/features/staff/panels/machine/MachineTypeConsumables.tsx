import type { PrinterPool } from "../../../../generated/api";
import { EmptyState, ErrorBlock, SectionHeading, Skeleton } from "../../../../components/ui";
import type { Machine } from "../../machinesApi";
import { useStaffGet } from "../shared";
import { ConsumablePoolList } from "./ConsumablePoolList";
import { poolHasUnit, poolPath, poolQueryKey } from "./servicePools";
import { typePoolUnit } from "./typeConfig";

export function MachineTypeConsumables({ machine, makerspaceId, canManageMachines, machineServiceEnabled }: {
  machine: Machine; makerspaceId: number; canManageMachines: boolean; machineServiceEnabled: boolean;
}) {
  const allowed = canManageMachines && machineServiceEnabled;
  const pools = useStaffGet<PrinterPool[]>(poolQueryKey(makerspaceId), poolPath(makerspaceId), allowed);
  // Disabling a query leaves its cache readable. Guard rendering too so a role or
  // module change cannot reveal previously fetched privileged stock.
  if (!allowed) return null;
  const unit = typePoolUnit(machine.machine_type);
  const compatible = (pools.data ?? []).filter((pool) => pool.is_active && unit && poolHasUnit(pool, unit) && (
    pool.machine_id === machine.id || (pool.machine_id === null && (
      pool.machine_type_id === machine.machine_type.id || pool.machine_type_id === null
    ))
  ));
  return <section className="mb-6 grid gap-3">
    <SectionHeading as="h3" title={`${machine.machine_type.name} consumables`} description="Stock available to this machine, using the same balance as the machine type's page." />
    {pools.isLoading ? <Skeleton className="h-20 w-full" /> : null}
    <ErrorBlock error={pools.error} />
    {!pools.isLoading && !pools.error ? compatible.length
      ? <ConsumablePoolList makerspaceId={makerspaceId} pools={compatible} canManage={canManageMachines} />
      : <EmptyState title="No compatible stock" description="Add consumables on this machine type's page." /> : null}
  </section>;
}

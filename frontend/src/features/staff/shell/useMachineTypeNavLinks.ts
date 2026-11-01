import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { collectionResults, getMachineTypes, isBuiltinPrinterType, machineKeys } from "../machinesApi";
import { machineTypeSegment } from "../staffTabs";
import { machineTypeQueueSegment } from "../machineTypeRoutes";
import type { StaffNavSubLink } from "./staffNavItems";

/**
 * One sidebar link per machine type this actor can reach. It reads the Machines panel's own
 * server-scoped query and cache entry: which types a role covers is decided by the server's
 * role links, never client-side, and opening the panel costs no second request.
 */
export function useMachineTypeNavLinks(
  makerspaceId: number | undefined,
  enabled: boolean,
  canManageMachines = false,
  machineServiceEnabled = false,
  printingEnabled = false,
): StaffNavSubLink[] {
  const machineTypes = useQuery({
    queryKey: machineKeys.types(makerspaceId ?? 0),
    queryFn: () => getMachineTypes(makerspaceId as number),
    enabled: enabled && makerspaceId !== undefined,
  });
  return useMemo(
    () => collectionResults(machineTypes.data).flatMap((type) => [
      { label: type.name, subPath: machineTypeSegment(type) },
      ...(canManageMachines && machineServiceEnabled && (!isBuiltinPrinterType(type) || printingEnabled)
        ? [{ label: `${type.name} requests`, subPath: machineTypeQueueSegment(type), queue: true }]
        : []),
    ]),
    [machineTypes.data, canManageMachines, machineServiceEnabled, printingEnabled],
  );
}

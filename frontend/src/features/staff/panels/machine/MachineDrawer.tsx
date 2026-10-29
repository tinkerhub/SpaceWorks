import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Chip, DetailDrawer, EmptyState, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from "../../../../components/ui";
import { getMachine, machineKeys } from "../../machinesApi";
import { MachineTypeConsumables } from "./MachineTypeConsumables";
import { ConsumablesTab } from "./ConsumablesTab";
import { DocumentsTab } from "./DocumentsTab";
import { ErrorsTab } from "./ErrorsTab";
import { MachineStatusChip } from "./machineUi";
import { MaintenanceTab } from "./MaintenanceTab";
import { OperatorsTab } from "./OperatorsTab";
import { OverviewTab } from "./OverviewTab";
import { UsageTab } from "./UsageTab";
import { WarrantyTab } from "./WarrantyTab";

type MachineTab = "overview" | "usage" | "maintenance" | "consumables" | "documents" | "errors" | "operators" | "warranty";

const TAB_LABELS: Record<MachineTab, string> = {
  overview: "Overview",
  usage: "Usage",
  maintenance: "Maintenance",
  consumables: "Consumables",
  documents: "Documents",
  errors: "Errors",
  operators: "Operators",
  warranty: "Warranty",
};

export function MachineDrawer({
  machineId, makerspaceId, canManageMachines, maintenanceEnabled, machineServiceEnabled = false, onClose,
}: {
  machineId: number;
  makerspaceId: number;
  canManageMachines: boolean;
  maintenanceEnabled: boolean;
  machineServiceEnabled?: boolean;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<MachineTab>("overview");
  const machine = useQuery({
    queryKey: machineKeys.detail(machineId),
    queryFn: () => getMachine(machineId),
  });
  const details = machine.data;
  // Maintenance needs the module AND operate access; Warranty needs edit access.
  const maintenanceAllowed = maintenanceEnabled && details?.can_operate === true;
  const tabs = (Object.keys(TAB_LABELS) as MachineTab[]).filter((tab) =>
    (tab !== "maintenance" || maintenanceAllowed) && (tab !== "warranty" || details?.can_edit === true),
  );
  // A tab that stops being allowed (a refetch revoked access) falls back to Overview.
  const shownTab = tabs.includes(activeTab) ? activeTab : "overview";

  return (
    <DetailDrawer open title={details?.name ?? "Machine details"} onClose={onClose}>
      {machine.isLoading ? (
        <div className="grid gap-3" role="status" aria-label="Loading machine">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-11 w-full" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : null}
      {machine.error instanceof Error ? (
        <EmptyState tone="error" title="Unable to load machine" description={machine.error.message} />
      ) : null}
      {details ? (
        <div className="grid gap-4">
          <div className="flex flex-wrap items-center gap-2">
            <MachineStatusChip status={details.status} size="md" />
            {!details.is_active ? <Chip tone="warning">Retired</Chip> : null}
            <span className="text-body-ui text-ink-muted">
              {details.machine_type.name} · {details.usage_hours} total hours
            </span>
          </div>
          <Tabs value={shownTab} onValueChange={(value) => setActiveTab(value as MachineTab)}>
            <TabsList aria-label="Machine details">
              {tabs.map((tab) => <TabsTrigger key={tab} value={tab}>{TAB_LABELS[tab]}</TabsTrigger>)}
            </TabsList>
            <TabsContent value="overview">
              <OverviewTab
                machine={details}
                makerspaceId={makerspaceId}
                canManageMachines={canManageMachines}
                canEdit={details.can_edit}
                canOperate={details.can_operate}
                canRetire={details.can_retire}
                canUnretire={details.can_unretire}
              />
            </TabsContent>
            <TabsContent value="usage">
              <UsageTab machineId={machineId} makerspaceId={makerspaceId} canOperate={details.can_operate} retired={!details.is_active} />
            </TabsContent>
            {maintenanceAllowed ? (
              <TabsContent value="maintenance">
                <MaintenanceTab
                  makerspaceId={makerspaceId}
                  machineId={machineId}
                  canEdit={details.can_edit}
                  canOperate={details.can_operate}
                  enabled={shownTab === "maintenance" && maintenanceAllowed}
                  retired={!details.is_active}
                />
              </TabsContent>
            ) : null}
            <TabsContent value="consumables">
              {canManageMachines && machineServiceEnabled ? <MachineTypeConsumables
                machine={details} makerspaceId={makerspaceId}
                canManageMachines={canManageMachines} machineServiceEnabled={machineServiceEnabled}
              /> : null}
              <ConsumablesTab machineId={machineId} canEdit={details.can_edit} canOperate={details.can_operate} retired={!details.is_active} />
            </TabsContent>
            <TabsContent value="documents">
              <DocumentsTab machineId={machineId} canEdit={details.can_edit} />
            </TabsContent>
            <TabsContent value="errors">
              <ErrorsTab machineId={machineId} canOperate={details.can_operate} retired={!details.is_active} />
            </TabsContent>
            <TabsContent value="operators">
              <OperatorsTab machineId={machineId} canDelegate={details.can_delegate} retired={!details.is_active} />
            </TabsContent>
            {details.can_edit ? (
              <TabsContent value="warranty">
                <WarrantyTab machineId={machineId} />
              </TabsContent>
            ) : null}
          </Tabs>
        </div>
      ) : null}
    </DetailDrawer>
  );
}

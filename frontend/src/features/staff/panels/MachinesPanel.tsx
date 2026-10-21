import { useMemo, useState } from "react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { Callout, PageHeader, SectionHeading, Skeleton, buttonClasses } from "../../../components/ui";
import type { PrinterPool } from "../../../generated/api";
import { collectionResults, getMachines, getMachineTypes, machineKeys, type MachineType } from "../machinesApi";
import { machineTypeSegment, parseMachineTypeSegment, staffSubPathFromPath, staffTabPath } from "../staffTabs";
import { MachineDrawer } from "./machine/MachineDrawer";
import { MachineTypeCards } from "./machine/MachineTypeCards";
import { MachineCreateDialog } from "./machine/MachineCreateDialog";
import { MachineTypePage, type StatusFilter } from "./machine/MachineTypePage";
import { SharedConsumablesSection } from "./machine/SharedConsumablesSection";
import { poolPath, poolQueryKey } from "./machine/servicePools";
import { useServiceDrafts } from "./machine/serviceDrafts";
import { MachineTypesPanel } from "./MachineTypesPanel";
import { NotificationRecipientPicker } from "../NotificationRecipientPicker";
import { useStaffGet } from "./shared";

type Props = {
  makerspaceId: number;
  canManage: boolean;
  canConfigureMachineTypes: boolean;
  maintenanceEnabled: boolean;
  machineServiceEnabled: boolean;
  printingEnabled: boolean;
  reportsEnabled?: boolean;
  delegatedRecipientRulesEnabled: boolean;
  guestOnly?: boolean;
  makerspaceSlug?: string | null;
  singleTenantLocked?: boolean;
};

export function MachinesPanel({
  makerspaceId,
  canManage,
  canConfigureMachineTypes,
  maintenanceEnabled,
  machineServiceEnabled,
  printingEnabled,
  reportsEnabled = true,
  delegatedRecipientRulesEnabled,
  guestOnly = false,
  makerspaceSlug = null,
  singleTenantLocked = false,
}: Props) {
  const location = useLocation();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [sharedOpen, setSharedOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  // Lives HERE, in the container that survives index-to-type navigation, not in
  // `MachineTypePage`. Only one type is mounted at a time now, so a hook inside the page
  // would discard a half-typed service form on every navigation -- the drafts previously
  // survived section collapse for exactly that reason.
  const { draftFor, setDraft } = useServiceDrafts();

  const machines = useQuery({ queryKey: machineKeys.list(makerspaceId), queryFn: () => getMachines(makerspaceId) });
  const machineTypes = useQuery({ queryKey: machineKeys.types(makerspaceId), queryFn: () => getMachineTypes(makerspaceId) });
  const poolQuery = useStaffGet<PrinterPool[]>(
    poolQueryKey(makerspaceId),
    poolPath(makerspaceId),
    canManage && machineServiceEnabled,
  );
  const types = collectionResults(machineTypes.data);
  const allMachines = machines.data?.results ?? [];
  const pools = poolQuery.data ?? [];
  const sharedPools = useMemo(
    () => pools.filter((pool) => pool.machine_id === null && pool.machine_type_id === null),
    [pools],
  );

  // The machine and machine-type requests are independent, so the type response can fail, go
  // stale, or omit a type while machines of it loaded fine. Building the index from `types`
  // alone then makes those machines VANISH. Nested `machine.machine_type` is the fallback and
  // is display-only: it carries no `can_create_machine`, which correctly reads as no creation
  // authority. It is still NAVIGABLE -- the machines list is server-scoped too, so a machine
  // the server returned implies a type this actor may open.
  const reachableTypes = useMemo(() => {
    const known = new Set(types.map((type) => type.id));
    const extras: MachineType[] = [];
    for (const machine of allMachines) {
      if (known.has(machine.machine_type.id)) continue;
      known.add(machine.machine_type.id);
      extras.push(machine.machine_type);
    }
    return [...types, ...extras];
  }, [allMachines, types]);

  const hrefFor = (machineType: MachineType) =>
    staffTabPath("machines", guestOnly, makerspaceSlug, singleTenantLocked, machineTypeSegment(machineType));
  const indexHref = staffTabPath("machines", guestOnly, makerspaceSlug, singleTenantLocked);

  const requestedTypeId = parseMachineTypeSegment(staffSubPathFromPath(location.pathname, guestOnly));
  // Both server-scoped sources must have SETTLED SUCCESSFULLY before an id can be called
  // unreachable. Judging on the type query alone would bounce a type known only through the
  // nested fallback; judging while either is loading would bounce every direct link on first
  // paint; judging after a failure would turn a network blip into what looks like a revoked
  // permission.
  const sourcesSettled =
    !machineTypes.isLoading && !machineTypes.isError && !machines.isLoading && !machines.isError;
  const selectedType = reachableTypes.find((type) => type.id === requestedTypeId) ?? null;
  const unknownType = requestedTypeId !== null && sourcesSettled && !selectedType;

  // NO auto-redirect when a single type is reachable. Redirecting would make this index --
  // and with it machine-type configuration, shared consumable pools and the delegated
  // recipient picker -- permanently unreachable for exactly the scoped maintainer those
  // controls are meant for. A single-type actor gets that type's page rendered inline below
  // instead, which lands them on their machines without hiding anything, and removes the
  // redirect loop and the flash-redirect at the same time.
  const soleType = reachableTypes.length === 1 ? reachableTypes[0] : null;
  const shownType = selectedType ?? (requestedTypeId === null ? soleType : null);

  // Normalise an unknown or unreachable type id back to the index -- the console's existing
  // behaviour for a stale deep link, rather than a dead denial page. `replace` so the bad
  // URL does not sit in history waiting for the back button.
  if (unknownType) {
    return <Navigate replace to={indexHref} />;
  }

  // A deep link whose type is known only through the nested machines fallback resolves once
  // the machines query lands. Rendering the index in the meantime would flash the card grid
  // in front of someone who asked for one specific type, so hold with a skeleton instead --
  // an honest "still resolving", which is also what stops the redirect above from firing
  // early.
  if (requestedTypeId !== null && !selectedType && !sourcesSettled) {
    return (
      <section className="grid gap-6" aria-busy="true">
        <PageHeader title="Machines" />
        <Skeleton className="h-40 w-full rounded-lg" />
        <span className="sr-only" role="status">Loading machine type</span>
      </section>
    );
  }

  const typeMachines = shownType
    ? allMachines.filter((machine) => machine.machine_type.id === shownType.id)
    : [];
  const machineIds = new Set(typeMachines.map((machine) => machine.id));
  const typePools = pools.filter((pool) =>
    pool.machine_type_id === shownType?.id ||
    (pool.machine_id !== null && machineIds.has(pool.machine_id)),
  );
  const onTypePage = shownType !== null && selectedType !== null;
  const loadErrors = [
    machineTypes.error instanceof Error ? `Machine types: ${machineTypes.error.message}` : null,
    machines.error instanceof Error ? `Machines: ${machines.error.message}` : null,
    // Panel level, not inside the Shared section: pools feed every type's start and
    // manual-usage forms, and Shared may be collapsed. A failed load would otherwise hand
    // those forms an empty selector with no indication stock failed to fetch, and an
    // operator would retry a start that cannot succeed.
    poolQuery.error instanceof Error ? `Consumable pools could not be loaded: ${poolQuery.error.message}` : null,
  ].filter((message): message is string => message !== null);
  const total = machines.data?.count;

  return (
    <section className="grid min-w-0 gap-6">
      <div className="grid gap-2">
        {onTypePage ? (
          <Link className={buttonClasses({ variant: "quiet", size: "sm", className: "-ml-1.5 justify-self-start" })} to={indexHref}>
            <ArrowLeft aria-hidden="true" className="size-4" />
            All machine types
          </Link>
        ) : null}
        <PageHeader
          title={shownType ? `${shownType.icon ? `${shownType.icon} ` : ""}${shownType.name}` : "Machines"}
          description={shownType
            ? `Machines, consumables and the service queue for ${shownType.name}.`
            : `Shared equipment, operators, usage, documents and operating status.${total !== undefined ? ` ${total} ${total === 1 ? "machine" : "machines"} in total.` : ""}`}
          actions={shownType && canManage && shownType.can_create_machine === true ? (
            <MachineCreateDialog makerspaceId={makerspaceId} machineType={shownType} onCreated={setSelectedId} />
          ) : null}
        />
      </div>

      {loadErrors.length ? (
        <Callout tone="danger" role="alert" title="Some machine data did not load">
          <ul className="grid gap-0.5">{loadErrors.map((message) => <li key={message}>{message}</li>)}</ul>
        </Callout>
      ) : null}

      {shownType ? (
        <MachineTypePage
          makerspaceId={makerspaceId}
          canManage={canManage}
          machineServiceEnabled={machineServiceEnabled}
          printingEnabled={printingEnabled}
          reportsEnabled={reportsEnabled}
          machineType={shownType}
          allMachines={typeMachines}
          visibleMachines={typeMachines.filter((machine) => statusFilter === "all" || machine.status === statusFilter)}
          statusFilter={statusFilter}
          onStatusFilter={setStatusFilter}
          typePools={typePools}
          formPools={[...sharedPools, ...typePools]}
          existingPools={pools}
          machinesLoading={machines.isLoading}
          machinesFailed={machines.isError}
          onSelectMachine={setSelectedId}
          draft={draftFor(shownType.id)}
          setDraft={(update) => setDraft(shownType.id, update)}
        />
      ) : (
        <MachineTypeCards
          machineTypes={reachableTypes}
          machines={allMachines}
          machinesLoading={machines.isLoading}
          machinesFailed={machines.isError}
          typesLoading={machineTypes.isLoading}
          typesFailed={machineTypes.isError}
          hrefFor={hrefFor}
        />
      )}

      {/* The settings block. Rendered on the index AND beneath a sole type's page, which is
          what makes "land straight on my type" safe: none of these controls can become
          unreachable for an actor who only ever has one type. */}
      {!onTypePage ? (
        <div className="grid gap-4 border-t border-line pt-6">
          <SectionHeading title="Setup" description="Machine types and pricing, who gets notified, and consumables shared across the space." />
          <MachineTypesPanel makerspaceId={makerspaceId} canConfigureMachineTypes={canConfigureMachineTypes} />

          {maintenanceEnabled && delegatedRecipientRulesEnabled ? (
            <NotificationRecipientPicker delegated makerspaceId={makerspaceId} />
          ) : null}

          {canManage && machineServiceEnabled ? (
            <SharedConsumablesSection makerspaceId={makerspaceId} pools={sharedPools} existingPools={pools} poolError={poolQuery.error} open={sharedOpen} onToggle={() => setSharedOpen((current) => !current)} />
          ) : null}
        </div>
      ) : null}

      {selectedId !== null ? <MachineDrawer key={selectedId} machineId={selectedId} makerspaceId={makerspaceId} canManageMachines={canManage} maintenanceEnabled={maintenanceEnabled} onClose={() => setSelectedId(null)} /> : null}
    </section>
  );
}

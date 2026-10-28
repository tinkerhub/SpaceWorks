import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, CollapsibleSection, Field, Input, Skeleton } from "../../../components/ui";
import {
  collectionResults,
  createMachineType,
  getMachineTypePricing,
  getMachineTypes,
  machineKeys,
} from "../machinesApi";
import { BuiltinTypeRow } from "./machine/BuiltinTypeRow";
import { CapabilityFields, CustomTypeRow, defaultConfig } from "./machine/MachineTypeEditors";
import { useNotify } from "./machine/machineUi";
import { useConsoleModule } from "./machine/useConsoleModule";

export function MachineTypesPanel({ makerspaceId, canConfigureMachineTypes, canEditPricing = canConfigureMachineTypes }: { makerspaceId: number; canConfigureMachineTypes: boolean; canEditPricing?: boolean }) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [open, setOpen] = useState(false);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [icon, setIcon] = useState("");
  const [config, setConfig] = useState(defaultConfig);
  const machineTypes = useQuery({ queryKey: machineKeys.types(makerspaceId), queryFn: () => getMachineTypes(makerspaceId) });
  // Prices are also what manual usage logs, so they show without payments; only the
  // "Enable payment" (online charge) switch needs the payments module.
  const paymentsOn = useConsoleModule(makerspaceId, "payments");
  const bookingsOn = useConsoleModule(makerspaceId, "bookings");
  const pricing = useQuery({ queryKey: machineKeys.pricing(makerspaceId), queryFn: () => getMachineTypePricing(makerspaceId), enabled: canConfigureMachineTypes || canEditPricing });
  const create = useMutation({
    mutationFn: () => createMachineType(makerspaceId, { slug: slug.trim(), name: name.trim(), icon: icon.trim(), capability_config: config }),
    onSuccess: async (created) => {
      notify.success(`${created?.name ?? name.trim()} created`);
      setSlug(""); setName(""); setIcon(""); setConfig(defaultConfig);
      await queryClient.invalidateQueries({ queryKey: machineKeys.types(makerspaceId) });
    },
    onError: (error) => notify.failure("Couldn't create the machine type.", error),
  });
  const types = collectionResults(machineTypes.data);
  // Empty until pricing loads: the labels then show no currency rather than a placeholder word.
  const currency = pricing.data?.currency?.toUpperCase() ?? "";

  return (
    <CollapsibleSection title="Machine types and pricing" count={types.length || undefined} open={open} onToggle={() => setOpen((current) => !current)}>
      <div className="grid gap-5 p-4">
        <p className="text-body-ui text-ink-muted">
          A built-in type's unit, booking and consumables can be changed for this makerspace only. Prices are set per makerspace, in the currency shown beside each amount.
        </p>
        {canConfigureMachineTypes ? (
          <form className="grid gap-4 rounded-lg border border-line bg-subtle p-4 sm:grid-cols-2 md:grid-cols-3" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
            <h3 className="text-title text-ink sm:col-span-full">New machine type</h3>
            <Field label="Slug" helperText="Lowercase, used in links. It can't change later.">
              <Input value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="laser-cutter" required />
            </Field>
            <Field label="Name"><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="Laser cutter" required /></Field>
            <Field label="Icon"><Input value={icon} onChange={(event) => setIcon(event.target.value)} placeholder="Optional icon" /></Field>
            <CapabilityFields config={config} showBooking={bookingsOn} onChange={setConfig} />
            {create.error instanceof Error ? <p className="text-caption text-danger-fg sm:col-span-full">{create.error.message}</p> : null}
            <Button className="justify-self-start sm:col-span-full" variant="primary" type="submit" loading={create.isPending} loadingLabel="Creating…" disabled={!slug.trim() || !name.trim()}>
              Create type
            </Button>
          </form>
        ) : <p className="text-body-ui text-ink-muted">{canEditPricing
          ? "You can set pricing for the machine types you manage. Creating and configuring types is for a space manager."
          : "You have read-only access to machine types and pricing."}</p>}
        {machineTypes.isLoading ? <Skeleton className="h-20 w-full" /> : null}
        {machineTypes.error instanceof Error ? <p className="text-caption text-danger-fg" role="alert">{machineTypes.error.message}</p> : null}
        {types.length ? (
          <ul className="grid gap-3">
            {types.map((machineType) => machineType.is_builtin || machineType.makerspace === null
              ? <BuiltinTypeRow key={machineType.id} makerspaceId={makerspaceId} machineType={machineType} canConfigure={canConfigureMachineTypes} canEditPricing={canEditPricing} currency={currency} paymentsOn={paymentsOn} showBooking={bookingsOn} />
              : <CustomTypeRow key={machineType.id} makerspaceId={makerspaceId} machineType={machineType} canConfigure={canConfigureMachineTypes} canEditPricing={canEditPricing} currency={currency} paymentsOn={paymentsOn} showBooking={bookingsOn} />)}
          </ul>
        ) : null}
      </div>
    </CollapsibleSection>
  );
}

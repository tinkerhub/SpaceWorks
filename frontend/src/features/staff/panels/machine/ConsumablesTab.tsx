import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, ConfirmDialog, Dropdown, EmptyState, Field, Input, SectionHeading, SegmentedControl, Skeleton, StatusChip } from "../../../../components/ui";
import {
  getConsumableCandidates,
  getMachineConsumables,
  linkMachineConsumable,
  logMachineConsumption,
  machineKeys,
  unlinkMachineConsumable,
  type ConsumableMeasurement,
  type MachineConsumable,
} from "../../machinesApi";
import { useNotify } from "./machineUi";

export function ConsumablesTab({ machineId, canEdit, canOperate, retired = false }: {
  machineId: number;
  canEdit: boolean;
  canOperate: boolean;
  retired?: boolean;
}) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [measurement, setMeasurement] = useState<ConsumableMeasurement>("count");
  const [productId, setProductId] = useState("");
  const [label, setLabel] = useState("");
  const [remaining, setRemaining] = useState("");
  const [lowThreshold, setLowThreshold] = useState("");
  const [note, setNote] = useState("");
  const [unlinking, setUnlinking] = useState<MachineConsumable | null>(null);
  const consumables = useQuery({
    queryKey: machineKeys.consumables(machineId),
    queryFn: () => getMachineConsumables(machineId),
  });
  const candidates = useQuery({
    queryKey: machineKeys.consumableCandidates(machineId),
    queryFn: () => getConsumableCandidates(machineId),
    enabled: canEdit,
  });
  const items = consumables.data ?? [];
  const linkedProducts = new Set(items.flatMap((item) => item.product ? [item.product] : []));
  const eligible = (candidates.data ?? []).filter((item) => !linkedProducts.has(item.id));
  const refresh = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: machineKeys.consumables(machineId) }),
    queryClient.invalidateQueries({ queryKey: machineKeys.consumableCandidates(machineId) }),
  ]);
  const link = useMutation({
    mutationFn: () => linkMachineConsumable(machineId, measurement === "count" ? {
      measurement,
      product_id: Number(productId),
      low_threshold: lowThreshold || null,
      note: note.trim(),
    } : {
      measurement,
      label: label.trim(),
      remaining: remaining || "0",
      low_threshold: lowThreshold || null,
      note: note.trim(),
    }),
    onSuccess: async (linked) => {
      notify.success(`${linked?.product_name ?? linked?.label ?? "Consumable"} linked`);
      setProductId(""); setLabel(""); setRemaining(""); setLowThreshold(""); setNote("");
      await refresh();
    },
    onError: (error) => notify.failure("Couldn't link the consumable.", error),
  });
  const unlink = useMutation({
    mutationFn: (id: number) => unlinkMachineConsumable(machineId, id),
    onSuccess: async () => {
      notify.success(`${unlinking?.product_name ?? unlinking?.label ?? "Consumable"} unlinked`);
      setUnlinking(null);
      await refresh();
    },
    onError: (error) => notify.failure("Couldn't unlink the consumable.", error),
  });

  return (
    <section className="grid gap-4">
      <SectionHeading as="h3" title="Inventory links and local ledger" description="Link inventory items by count or keep a separate local grams ledger. Manage filament and other type stock on the machine type's page; copying it here would duplicate its balance." />
      {consumables.isLoading ? (
        <div className="grid gap-2" role="status" aria-label="Loading consumables">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : null}
      {consumables.error instanceof Error ? <EmptyState tone="error" title="Couldn't load consumables" description={consumables.error.message} /> : null}
      {!consumables.isLoading && !consumables.error && !items.length ? (
        <EmptyState title="No consumables linked" description={canEdit && !retired ? "Link an inventory product or start a grams ledger below." : "Nothing is linked to this machine yet."} />
      ) : null}
      {items.length ? (
        <ul className="grid gap-2">
          {items.map((item) => (
            <ConsumableRow key={item.id} item={item} machineId={machineId} canLog={canOperate && !retired}
              canEdit={canEdit} onRemove={() => setUnlinking(item)} onLogged={refresh} />
          ))}
        </ul>
      ) : null}
      {canEdit && !retired ? (
        <form className="grid gap-4 rounded-lg border border-line bg-subtle p-4" onSubmit={(event) => { event.preventDefault(); link.mutate(); }}>
          <h4 className="text-title text-ink">Link inventory or create a local ledger</h4>
          <SegmentedControl
            ariaLabel="Measurement"
            size="sm"
            value={measurement}
            onValueChange={setMeasurement}
            options={[
              { value: "count", label: "Count (inventory)" },
              { value: "grams", label: "Grams (local ledger)" },
            ]}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            {measurement === "count" ? (
              <Field label="Inventory product">
                <Dropdown value={productId} onChange={(event) => setProductId(event.target.value)} required>
                  <option value="" disabled>{candidates.isLoading ? "Loading products…" : "Select a product"}</option>
                  {eligible.map((item) => <option key={item.id} value={String(item.id)}>{item.name} ({item.available} available)</option>)}
                </Dropdown>
              </Field>
            ) : (
              <Field label="Label">
                <Input maxLength={200} value={label} onChange={(event) => setLabel(event.target.value)} required />
              </Field>
            )}
            {measurement === "grams" ? (
              <Field label="Starting grams">
                <Input type="number" min="0" step="0.01" inputMode="decimal" value={remaining} onChange={(event) => setRemaining(event.target.value)} />
              </Field>
            ) : null}
            <Field label={`Low threshold (${measurement})`} helperText="Shows a Low warning at or below this.">
              <Input type="number" min="0" step={measurement === "count" ? "1" : "0.01"} value={lowThreshold} onChange={(event) => setLowThreshold(event.target.value)} />
            </Field>
            <Field label="Note" className="sm:col-span-full">
              <Input maxLength={255} value={note} onChange={(event) => setNote(event.target.value)} />
            </Field>
          </div>
          {link.error instanceof Error ? <p className="text-caption text-danger-fg">{link.error.message}</p> : null}
          <Button className="justify-self-start" type="submit" loading={link.isPending} loadingLabel="Linking…"
            disabled={measurement === "count" ? !productId : !label.trim()}>
            {measurement === "count" ? "Link product" : "Add grams consumable"}
          </Button>
        </form>
      ) : null}
      {(canEdit || canOperate) && retired ? <p className="text-caption text-ink-muted">Retired machines can't link or log consumables. Unlinking still works.</p> : null}
      {candidates.error instanceof Error ? <p className="text-caption text-danger-fg">{candidates.error.message}</p> : null}
      {unlink.error instanceof Error ? <p className="text-caption text-danger-fg">{unlink.error.message}</p> : null}
      <ConfirmDialog
        open={unlinking !== null}
        title={`Unlink ${unlinking?.product_name ?? unlinking?.label ?? "this consumable"}?`}
        message="The machine stops drawing from it. Stock already used stays recorded."
        confirmLabel="Unlink"
        tone="danger"
        pending={unlink.isPending}
        onConfirm={() => { if (unlinking) unlink.mutate(unlinking.id); }}
        onCancel={() => setUnlinking(null)}
      />
    </section>
  );
}

function ConsumableRow({ item, machineId, canLog, canEdit, onRemove, onLogged }: {
  item: MachineConsumable;
  machineId: number;
  canLog: boolean;
  canEdit: boolean;
  onRemove: () => void;
  onLogged: () => Promise<unknown>;
}) {
  const notify = useNotify();
  const [quantity, setQuantity] = useState("");
  const balance = item.measurement === "count" ? item.available : Number(item.remaining);
  const threshold = item.low_threshold === null ? null : Number(item.low_threshold);
  const isLow = threshold !== null && balance !== null && Number(balance) <= threshold;
  const name = item.product_name ?? item.label;
  const log = useMutation({
    mutationFn: () => logMachineConsumption(machineId, item.id, quantity),
    onSuccess: async () => {
      notify.success(`${quantity} ${item.measurement === "count" ? "used" : "g used"} from ${name}`);
      setQuantity("");
      await onLogged();
    },
    onError: (error) => notify.failure("Couldn't log consumption.", error),
  });

  return (
    <li className="grid gap-3 rounded-lg border border-line bg-canvas p-4">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-title text-ink">{name}</strong>
        <span className="tabular-nums text-body-ui text-ink-secondary">
          {item.measurement === "count" ? `${item.available ?? 0} available` : `${item.remaining ?? "0.00"} g remaining`}
        </span>
        {isLow ? <StatusChip tone="warning" size="sm">Low</StatusChip> : null}
        {canEdit ? <Button className="ml-auto" variant="danger-quiet" size="sm" onClick={onRemove}>Unlink…</Button> : null}
      </div>
      {item.note ? <p className="text-caption text-ink-muted">{item.note}</p> : null}
      {canLog ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); log.mutate(); }}>
          <Field label={`Use (${item.measurement})`} className="w-36">
            <Input type="number" min={item.measurement === "count" ? "1" : "0.01"}
              step={item.measurement === "count" ? "1" : "0.01"} value={quantity}
              onChange={(event) => setQuantity(event.target.value)} required />
          </Field>
          <Button type="submit" loading={log.isPending} loadingLabel="Logging…" disabled={!quantity}>Log consumption</Button>
        </form>
      ) : null}
      {log.error instanceof Error ? <p className="text-caption text-danger-fg">{log.error.message}</p> : null}
    </li>
  );
}

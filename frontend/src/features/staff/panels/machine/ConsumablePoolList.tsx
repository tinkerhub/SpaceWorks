import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Chip, EmptyState, ErrorBlock, Field, Input, ProgressBar, StatusChip, Switch } from "../../../../components/ui";
import type { PrinterPool } from "../../../../generated/api";
import { staffRequest } from "../../../../lib/api";
import { useNotify } from "./machineUi";
import { poolLabel, poolQueryKey } from "./servicePools";

type StockState = { label: string; tone: "danger" | "warning" | "success" };

export function poolStockState(pool: PrinterPool): StockState {
  const remaining = Number(pool.remaining_grams);
  const threshold = pool.low_threshold_grams === null || pool.low_threshold_grams === undefined
    ? null
    : Number(pool.low_threshold_grams);
  if (remaining <= 0) return { label: "Empty", tone: "danger" };
  if (threshold !== null && remaining <= threshold) return { label: "Low stock", tone: "warning" };
  return { label: "In stock", tone: "success" };
}

export function ConsumablePoolList({ makerspaceId, pools, canManage }: { makerspaceId: number; pools: PrinterPool[]; canManage: boolean }) {
  const listId = useId();
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [adjustingId, setAdjustingId] = useState<number | null>(null);
  const [quantityDelta, setQuantityDelta] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: poolQueryKey(makerspaceId) });
  const adjustPool = useMutation({
    mutationFn: ({ id, quantity_delta }: { id: number; quantity_delta: string }) => staffRequest(`/admin/machine-service/consumable-pools/${id}/adjustments`, {
      method: "POST",
      body: JSON.stringify({ quantity_delta, reason: "Manual correction" }),
    }),
    onSuccess: async (_result, { quantity_delta }) => {
      notify.success(`Stock adjusted by ${Number(quantity_delta) > 0 ? "+" : ""}${quantity_delta}`);
      setAdjustingId(null);
      setQuantityDelta("");
      await refresh();
    },
    onError: (error) => notify.failure("Couldn't adjust the stock.", error),
  });
  const visibility = useMutation({
    mutationFn: ({ id, isPublic }: { id: number; isPublic: boolean }) => staffRequest<PrinterPool>(`/admin/machine-service/consumable-pools/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ is_public: isPublic }),
    }),
    onSuccess: async (_pool, { isPublic }) => {
      notify.success(isPublic ? "Now visible to requesters" : "Hidden from requesters");
      await refresh();
    },
    onError: (error) => notify.failure("Couldn't change visibility.", error),
  });

  if (!pools.length) {
    return <EmptyState title="No consumable pools" description="Add stock with the form above so jobs can draw from it." />;
  }

  return (
    <>
      <ul className="grid gap-3 md:grid-cols-2">
        {pools.map((pool) => {
          const label = poolLabel(pool);
          const unit = pool.unit ?? "grams";
          const initial = Number(pool.initial_grams);
          const remaining = Number(pool.remaining_grams);
          const percent = initial > 0 ? Math.max(0, Math.min(100, (remaining / initial) * 100)) : 0;
          const state = poolStockState(pool);
          const isPublic = pool.is_public !== false;
          const isAdjusting = adjustingId === pool.id;
          const validAdjustment = quantityDelta.trim() !== "" && Number.isFinite(Number(quantityDelta)) && Number(quantityDelta) !== 0;
          const switchId = `${listId}-pool-visibility-${pool.id}`;
          return (
            <li className="grid min-w-0 content-start gap-3 rounded-lg border border-line bg-canvas p-4" key={pool.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <strong className="min-w-0 text-title text-ink">{label}</strong>
                <StatusChip tone={state.tone} size="sm">{state.label}</StatusChip>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Chip size="sm" tone={pool.machine_id !== null ? "secondary" : pool.machine_type_id !== null ? "accent" : "neutral"}>
                  {pool.machine_id !== null ? "Machine-specific" : pool.machine_type_id !== null ? "Type-wide" : "Space-wide"}
                </Chip>
                <Chip size="sm" tone="outline">
                  <span className="inline-flex items-center gap-1.5">
                    <span
                      aria-hidden="true"
                      className="size-3 rounded-full border border-line-strong bg-fill"
                      style={pool.color_hex || pool.color ? { backgroundColor: pool.color_hex || pool.color } : undefined}
                    />
                    Colour: {pool.color || "Not specified"}
                  </span>
                </Chip>
                {!isPublic ? <Chip size="sm" tone="warning">Hidden from requesters</Chip> : null}
              </div>
              <div className="grid gap-1.5">
                <ProgressBar value={remaining} max={initial} tone={state.tone} label={`${label} remaining`} />
                <div className="flex flex-wrap justify-between gap-2 text-caption text-ink-muted">
                  <p className="tabular-nums"><strong className="text-ink">{pool.remaining_grams}</strong> / {pool.initial_grams} {unit}</p>
                  <span>{Math.round(percent)}% remaining</span>
                </div>
              </div>
              {canManage ? <div className="flex items-center justify-between gap-3 border-t border-line pt-3">
                {/* The accessible name STARTS with the visible text, so voice control can act on
                    what the user reads (WCAG 2.5.3 Label in Name); the pool name keeps it unique. */}
                <label htmlFor={switchId} className="cursor-pointer text-label text-ink">Visible to requesters</label>
                <Switch
                  id={switchId}
                  aria-label={`Visible to requesters: ${label}`}
                  checked={isPublic}
                  disabled={visibility.isPending}
                  onCheckedChange={(checked) => visibility.mutate({ id: pool.id, isPublic: checked })}
                />
              </div> : null}
              {canManage ? (isAdjusting ? (
                <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); if (validAdjustment) adjustPool.mutate({ id: pool.id, quantity_delta: quantityDelta }); }}>
                  <Field label={`Adjustment (${unit}, + or −)`} className="min-w-48 flex-1">
                    <Input
                      autoFocus
                      inputMode="decimal"
                      step="any"
                      type="number"
                      value={quantityDelta}
                      onChange={(event) => setQuantityDelta(event.target.value)}
                      required
                    />
                  </Field>
                  <div className="flex gap-2">
                    <Button type="submit" variant="primary" size="sm" loading={adjustPool.isPending} loadingLabel="Saving…" disabled={!validAdjustment}>Save adjustment</Button>
                    <Button size="sm" variant="quiet" disabled={adjustPool.isPending} onClick={() => { setAdjustingId(null); setQuantityDelta(""); adjustPool.reset(); }}>Cancel</Button>
                  </div>
                </form>
              ) : (
                <Button className="justify-self-start" size="sm" onClick={() => { setAdjustingId(pool.id); setQuantityDelta(""); adjustPool.reset(); }}>
                  Adjust stock
                </Button>
              )) : null}
            </li>
          );
        })}
      </ul>
      <ErrorBlock className="mt-2" error={adjustPool.error ?? visibility.error} />
    </>
  );
}

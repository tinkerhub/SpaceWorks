import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, EmptyState, ErrorBlock, SectionHeading, Skeleton, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { QrImage } from "./QrImage";
import { AssetEditForm } from "./AssetEditForm";
import { errorText, StatusWord, useStaffGet } from "./shared";
import type { Actor, InventoryAssetRow, LendingHistoryResponse, QrHistoryResponse } from "./inventoryForm";

export function QrHistory({ title, queryKey, path }: { title: string; queryKey: unknown[]; path: string }) {
  const [open, setOpen] = useState(false);
  const history = useStaffGet<QrHistoryResponse>(queryKey, path, open);
  const rows = history.data?.scans ?? [];
  return (
    <div className="grid w-full min-w-0 gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-label text-ink">{title}</h3>
        <Button variant="quiet" size="sm" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? "Hide" : "History"}</Button>
      </div>
      {open && history.isLoading ? <Skeleton className="h-10 w-full" /> : null}
      {open ? <ErrorBlock error={history.error} /> : null}
      {open && !history.isLoading && !history.error && !rows.length ? <p className="text-caption text-ink-muted">No QR scans recorded.</p> : null}
      {open && rows.length ? (
        <ul className="grid divide-y divide-line rounded-md border border-line text-caption text-ink-secondary">
          {rows.map((scan) => (
            <li key={scan.id} className="px-3 py-2">
              <span className="font-semibold text-ink">{humanize(scan.context)}</span> on {formatDate(scan.created_at)}{scan.actor ? ` by user #${scan.actor}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// Viewing assets needs VIEW_INVENTORY; editing an asset and the fix-status actions are
// EDIT_INVENTORY on the server, so a view-only role gets the list without the controls.
export function IndividualAssets({ productId, makerspaceId, refreshInventory, canEdit, containersEnabled }: {
  productId: number; makerspaceId: number; refreshInventory: () => void; canEdit: boolean; containersEnabled: boolean;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [editingAssetId, setEditingAssetId] = useState<number | null>(null);
  const assets = useStaffGet<{ results: InventoryAssetRow[] }>(["inventory-assets", productId], `/admin/inventory/${productId}/assets`);
  const containers = useStaffGet<{ results: { id: number; label: string }[] } | { id: number; label: string }[]>(
    ["containers-all", makerspaceId],
    `/admin/makerspace/${makerspaceId}/containers?page_size=1000`,
    canEdit && containersEnabled,
  );
  const containerOptions = Array.isArray(containers.data) ? containers.data : containers.data?.results ?? [];
  const saveAsset = () => {
    setEditingAssetId(null);
    queryClient.invalidateQueries({ queryKey: ["inventory-assets", productId] });
    refreshInventory();
  };
  const action = useMutation({
    mutationFn: ({ assetId, action }: { assetId: number; action: "shelve" | "repair"; tag: string }) =>
      staffRequest(`/admin/assets/${assetId}/fix-status`, {
        method: "POST",
        body: JSON.stringify({ action }),
      }),
    onSuccess: (_data, variables) => {
      showToast(variables.action === "repair" ? `${variables.tag} is back in inventory` : `${variables.tag} moved to the fix shelf`, { tone: "success" });
      queryClient.invalidateQueries({ queryKey: ["inventory-assets", productId] });
      queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspaceId] });
      refreshInventory();
    },
    onError: (error) => showToast(errorText(error, "Could not change the asset's status."), { tone: "error" }),
  });
  const rows = assets.data?.results ?? [];
  return (
    <section className="grid gap-3 border-t border-line pt-5">
      <SectionHeading as="h3" title="Individual assets" description="Each unit with its own tag, container and QR." />
      {assets.isLoading ? <div className="grid gap-2"><Skeleton className="h-20 w-full" /><Skeleton className="h-20 w-full" /></div> : null}
      <ErrorBlock error={assets.error} />
      {!assets.isLoading && !assets.error && !rows.length ? <EmptyState title="No asset records yet" description="Assets appear here once units are tagged for this item." /> : null}
      <div className="grid gap-2">
        {rows.map((asset) => (
          <Card key={asset.id} padding="sm" className="grid gap-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex min-w-0 flex-1 items-center gap-3">
                {asset.qr_code_id ? <div className="w-16 shrink-0"><QrImage qrId={asset.qr_code_id} label={asset.asset_tag} /></div> : null}
                <div className="grid min-w-0 gap-1">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm font-semibold text-ink">{asset.asset_tag}</span>
                    <StatusWord status={asset.status} tone={asset.status === "maintenance" ? "warning" : undefined} />
                  </p>
                  <p className="text-caption text-ink-muted">{[asset.serial_number ? `Serial ${asset.serial_number}` : "", asset.box_label ?? ""].filter(Boolean).join(" · ") || "No serial or container"}</p>
                  <p className="truncate text-caption text-ink-muted">{asset.qr_code_id ? <span className="font-mono">QR #{asset.qr_code_id} · {asset.qr_payload ?? ""}</span> : "No QR linked"}</p>
                </div>
              </div>
              {canEdit ? (
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" aria-expanded={editingAssetId === asset.id} onClick={() => setEditingAssetId((current) => (current === asset.id ? null : asset.id))}>
                    {editingAssetId === asset.id ? "Close" : "Edit"}
                  </Button>
                  {asset.status === "maintenance" ? (
                    <Button size="sm" variant="success" disabled={action.isPending} onClick={() => action.mutate({ assetId: asset.id, action: "repair", tag: asset.asset_tag })}>Move back to inventory</Button>
                  ) : (
                    <Button size="sm" variant="warn" disabled={action.isPending || !["available", "damaged"].includes(asset.status)} onClick={() => action.mutate({ assetId: asset.id, action: "shelve", tag: asset.asset_tag })}>To Fix</Button>
                  )}
                </div>
              ) : null}
            </div>
            {canEdit && editingAssetId === asset.id ? (
              <AssetEditForm asset={asset} containers={containerOptions} onSaved={saveAsset} onCancel={() => setEditingAssetId(null)} />
            ) : null}
            <QrHistory title="Asset QR history" queryKey={["asset-qr-history", asset.id]} path={`/admin/assets/${asset.id}/qr-history`} />
          </Card>
        ))}
      </div>
      <ErrorBlock error={action.error} />
    </section>
  );
}

export function LendingHistory({ productId }: { productId: number }) {
  const history = useStaffGet<LendingHistoryResponse>(["lending-history", productId], `/admin/inventory/${productId}/lending-history`);
  const last = history.data?.last_borrower;
  const recent = history.data?.recent ?? [];
  return (
    <section className="grid gap-3 border-t border-line pt-5">
      <SectionHeading as="h3" title="Lending history" />
      {history.isLoading ? <Skeleton className="h-12 w-full" /> : null}
      <ErrorBlock error={history.error} />
      {!history.isLoading && !history.error && !recent.length ? <p className="text-body-ui text-ink-muted">No lending history yet.</p> : null}
      {last ? (
        <div className="rounded-md bg-subtle px-3 py-2.5 text-body-ui text-ink">
          <p>Last borrower: <span className="font-semibold">{last.username}</span> ({formatDate(last.issued_at)})</p>
          <AttributionLine acceptedBy={last.accepted_by} issuedBy={last.issued_by} />
        </div>
      ) : null}
      {recent.length ? (
        <ul className="grid divide-y divide-line rounded-md border border-line text-body-ui text-ink-secondary">
          {recent.map((entry) => (
            <li key={entry.id} className="px-3 py-2">
              <span className="font-semibold text-ink">{entry.username}</span> — {entry.quantity} on {formatDate(entry.issued_at)}
              <AttributionLine acceptedBy={entry.accepted_by} issuedBy={entry.issued_by} />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function AttributionLine({ acceptedBy, issuedBy }: { acceptedBy: Actor | null; issuedBy: Actor | null }) {
  const parts = [
    acceptedBy ? `Accepted by ${formatActor(acceptedBy)}` : "",
    issuedBy ? `Issued by ${formatActor(issuedBy)}` : "",
  ].filter(Boolean);
  return parts.length ? <p className="text-caption text-ink-muted">{parts.join(" · ")}</p> : null;
}

function formatActor(actor: Actor) {
  return actor.role ? `${actor.username} (${actor.role})` : actor.username;
}

function humanize(value: string) {
  return value.replace(/_/g, " ").replace(/^\w/, (match) => match.toUpperCase());
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

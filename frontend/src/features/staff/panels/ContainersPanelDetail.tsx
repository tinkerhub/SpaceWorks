import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { QrCode } from "lucide-react";

import { Button, Card, EmptyState, ErrorText, SectionHeading, SegmentedControl, Skeleton, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { WarrantySection } from "../WarrantySection";
import { errorText, StatusWord, useStaffGet } from "./shared";
import { QrImage } from "./QrImage";

export type Container = { id: number; code?: string; label: string; location?: string; description?: string; is_active?: boolean; qr_code_id?: number | null };
type ContentsAsset = { id: number; asset_tag: string; product: string; status: string };
type Contents = {
  products: { id: number; name: string; available_quantity: number; tracking_mode: string }[];
  assets: ContentsAsset[];
  children: Container[];
};
type History = { scans: { id: string; source: string; context: string; actor: number | null; created_at: string }[] };

/** Contents and scan history of one container, shown in the detail drawer. */
export function ContainerDetail({ container, canEditInventory }: { container: Container; canEditInventory: boolean }) {
  const [view, setView] = useState<"contents" | "history">("contents");
  return (
    <div className="grid gap-5">
      <div className="grid gap-1 text-body-ui text-ink-secondary">
        {container.code ? <p>Code <span className="font-mono text-ink">{container.code}</span></p> : null}
        {container.location ? <p>Location: {container.location}</p> : null}
        {container.description ? <p>{container.description}</p> : null}
      </div>
      <ContainerQr container={container} />
      <SegmentedControl
        ariaLabel="Container detail"
        value={view}
        onValueChange={setView}
        options={[{ value: "contents", label: "Contents" }, { value: "history", label: "History" }]}
      />
      {view === "contents" ? <ContainerContents containerId={container.id} canEditInventory={canEditInventory} /> : <ContainerHistory containerId={container.id} />}
    </div>
  );
}

// The label staff scan at issue and return. Without it on screen there was no way to print a
// container's QR from the console, so the "scan the box" step could only ever be a list pick.
function ContainerQr({ container }: { container: Container }) {
  if (!container.qr_code_id) {
    return <p className="text-caption text-ink-muted">This container has no QR label, so it can only be picked from the list at handover.</p>;
  }
  return (
    <section className="grid gap-2" aria-label="Container QR">
      <SectionHeading as="h3" title="QR label" description="Print it and stick it on the container; staff scan it at issue and return." />
      <div className="w-40"><QrImage qrId={container.qr_code_id} label={container.label} /></div>
    </section>
  );
}

function LoadingLines() {
  return (
    <div className="grid gap-2" aria-busy="true">
      <Skeleton className="h-10 w-full" />
      <Skeleton className="h-10 w-full" />
    </div>
  );
}

function ContainerContents({ containerId, canEditInventory }: { containerId: number; canEditInventory: boolean }) {
  const contents = useStaffGet<Contents>(["container-contents", containerId], `/admin/containers/${containerId}/contents`);
  if (contents.isLoading) return <LoadingLines />;
  if (contents.error instanceof Error) return <ErrorText message={contents.error.message} />;
  const data = contents.data;
  return (
    <div className="grid gap-5">
      <section className="grid gap-2">
        <SectionHeading as="h3" title="Products" />
        {data?.products.length ? (
          <ul className="grid divide-y divide-line rounded-lg border border-line">
            {data.products.map((product) => (
              <li key={product.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-body-ui">
                <span className="min-w-0 break-words text-ink">{product.name}</span>
                <span className="text-ink-muted">{product.available_quantity} available</span>
              </li>
            ))}
          </ul>
        ) : <EmptyState title="No products here" description="Move stock into this container with a stock transfer." />}
      </section>
      <section className="grid gap-2">
        <SectionHeading as="h3" title="Asset units" />
        {data?.assets.length ? (
          <div className="grid gap-2">
            {data.assets.map((asset) => <AssetQrRow key={asset.id} asset={asset} canEditInventory={canEditInventory} />)}
          </div>
        ) : <EmptyState title="No asset units here" description="Individually tracked units stored in this container show up here." />}
      </section>
      {data?.children.length ? (
        <p className="text-body-ui text-ink-muted">Sub-containers: {data.children.map((child) => child.label).join(", ")}</p>
      ) : null}
    </div>
  );
}

function ContainerHistory({ containerId }: { containerId: number }) {
  const history = useStaffGet<History>(["container-history", containerId], `/admin/containers/${containerId}/history`);
  if (history.isLoading) return <LoadingLines />;
  if (history.error instanceof Error) return <ErrorText message={history.error.message} />;
  const scans = history.data?.scans ?? [];
  if (!scans.length) return <EmptyState title="No scan history" description="Scans of this container's QR during handovers and checks appear here." />;
  return (
    <ul className="grid divide-y divide-line rounded-lg border border-line">
      {scans.map((scan) => (
        <li key={scan.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-body-ui">
          <span className="text-ink">{scan.context || "Scan"}</span>
          <span className="text-ink-muted">
            {scan.source === "box_scan" ? "Reviewed handover" : "QR scan"} · {new Date(scan.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
          </span>
        </li>
      ))}
    </ul>
  );
}

// Reprint a single unit's QR without rebuilding a whole batch: POST asset/<id>/qr is a
// get_or_create, so it returns the existing active QR (or makes one) and we render it.
function AssetQrRow({ asset, canEditInventory }: { asset: ContentsAsset; canEditInventory: boolean }) {
  const { showToast } = useToast();
  const [qrId, setQrId] = useState<number | null>(null);
  const [showWarranty, setShowWarranty] = useState(false);
  const show = useMutation({
    mutationFn: () => staffRequest<{ id: number }>(`/admin/assets/${asset.id}/qr`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (qr) => setQrId(qr.id),
    onError: (error) => showToast(errorText(error, "Could not load the unit QR"), { tone: "error" }),
  });
  return (
    <Card padding="sm" className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 break-words font-mono text-body-ui text-ink">{asset.asset_tag}</span>
        <StatusWord status={asset.status} />
        <div className="ml-auto flex flex-wrap gap-2">
          <Button size="sm" startIcon={<QrCode />} disabled={Boolean(qrId)} loading={show.isPending} onClick={() => show.mutate()}>{qrId ? "QR shown" : "Show QR"}</Button>
          <Button size="sm" variant="quiet" aria-expanded={showWarranty} onClick={() => setShowWarranty((value) => !value)}>
            {showWarranty ? "Hide warranty" : "Warranty"}
          </Button>
        </div>
      </div>
      {qrId ? <div className="w-32"><QrImage qrId={qrId} label={asset.asset_tag} /></div> : null}
      {show.isError ? <ErrorText message={show.error.message} /> : null}
      {showWarranty ? <WarrantySection hostKind="asset" hostId={asset.id} disabled={!canEditInventory} /> : null}
    </Card>
  );
}

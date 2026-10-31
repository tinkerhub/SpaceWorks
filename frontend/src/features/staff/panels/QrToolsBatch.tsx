import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Download } from "lucide-react";

import { Button, Card, CardHeader, Dialog, EmptyState, ErrorText, Field, Input, Skeleton, useToast } from "../../../components/ui";
import { downloadStaffFile } from "../../../lib/api";
import { errorText } from "./shared";
import { QrImage } from "./QrImage";

type QrCode = { id: number; payload: string; target_type: string; target_id: number };
export type Batch = { id: number; title: string; status: string; created_at: string };
type BatchItem = { id: number; qr_code: QrCode | null; label_text: string; target_type: string; target_id: number };
export type BatchDetail = Batch & { items: BatchItem[] };

/** The working batch: every label collected so far, plus the ZIP download. */
export function BatchLabels({ batchId, batch, loading, error }: { batchId: number; batch?: BatchDetail; loading: boolean; error: unknown }) {
  const { showToast } = useToast();
  const items = batch?.items ?? [];
  const printableCount = items.filter((item) => item.qr_code !== null).length;
  const hasUnavailableLabels = printableCount < items.length;
  const downloadZip = useMutation({
    mutationFn: () => downloadStaffFile(`/admin/qr-print-batches/${batchId}/download`, `qr-batch-${batchId}.zip`),
    onSuccess: () => showToast("Download started", { tone: "success" }),
    onError: (failure) => showToast(errorText(failure, "Could not download the batch"), { tone: "error" }),
  });
  return (
    <Card as="section">
      <CardHeader
        title={batch?.title ?? "Working batch"}
        description={hasUnavailableLabels
          ? `${printableCount} printable of ${items.length} QR labels collected`
          : `${items.length} QR ${items.length === 1 ? "label" : "labels"} collected`}
        action={(
          <Button startIcon={<Download />} disabled={!printableCount} loading={downloadZip.isPending} loadingLabel="Preparing…" onClick={() => downloadZip.mutate()}>
            {hasUnavailableLabels ? "Download available (ZIP)" : "Download all (ZIP)"}
          </Button>
        )}
      />
      {error instanceof Error ? <ErrorText message={error.message} /> : null}
      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-busy="true">
          {[0, 1, 2, 3].map((key) => <Skeleton key={key} className="aspect-square w-full" />)}
        </div>
      ) : !items.length ? (
        <EmptyState title="No QR labels in this batch" description="Pick an inventory item above to add its QR label here." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {items.map((item) => (
            <article key={item.id} className="grid gap-2 rounded-lg border border-line bg-canvas p-3 text-center">
              {item.qr_code !== null ? (
                <QrImage qrId={item.qr_code.id} label={item.label_text} />
              ) : (
                <div className="grid aspect-square place-items-center rounded-md border border-dashed border-line bg-canvas p-2 text-caption text-ink-muted">QR unavailable</div>
              )}
              <p className="text-label text-ink [overflow-wrap:anywhere]">{item.label_text}</p>
              <p className="text-caption text-ink-muted">{sentence(item.target_type)} #{item.target_id}</p>
            </article>
          ))}
        </div>
      )}
      {downloadZip.isError ? <ErrorText message={errorText(downloadZip.error, "Could not download the batch")} /> : null}
    </Card>
  );
}

export function NewBatchDialog({ open, pending, error, onClose, onCreate }: {
  open: boolean;
  pending: boolean;
  error?: string;
  onClose: () => void;
  onCreate: (title: string) => void;
}) {
  const [title, setTitle] = useState("QR labels");
  return (
    <Dialog
      open={open}
      onClose={() => { if (!pending) onClose(); }}
      title="New print batch"
      description="A batch collects QR labels so you can print them in one go."
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button disabled={pending} onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="qr-batch-form" disabled={!title.trim()} loading={pending} loadingLabel="Creating…">Create batch</Button>
        </div>
      )}
    >
      <form id="qr-batch-form" className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (title.trim()) onCreate(title.trim()); }}>
        <Field label="Batch title"><Input value={title} onChange={(event) => setTitle(event.target.value)} /></Field>
        <ErrorText message={error} />
      </form>
    </Dialog>
  );
}

function sentence(value: string) {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

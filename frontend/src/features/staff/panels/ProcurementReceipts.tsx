import { useRef, useState } from "react";
import { Upload } from "lucide-react";

import { Button, ConfirmDialog, ErrorText, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { errorText } from "./shared";

import { useAuthActionOwner } from "../../auth/useAuthActionOwner";
import { getSessionGeneration } from "../../../lib/apiSession";
import { admitUpload, uploadBytes, type UploadGuard } from "../../../lib/uploadProtocol";

export type ToBuyReceipt = {
  id: number;
  created_at: string;
  uploaded_by: number | null;
  uploaded_by_username: string | null;
};

type UploadResponse = {
  object_key: string;
  upload: {
    url: string;
    fields?: Record<string, string>;
    method?: string;
    headers?: Record<string, string>;
  };
};

const acceptedReceiptTypes = "application/pdf,image/jpeg,image/png,image/webp";

type Props = { itemId: number; receipts: ToBuyReceipt[]; onChanged: () => void };
export function ProcurementReceipts(props: Props) {
  return <OwnedProcurementReceipts key={`${props.itemId}:${getSessionGeneration()}`} {...props} />;
}
function OwnedProcurementReceipts({ itemId, receipts, onChanged }: Props) {
  const uploadOwner = useAuthActionOwner(itemId);
  const removeOwner = useAuthActionOwner(itemId);
  const viewOwner = useAuthActionOwner(itemId);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ToBuyReceipt | null>(null);
  const { showToast } = useToast();

  async function upload(files: File[]) {
    if (!uploadOwner.isIntentCurrent()) return;
    const action = uploadOwner.begin();
    if (!action) return;
    const guard = admitUpload(() => uploadOwner.isCurrent(action));
    const batch = [...files];
    setUploading(true);
    setError("");
    try {
      for (const file of batch) await uploadReceipt(itemId, file, guard);
      guard.assertCurrent();
      showToast(batch.length === 1 ? "Receipt added." : `${batch.length} receipts added.`, { tone: "success" });
    } catch (err) {
      if (!uploadOwner.isCurrent(action)) return;
      const message = errorText(err, "Upload failed.");
      setError(message);
      showToast(message, { tone: "error" });
    } finally {
      if (uploadOwner.isCurrent(action)) {
        if (inputRef.current) inputRef.current.value = "";
        // Earlier files may have attached even if a later file failed.
        setUploading(false);
        onChanged();
      }
      uploadOwner.finish(action);
    }
  }
  async function remove() {
    if (!deleteTarget || !removeOwner.isIntentCurrent()) return;
    const action = removeOwner.begin();
    if (!action) return;
    const id = deleteTarget.id;
    setRemoving(true);
    setError("");
    try {
      await staffRequest<void>(`/procurement/to-buy/receipts/${id}`, { method: "DELETE" });
      if (!removeOwner.isCurrent(action)) return;
      setDeleteTarget(null);
      onChanged();
      showToast("Receipt deleted.", { tone: "success" });
    } catch (err) {
      if (!removeOwner.isCurrent(action)) return;
      const message = errorText(err, "Could not delete receipt.");
      setError(message);
      showToast(message, { tone: "error" });
    } finally {
      if (removeOwner.isCurrent(action)) setRemoving(false);
      removeOwner.finish(action);
    }
  }
  async function openReceipt(receiptId: number) {
    if (!viewOwner.isIntentCurrent()) return;
    const action = viewOwner.begin();
    if (!action) return;
    setError("");
    try {
      const { url } = await staffRequest<{ url: string }>(`/procurement/to-buy/receipts/${receiptId}/url`);
      if (viewOwner.isCurrent(action)) window.open(url, "_blank", "noopener");
    } catch (err) {
      if (!viewOwner.isCurrent(action)) return;
      const message = errorText(err, "Could not open receipt.");
      setError(message);
      showToast(message, { tone: "error" });
    } finally {
      viewOwner.finish(action);
    }
  }
  const canSelect = () => uploadOwner.isIntentCurrent() && !uploadOwner.isPending();
  const canRemove = () => removeOwner.isIntentCurrent() && !removeOwner.isPending();

  return (
    <div className="grid gap-3">
      {receipts.length ? (
        <ul className="grid gap-2">
          {receipts.map((receipt) => (
            <li key={receipt.id} className="flex min-w-0 flex-wrap items-center gap-2 rounded-md border border-line bg-canvas px-3 py-2">
              <span className="min-w-0 flex-1 text-body-ui text-ink-secondary">
                {formatDateTime(receipt.created_at)}
                {receipt.uploaded_by_username ? <span className="text-ink-muted"> · {receipt.uploaded_by_username}</span> : null}
              </span>
              <Button size="sm" variant="quiet" onClick={() => openReceipt(receipt.id)}>View</Button>
              <Button size="sm" variant="danger-quiet" disabled={removing} onClick={() => { if (canRemove()) setDeleteTarget(receipt); }}>Delete…</Button>
            </li>
          ))}
        </ul>
      ) : <p className="text-body-ui text-ink-muted">No receipts yet.</p>}
      <div className="flex flex-wrap items-center gap-3">
        {/* The visible button opens this picker; the input itself stays out of the tab order. */}
        <input
          ref={inputRef}
          tabIndex={-1}
          aria-hidden="true"
          type="file"
          multiple
          accept={acceptedReceiptTypes}
          disabled={uploading}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            if (files.length && canSelect()) void upload(files);
          }}
          className="sr-only"
        />
        <Button size="sm" startIcon={<Upload />} loading={uploading} loadingLabel="Uploading…" onClick={() => { if (canSelect()) inputRef.current?.click(); }}>
          Add receipt
        </Button>
        <span className="text-caption text-ink-muted">PDF, JPEG, PNG or WebP</span>
      </div>
      <ErrorText message={error} />
      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="Delete this receipt?"
        message={deleteTarget ? `The receipt added ${formatDateTime(deleteTarget.created_at)} will be removed.` : ""}
        confirmLabel="Delete receipt"
        tone="danger"
        pending={removing}
        onCancel={() => { if (canRemove()) setDeleteTarget(null); }}
        onConfirm={() => { void remove(); }}
      />
    </div>
  );
}

async function uploadReceipt(itemId: number, file: File, guard: UploadGuard = admitUpload()) {
  guard.assertCurrent();
  const presigned = await staffRequest<UploadResponse>(`/procurement/to-buy/${itemId}/receipts/presign`, {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "application/octet-stream",
    }),
  });

  await uploadBytes(file, presigned.upload, guard);
  guard.assertCurrent();

  const receipt = await staffRequest(`/procurement/to-buy/${itemId}/receipts`, {
    method: "POST",
    body: JSON.stringify({ object_key: presigned.object_key }),
  });
  guard.assertCurrent();
  return receipt;
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

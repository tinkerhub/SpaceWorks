import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Upload } from "lucide-react";

import { Button, ConfirmDialog, ErrorText, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { errorText } from "./shared";

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

export function ProcurementReceipts({ itemId, receipts, onChanged }: { itemId: number; receipts: ToBuyReceipt[]; onChanged: () => void }) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ToBuyReceipt | null>(null);
  const { showToast } = useToast();

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      for (const file of files) {
        await uploadReceipt(itemId, file);
      }
      return files.length;
    },
    onSuccess: (count) => {
      setError("");
      if (inputRef.current) inputRef.current.value = "";
      onChanged();
      showToast(count === 1 ? "Receipt added." : `${count} receipts added.`, { tone: "success" });
    },
    onError: (err) => {
      // Files uploaded before the failure are already attached, so refresh either way.
      if (inputRef.current) inputRef.current.value = "";
      onChanged();
      const message = errorText(err, "Upload failed.");
      setError(message);
      showToast(message, { tone: "error" });
    },
  });

  const remove = useMutation({
    mutationFn: (receiptId: number) => staffRequest<void>(`/procurement/to-buy/receipts/${receiptId}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleteTarget(null);
      onChanged();
      showToast("Receipt deleted.", { tone: "success" });
    },
    onError: (err) => {
      const message = errorText(err, "Could not delete receipt.");
      setError(message);
      showToast(message, { tone: "error" });
    },
  });

  async function openReceipt(receiptId: number) {
    setError("");
    try {
      const { url } = await staffRequest<{ url: string }>(`/procurement/to-buy/receipts/${receiptId}/url`);
      window.open(url, "_blank", "noopener");
    } catch (err) {
      const message = errorText(err, "Could not open receipt.");
      setError(message);
      showToast(message, { tone: "error" });
    }
  }

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
              <Button size="sm" variant="danger-quiet" disabled={remove.isPending} onClick={() => setDeleteTarget(receipt)}>Delete…</Button>
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
          disabled={upload.isPending}
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            if (files.length) upload.mutate(files);
          }}
          className="sr-only"
        />
        <Button size="sm" startIcon={<Upload />} loading={upload.isPending} loadingLabel="Uploading…" onClick={() => inputRef.current?.click()}>
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
        pending={remove.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => { if (deleteTarget) remove.mutate(deleteTarget.id); }}
      />
    </div>
  );
}

async function uploadReceipt(itemId: number, file: File) {
  const presigned = await staffRequest<UploadResponse>(`/procurement/to-buy/${itemId}/receipts/presign`, {
    method: "POST",
    body: JSON.stringify({
      filename: file.name,
      content_type: file.type || "application/octet-stream",
    }),
  });

  if (presigned.upload.method === "PUT") {
    const response = await fetch(presigned.upload.url, {
      method: "PUT",
      body: file,
      headers: presigned.upload.headers,
    });
    if (!response.ok) throw new Error(`Storage upload failed (${response.status})`);
  } else {
    const formData = new FormData();
    Object.entries(presigned.upload.fields ?? {}).forEach(([key, value]) => formData.append(key, value));
    formData.append("file", file);
    const response = await fetch(presigned.upload.url, { method: "POST", body: formData });
    if (!response.ok) throw new Error(`Storage upload failed (${response.status})`);
  }

  return staffRequest(`/procurement/to-buy/${itemId}/receipts`, {
    method: "POST",
    body: JSON.stringify({ object_key: presigned.object_key }),
  });
}

function formatDateTime(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

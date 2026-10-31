import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { Button, ConfirmDialog, ErrorText, useToast } from "../../components/ui";
import { useAuthActionOwner } from "../auth/useAuthActionOwner";
import { admitUpload } from "../../lib/uploadProtocol";
import { errorText } from "./panels/shared";
import { deleteWarrantyDocument, getWarrantyDocumentUrl, uploadWarrantyDocument, type WarrantyDocument } from "./warrantyApi";

type Props = { warrantyId: number; documents: WarrantyDocument[]; disabled: boolean; onChanged: () => void };
export function WarrantyDocuments({ warrantyId, documents, disabled, onChanged }: Props) {
  const uploadOwner = useAuthActionOwner(warrantyId);
  const removeOwner = useAuthActionOwner(warrantyId);
  const viewOwner = useAuthActionOwner(warrantyId);
  const inputRef = useRef<HTMLInputElement>(null);
  const { showToast } = useToast();
  const [documentError, setDocumentError] = useState("");
  const [removeTarget, setRemoveTarget] = useState<WarrantyDocument | null>(null);
  const [uploading, setUploading] = useState(false);
  const [removing, setRemoving] = useState(false);
  const canSelect = () => !disabled && uploadOwner.isIntentCurrent() && !uploadOwner.isPending();
  const canRemove = () => !disabled && removeOwner.isIntentCurrent() && !removeOwner.isPending();
  async function upload(files: File[]) {
    if (!canSelect()) return;
    const action = uploadOwner.begin();
    if (!action) return;
    const guard = admitUpload(() => uploadOwner.isCurrent(action));
    const batch = [...files];
    setUploading(true);
    setDocumentError("");
    try {
      for (const file of batch) await uploadWarrantyDocument(warrantyId, file, guard);
      guard.assertCurrent();
      showToast(batch.length === 1 ? "Document attached." : `${batch.length} documents attached.`, { tone: "success" });
    } catch (err) {
      if (!uploadOwner.isCurrent(action)) return;
      const message = errorText(err, "Upload failed.");
      setDocumentError(message);
      showToast(message, { tone: "error" });
    } finally {
      if (uploadOwner.isCurrent(action)) {
        if (inputRef.current) inputRef.current.value = "";
        setUploading(false);
        onChanged(); // Preserve current-target partial success refresh.
      }
      uploadOwner.finish(action);
    }
  }
  async function remove() {
    if (!removeTarget || !canRemove()) return;
    const action = removeOwner.begin();
    if (!action) return;
    const id = removeTarget.id;
    setRemoving(true);
    setDocumentError("");
    try {
      await deleteWarrantyDocument(id);
      if (!removeOwner.isCurrent(action)) return;
      setRemoveTarget(null);
      onChanged();
      showToast("Document removed.", { tone: "success" });
    } catch (err) {
      if (!removeOwner.isCurrent(action)) return;
      const message = errorText(err, "Could not remove document.");
      setDocumentError(message);
      showToast(message, { tone: "error" });
    } finally {
      if (removeOwner.isCurrent(action)) setRemoving(false);
      removeOwner.finish(action);
    }
  }
  async function openDocument(documentId: number) {
    if (!viewOwner.isIntentCurrent()) return;
    const action = viewOwner.begin();
    if (!action) return;
    setDocumentError("");
    try {
      const { url } = await getWarrantyDocumentUrl(documentId);
      if (viewOwner.isCurrent(action)) window.open(url, "_blank", "noopener");
    } catch (err) {
      if (!viewOwner.isCurrent(action)) return;
      const message = errorText(err, "Could not open document.");
      setDocumentError(message);
      showToast(message, { tone: "error" });
    } finally {
      viewOwner.finish(action);
    }
  }
  return (<>
      <div className="grid gap-3 border-t border-line pt-4">
        <h4 className="text-label text-ink">Documents</h4>
        {documents.length ? (
          <ul className="grid gap-2">
            {documents.map((document) => (
              <li key={document.id} className="flex min-w-0 flex-wrap items-center gap-2 rounded-md border border-line bg-canvas px-3 py-2">
                <span className="min-w-0 flex-1 break-words text-body-ui text-ink">{document.original_filename}</span>
                <span className="text-caption tabular-nums text-ink-muted">{formatBytes(document.size_bytes)}</span>
                <Button size="sm" variant="quiet" onClick={() => openDocument(document.id)}>View</Button>
                {!disabled ? (
                  <Button size="sm" variant="danger-quiet" disabled={removing} onClick={() => { if (canRemove()) setRemoveTarget(document); }}>
                    Remove…
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body-ui text-ink-muted">No documents attached.</p>
        )}

        {!disabled ? (
            <div className="flex flex-wrap items-center gap-3">
              {/* The button opens this picker; the input itself stays out of the tab order. */}
              <input
                ref={inputRef}
                type="file"
                multiple
                tabIndex={-1}
                aria-hidden="true"
                accept="application/pdf,image/jpeg,image/png,image/webp"
                disabled={uploading}
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  if (files.length) void upload(files);
                }}
                className="sr-only"
              />
              <Button size="sm" startIcon={<Upload />} loading={uploading} loadingLabel="Uploading…" onClick={() => { if (canSelect()) inputRef.current?.click(); }}>
                Add warranty documents
              </Button>
              <span className="text-caption text-ink-muted">PDF, JPEG, PNG or WebP</span>
            </div>
        ) : null}
        <ErrorText message={documentError} />
      </div>
      <ConfirmDialog
        open={Boolean(removeTarget)}
        title="Remove this document?"
        message={removeTarget ? `${removeTarget.original_filename} will be detached from this warranty.` : ""}
        confirmLabel="Remove document"
        tone="danger"
        pending={removing}
        onCancel={() => { if (canRemove()) setRemoveTarget(null); }}
        onConfirm={() => { void remove(); }}
      />
  </>);
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

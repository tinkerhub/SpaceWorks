import { useRef, useState } from "react";
import { Paperclip } from "lucide-react";

import { Button, ConfirmDialog, Field, Input } from "../../../../components/ui";
import {
  uploadToContract,
  useDeleteMaintenanceDocument,
  useFinalizeMaintenanceDocument,
  useMaintenanceDocumentUrl,
  usePresignMaintenanceDocument,
  type MaintenanceDocument,
} from "./maintenanceApi";
import { formatBytes, useNotify, When } from "./machineUi";

export function MaintenanceDocuments({
  machineId, logId, documents, canDelete, retired,
}: {
  machineId: number;
  logId: number;
  documents: MaintenanceDocument[];
  canDelete: boolean;
  retired: boolean;
}) {
  const notify = useNotify();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pendingKey, setPendingKey] = useState("");
  const [uploadError, setUploadError] = useState<Error | null>(null);
  const [deleteDocumentId, setDeleteDocumentId] = useState<number | null>(null);
  const presign = usePresignMaintenanceDocument(logId);
  const finalize = useFinalizeMaintenanceDocument(machineId, logId);
  const view = useMaintenanceDocumentUrl();
  const remove = useDeleteMaintenanceDocument(machineId, logId);

  const finish = async (key: string) => {
    await finalize.mutateAsync(key);
    setPendingKey("");
    setFile(null);
    if (input.current) input.current.value = "";
    notify.success("Attachment uploaded");
  };
  const fail = (caught: unknown, fallback: string) => {
    const error = caught instanceof Error ? caught : new Error(fallback);
    setUploadError(error);
    notify.failure("Couldn't upload the attachment.", error);
  };
  const upload = async () => {
    if (!file) return;
    setUploadError(null);
    try {
      const contract = await presign.mutateAsync(file);
      await uploadToContract(file, contract);
      setPendingKey(contract.object_key);
      await finish(contract.object_key);
    } catch (caught) {
      fail(caught, "Unable to upload document.");
    }
  };
  const retryFinalize = async () => {
    setUploadError(null);
    try {
      await finish(pendingKey);
    } catch (caught) {
      fail(caught, "Unable to finalize document.");
    }
  };
  const error = uploadError ?? presign.error ?? finalize.error ?? view.error ?? remove.error;
  const uploading = presign.isPending || finalize.isPending;

  return (
    <div className="grid gap-3 border-t border-line pt-3">
      <h4 className="text-label text-ink">Attachments</h4>
      {documents.length ? (
        <ul className="grid gap-1.5">
          {documents.map((document) => (
            <li key={document.id} className="flex flex-wrap items-center gap-2">
              <Paperclip aria-hidden="true" className="size-4 shrink-0 text-ink-muted" />
              <span className="min-w-0 flex-1 text-caption text-ink-secondary">
                Attachment #{document.id} · {formatBytes(document.size_bytes)} · <When value={document.created_at} />
              </span>
              <Button size="sm" variant="quiet" onClick={() => view.mutate(document.id, { onError: (caught) => notify.failure("Couldn't open the attachment.", caught) })}>
                Download
              </Button>
              {canDelete && !retired ? (
                <Button size="sm" variant="danger-quiet" onClick={() => setDeleteDocumentId(document.id)}>Delete…</Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : <p className="text-caption text-ink-muted">No attachments.</p>}
      {!retired ? (
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Add supporting document" className="min-w-0 flex-[1_1_14rem]">
            <Input
              ref={input}
              type="file"
              className="py-2"
              accept=".pdf,.jpg,.jpeg,.png,.webp,.stl,.3mf,.step,.stp,.obj,.amf,.ply,.gcode,.gco,.iges,.igs,.dxf"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setUploadError(null);
              }}
            />
          </Field>
          <Button disabled={!file} loading={uploading} loadingLabel="Uploading…" onClick={() => void upload()}>Upload</Button>
          {pendingKey && finalize.isError ? (
            <Button onClick={() => void retryFinalize()}>Retry finalize</Button>
          ) : null}
        </div>
      ) : null}
      {error instanceof Error ? (
        <p className="text-caption text-danger-fg" role="alert">{error.message}</p>
      ) : null}
      <ConfirmDialog
        open={deleteDocumentId !== null}
        title="Delete maintenance attachment?"
        message="Permanently delete this maintenance attachment?"
        confirmLabel="Delete attachment"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => {
          if (deleteDocumentId !== null) {
            remove.mutate(deleteDocumentId, {
              onSuccess: () => { notify.success("Attachment deleted"); setDeleteDocumentId(null); },
              onError: (caught) => notify.failure("Couldn't delete the attachment.", caught),
            });
          }
        }}
        onCancel={() => setDeleteDocumentId(null)}
      />
    </div>
  );
}

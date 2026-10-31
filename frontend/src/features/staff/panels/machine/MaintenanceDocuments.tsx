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

import { useAuthActionOwner } from "../../../auth/useAuthActionOwner";
import { getSessionGeneration } from "../../../../lib/apiSession";
import { admitUpload, type UploadGuard } from "../../../../lib/uploadProtocol";

type Props = {
  machineId: number;
  logId: number;
  documents: MaintenanceDocument[];
  canDelete: boolean;
  retired: boolean;
};
export function MaintenanceDocuments(props: Props) {
  return <OwnedMaintenanceDocuments key={`${props.machineId}:${props.logId}:${getSessionGeneration()}`} {...props} />;
}
function OwnedMaintenanceDocuments({
  machineId, logId, documents, canDelete, retired,
}: Props) {
  const owner = useAuthActionOwner(`${machineId}:${logId}`);
  const viewOwner = useAuthActionOwner(`${machineId}:${logId}`);
  const removeOwner = useAuthActionOwner(`${machineId}:${logId}`);
  const [uploading, setUploading] = useState(false);
  const [viewing, setViewing] = useState<number | null>(null);
  const [removing, setRemoving] = useState(false);
  const notify = useNotify();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [pendingKey, setPendingKey] = useState<{ key: string; origin: UploadGuard } | null>(null);
  const [uploadError, setUploadError] = useState<Error | null>(null);
  const [deleteDocumentId, setDeleteDocumentId] = useState<number | null>(null);
  const presign = usePresignMaintenanceDocument(logId);
  const finalize = useFinalizeMaintenanceDocument(machineId, logId);
  const view = useMaintenanceDocumentUrl();
  const remove = useDeleteMaintenanceDocument(machineId, logId);

  const finish = async (key: string, guard: UploadGuard) => {
    guard.assertCurrent();
    await finalize.mutateAsync({ key, guard });
    guard.assertCurrent();
    setPendingKey(null);
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
    if (!file || retired || !owner.isIntentCurrent()) return;
    const action = owner.begin();
    if (!action) return;
    const guard = admitUpload(() => owner.isCurrent(action));
    const origin = admitUpload(() => owner.isContextCurrent());
    const selected = file;
    setUploading(true);
    setPendingKey(null);
    setUploadError(null);
    try {
      guard.assertCurrent();
      const contract = await presign.mutateAsync({ file: selected, guard });
      await uploadToContract(selected, contract, guard);
      guard.assertCurrent();
      setPendingKey({ key: contract.object_key, origin });
      await finish(contract.object_key, guard);
    } catch (caught) {
      if (owner.isCurrent(action)) fail(caught, "Unable to upload document.");
    } finally {
      if (owner.isCurrent(action)) setUploading(false);
      owner.finish(action);
    }
  };
  const retryFinalize = async () => {
    if (!pendingKey || retired || !owner.isIntentCurrent() || !pendingKey.origin.isCurrent()) return;
    const retry = pendingKey;
    const action = owner.begin();
    if (!action) return;
    const guard = admitUpload(() => retry.origin.isCurrent() && owner.isCurrent(action));
    setUploading(true);
    setUploadError(null);
    try {
      await finish(retry.key, guard);
    } catch (caught) {
      if (owner.isCurrent(action)) fail(caught, "Unable to finalize document.");
    } finally {
      if (owner.isCurrent(action)) setUploading(false);
      owner.finish(action);
    }
  };
  async function openDocument(id: number) {
    if (!viewOwner.isIntentCurrent()) return;
    const action = viewOwner.begin();
    if (!action) return;
    const guard = admitUpload(() => viewOwner.isCurrent(action));
    setViewing(id);
    setUploadError(null);
    try {
      guard.assertCurrent();
      await view.mutateAsync({ id, guard });
    } catch (caught) {
      if (viewOwner.isCurrent(action)) {
        setUploadError(caught instanceof Error ? caught : new Error("Couldn't open the attachment."));
        notify.failure("Couldn't open the attachment.", caught);
      }
    } finally {
      if (viewOwner.isCurrent(action)) setViewing(null);
      viewOwner.finish(action);
    }
  }
  async function removeDocument() {
    if (deleteDocumentId === null || retired || !canDelete || !removeOwner.isIntentCurrent()) return;
    const id = deleteDocumentId;
    const action = removeOwner.begin();
    if (!action) return;
    const guard = admitUpload(() => removeOwner.isCurrent(action));
    setRemoving(true);
    setUploadError(null);
    try {
      guard.assertCurrent();
      await remove.mutateAsync({ id, guard });
      guard.assertCurrent();
      notify.success("Attachment deleted");
      setDeleteDocumentId(null);
    } catch (caught) {
      if (removeOwner.isCurrent(action)) {
        setUploadError(caught instanceof Error ? caught : new Error("Couldn't delete the attachment."));
        notify.failure("Couldn't delete the attachment.", caught);
      }
    } finally {
      if (removeOwner.isCurrent(action)) setRemoving(false);
      removeOwner.finish(action);
    }
  }
  const canSelect = () => !retired && owner.isIntentCurrent() && !owner.isPending();
  const canRemove = () => removeOwner.isIntentCurrent() && !removeOwner.isPending();
  const error = uploadError;

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
              <Button
                size="sm"
                variant="quiet"
                disabled={viewing !== null}
                loading={viewing === document.id}
                loadingLabel="Opening…"
                onClick={() => { void openDocument(document.id); }}
              >
                Download
              </Button>
              {canDelete && !retired ? (
                <Button size="sm" variant="danger-quiet" disabled={removing} onClick={() => { if (canRemove()) setDeleteDocumentId(document.id); }}>Delete…</Button>
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
              disabled={uploading}
              onChange={(event) => {
                if (!canSelect()) return;
                setPendingKey(null);
                setFile(event.target.files?.[0] ?? null);
                setUploadError(null);
              }}
            />
          </Field>
          <Button disabled={!file} loading={uploading} loadingLabel="Uploading…" onClick={() => void upload()}>Upload</Button>
          {pendingKey && pendingKey.origin.isCurrent() ? (
            <Button disabled={uploading} onClick={() => void retryFinalize()}>Retry finalize</Button>
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
        pending={removing}
        onConfirm={() => { void removeDocument(); }}
        onCancel={() => { if (canRemove()) setDeleteDocumentId(null); }}
      />
    </div>
  );
}

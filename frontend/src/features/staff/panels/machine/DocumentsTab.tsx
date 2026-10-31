import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";

import { Button, Chip, ConfirmDialog, Dropdown, EmptyState, Field, Input, SectionHeading, Skeleton } from "../../../../components/ui";
import {
  collectionResults,
  deleteMachineDocument,
  getMachineDocuments,
  getMachineDocumentUrl,
  machineKeys,
  uploadMachineDocument,
} from "../../machinesApi";
import type { MachineDocument } from "../../machinesApi";
import { formatBytes, useNotify, When } from "./machineUi";

import { useAuthActionOwner } from "../../../auth/useAuthActionOwner";
import { getSessionGeneration } from "../../../../lib/apiSession";
import { admitUpload } from "../../../../lib/uploadProtocol";

// Mirrors backend `MachineDocument.DocType`. The old free-text field accepted anything, so a
// typo uploaded the file to storage and only then failed the finalize step.
const DOC_TYPES = [
  { value: "manual", label: "Manual" },
  { value: "sop", label: "SOP" },
];
const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.stl,.3mf,.step,.stp,.obj,.amf,.ply,.gcode,.gco,.iges,.igs,.dxf";

type Props = { machineId: number; canEdit: boolean };
export function DocumentsTab(props: Props) {
  return <OwnedDocumentsTab key={`${props.machineId}:${getSessionGeneration()}`} {...props} />;
}
function OwnedDocumentsTab({ machineId, canEdit }: Props) {
  const uploadOwner = useAuthActionOwner(machineId);
  const viewOwner = useAuthActionOwner(machineId);
  const removeOwner = useAuthActionOwner(machineId);
  const [uploading, setUploading] = useState(false);
  const [viewing, setViewing] = useState<number | null>(null);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const queryClient = useQueryClient();
  const notify = useNotify();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [docType, setDocType] = useState("manual");
  const [deleting, setDeleting] = useState<MachineDocument | null>(null);
  const documents = useQuery({
    queryKey: machineKeys.documents(machineId),
    queryFn: () => getMachineDocuments(machineId),
  });
  const items = collectionResults(documents.data);
  async function upload() {
    if (!canEdit || !file || !uploadOwner.isIntentCurrent()) return;
    const action = uploadOwner.begin();
    if (!action) return;
    const guard = admitUpload(() => uploadOwner.isCurrent(action));
    const selectedFile = file;
    const selectedType = docType.trim();
    setUploading(true);
    setError(null);
    try {
      const document = await uploadMachineDocument(machineId, selectedFile, selectedType, guard);
      guard.assertCurrent();
      notify.success(`${document?.original_filename ?? selectedFile.name} uploaded`);
      setFile(null);
      setDocType("manual");
      if (fileInput.current) fileInput.current.value = "";
      void queryClient.invalidateQueries({ queryKey: machineKeys.documents(machineId) });
    } catch (caught) {
      if (uploadOwner.isCurrent(action)) {
        setError(caught instanceof Error ? caught : new Error("Couldn't upload the document."));
        notify.failure("Couldn't upload the document.", caught);
      }
    } finally {
      if (uploadOwner.isCurrent(action)) setUploading(false);
      uploadOwner.finish(action);
    }
  }
  async function view(documentId: number) {
    if (!viewOwner.isIntentCurrent()) return;
    const action = viewOwner.begin();
    if (!action) return;
    setViewing(documentId);
    setError(null);
    try {
      const { url } = await getMachineDocumentUrl(documentId);
      if (viewOwner.isCurrent(action)) window.open(url, "_blank", "noopener,noreferrer");
    } catch (caught) {
      if (viewOwner.isCurrent(action)) {
        setError(caught instanceof Error ? caught : new Error("Couldn't open the document."));
        notify.failure("Couldn't open the document.", caught);
      }
    } finally {
      if (viewOwner.isCurrent(action)) setViewing(null);
      viewOwner.finish(action);
    }
  }
  async function remove() {
    if (!canEdit || !deleting || !removeOwner.isIntentCurrent()) return;
    const action = removeOwner.begin();
    if (!action) return;
    const target = { ...deleting };
    setRemoving(true);
    setError(null);
    try {
      await deleteMachineDocument(target.id);
      if (!removeOwner.isCurrent(action)) return;
      notify.success(`${target.original_filename} deleted`);
      setDeleting(null);
      void queryClient.invalidateQueries({ queryKey: machineKeys.documents(machineId) });
    } catch (caught) {
      if (removeOwner.isCurrent(action)) {
        setError(caught instanceof Error ? caught : new Error("Couldn't delete the document."));
        notify.failure("Couldn't delete the document.", caught);
      }
    } finally {
      if (removeOwner.isCurrent(action)) setRemoving(false);
      removeOwner.finish(action);
    }
  }
  const canEditUpload = () => uploadOwner.isIntentCurrent() && !uploadOwner.isPending();

  return (
    <section className="grid gap-4">
      <SectionHeading as="h3" title="Documents" description="Manuals and standard operating procedures, stored privately." />
      {documents.isLoading ? (
        <div className="grid gap-2" role="status" aria-label="Loading documents">
          <Skeleton className="h-14 w-full" />
          <Skeleton className="h-14 w-full" />
        </div>
      ) : null}
      {documents.error instanceof Error ? <EmptyState tone="error" title="Couldn't load documents" description={documents.error.message} /> : null}
      {!documents.isLoading && !documents.error && !items.length ? (
        <EmptyState title="No documents yet" description={canEdit ? "Upload the manual or an SOP below so operators can find it here." : "No manual or SOP has been uploaded for this machine."} />
      ) : null}
      {items.length ? (
        <ul className="grid gap-2">
          {items.map((document) => (
            <li key={document.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-canvas p-3">
              <FileText aria-hidden="true" className="size-5 shrink-0 text-ink-muted" />
              <span className="min-w-0 flex-1">
                <strong className="block truncate text-body-ui font-semibold text-ink">{document.original_filename}</strong>
                <span className="flex flex-wrap items-center gap-x-2 text-caption text-ink-muted">
                  <Chip size="sm">{DOC_TYPES.find((type) => type.value === document.doc_type)?.label ?? document.doc_type}</Chip>
                  {formatBytes(document.size_bytes)} · <When value={document.created_at} />
                </span>
              </span>
              <Button size="sm" disabled={viewing === document.id} onClick={() => void view(document.id)}>View</Button>
              {canEdit ? <Button size="sm" variant="danger-quiet" disabled={removing} onClick={() => { if (removeOwner.isIntentCurrent() && !removeOwner.isPending()) setDeleting(document); }}>Delete…</Button> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {canEdit ? (
        <form className="grid gap-3 rounded-lg border border-line bg-subtle p-4 sm:grid-cols-[minmax(0,1fr)_10rem] items-start"
          onSubmit={(event) => { event.preventDefault(); void upload(); }}>
          <Field label="File" helperText="PDF, image or CAD file.">
            <Input ref={fileInput} type="file" accept={ACCEPT} className="py-2" disabled={uploading} onChange={(event) => { if (canEditUpload()) setFile(event.target.files?.[0] ?? null); }} required />
          </Field>
          <Field label="Document type">
            <Dropdown value={docType} disabled={uploading} onChange={(event) => { if (canEditUpload()) setDocType(event.target.value); }} required>
              {DOC_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
            </Dropdown>
          </Field>
          <div className="flex justify-end sm:col-span-2">
            <Button variant="primary" type="submit" loading={uploading} loadingLabel="Uploading…" disabled={!file || !docType.trim()}>Upload</Button>
          </div>
        </form>
      ) : null}
      {error ? <p className="text-caption text-danger-fg">{error.message}</p> : null}
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.original_filename ?? "this document"}?`}
        message="The file is removed from storage for good."
        confirmLabel="Delete document"
        tone="danger"
        pending={removing}
        onConfirm={() => { void remove(); }}
        onCancel={() => { if (removeOwner.isIntentCurrent() && !removeOwner.isPending()) setDeleting(null); }}
      />
    </section>
  );
}

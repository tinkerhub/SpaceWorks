import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

// Mirrors backend `MachineDocument.DocType`. The old free-text field accepted anything, so a
// typo uploaded the file to storage and only then failed the finalize step.
const DOC_TYPES = [
  { value: "manual", label: "Manual" },
  { value: "sop", label: "SOP" },
];
const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,.stl,.3mf,.step,.stp,.obj,.amf,.ply,.gcode,.gco,.iges,.igs,.dxf";

export function DocumentsTab({ machineId, canEdit }: { machineId: number; canEdit: boolean }) {
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
  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose a document to upload");
      return uploadMachineDocument(machineId, file, docType.trim());
    },
    onSuccess: async (document) => {
      notify.success(`${document?.original_filename ?? file?.name ?? "Document"} uploaded`);
      setFile(null);
      setDocType("manual");
      if (fileInput.current) fileInput.current.value = "";
      await queryClient.invalidateQueries({ queryKey: machineKeys.documents(machineId) });
    },
    onError: (error) => notify.failure("Couldn't upload the document.", error),
  });
  const view = useMutation({
    mutationFn: (documentId: number) => getMachineDocumentUrl(documentId),
    onSuccess: ({ url }) => window.open(url, "_blank", "noopener,noreferrer"),
    onError: (error) => notify.failure("Couldn't open the document.", error),
  });
  const remove = useMutation({
    mutationFn: deleteMachineDocument,
    onSuccess: async () => {
      notify.success(`${deleting?.original_filename ?? "Document"} deleted`);
      setDeleting(null);
      await queryClient.invalidateQueries({ queryKey: machineKeys.documents(machineId) });
    },
    onError: (error) => notify.failure("Couldn't delete the document.", error),
  });

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
              <Button size="sm" disabled={view.isPending && view.variables === document.id} onClick={() => view.mutate(document.id)}>View</Button>
              {canEdit ? <Button size="sm" variant="danger-quiet" onClick={() => setDeleting(document)}>Delete…</Button> : null}
            </li>
          ))}
        </ul>
      ) : null}
      {canEdit ? (
        <form className="grid gap-3 rounded-lg border border-line bg-subtle p-4 sm:grid-cols-[minmax(0,1fr)_10rem] items-start"
          onSubmit={(event) => { event.preventDefault(); upload.mutate(); }}>
          <Field label="File" helperText="PDF, image or CAD file.">
            <Input ref={fileInput} type="file" accept={ACCEPT} className="py-2" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required />
          </Field>
          <Field label="Document type">
            <Dropdown value={docType} onChange={(event) => setDocType(event.target.value)} required>
              {DOC_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
            </Dropdown>
          </Field>
          <div className="flex justify-end sm:col-span-2">
            <Button variant="primary" type="submit" loading={upload.isPending} loadingLabel="Uploading…" disabled={!file || !docType.trim()}>Upload</Button>
          </div>
        </form>
      ) : null}
      {[upload.error, view.error, remove.error].map((error, index) => error instanceof Error
        ? <p key={index} className="text-caption text-danger-fg">{error.message}</p> : null)}
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.original_filename ?? "this document"}?`}
        message="The file is removed from storage for good."
        confirmLabel="Delete document"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => { if (deleting) remove.mutate(deleting.id); }}
        onCancel={() => setDeleting(null)}
      />
    </section>
  );
}

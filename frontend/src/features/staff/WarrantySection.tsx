import { useEffect, useId, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";

import { Button, ConfirmDialog, ErrorText, Field, Input, Skeleton, useToast } from "../../components/ui";
import { errorText } from "./panels/shared";
import { WarrantyStatusBadge } from "./WarrantyStatusBadge";
import {
  deleteWarrantyDocument,
  getWarranty,
  getWarrantyDocumentUrl,
  saveWarranty,
  uploadWarrantyDocument,
  type Warranty,
  type WarrantyDocument,
  type WarrantyHostKind,
  type WarrantyPayload,
} from "./warrantyApi";

type WarrantySectionProps = {
  hostKind: WarrantyHostKind;
  hostId: number;
  disabled?: boolean;
};

type WarrantyForm = {
  purchased_on: string;
  warranty_expires_on: string;
  vendor_name: string;
  vendor_contact: string;
};

const emptyForm: WarrantyForm = {
  purchased_on: "",
  warranty_expires_on: "",
  vendor_name: "",
  vendor_contact: "",
};

const acceptedDocumentTypes = "application/pdf,image/jpeg,image/png,image/webp";

export function WarrantySection({ hostKind, hostId, disabled = false }: WarrantySectionProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const headingId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const queryKey = ["warranty", hostKind, hostId] as const;
  const warranty = useQuery({
    queryKey,
    queryFn: () => getWarranty(hostKind, hostId),
  });
  const [form, setForm] = useState<WarrantyForm>(emptyForm);
  const [documentError, setDocumentError] = useState("");
  const [removeTarget, setRemoveTarget] = useState<WarrantyDocument | null>(null);

  useEffect(() => {
    setForm(formFromWarranty(warranty.data ?? null));
  }, [warranty.data]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey });
    queryClient.invalidateQueries({ queryKey: ["warranties"] });
  };

  const save = useMutation({
    mutationFn: () => saveWarranty(hostKind, hostId, payloadFromForm(form)),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKey, updated);
      queryClient.invalidateQueries({ queryKey: ["warranties"] });
      showToast("Warranty saved.", { tone: "success" });
    },
    onError: (err) => showToast(errorText(err, "Could not save warranty."), { tone: "error" }),
  });

  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      if (!warranty.data) throw new Error("Save warranty details first to attach documents.");
      for (const file of files) {
        await uploadWarrantyDocument(warranty.data.id, file);
      }
      return files.length;
    },
    onSuccess: (count) => {
      setDocumentError("");
      if (inputRef.current) inputRef.current.value = "";
      invalidate();
      showToast(count === 1 ? "Document attached." : `${count} documents attached.`, { tone: "success" });
    },
    onError: (err) => {
      // Files uploaded before the failing one are attached already; show them.
      if (inputRef.current) inputRef.current.value = "";
      invalidate();
      const message = errorText(err, "Upload failed.");
      setDocumentError(message);
      showToast(message, { tone: "error" });
    },
  });

  const remove = useMutation({
    mutationFn: deleteWarrantyDocument,
    onSuccess: () => {
      setRemoveTarget(null);
      invalidate();
      showToast("Document removed.", { tone: "success" });
    },
    onError: (err) => showToast(errorText(err, "Could not remove document."), { tone: "error" }),
  });

  const current = warranty.data;
  const documents = current?.documents ?? [];
  const fieldsDisabled = disabled || save.isPending;
  const setField = (field: keyof WarrantyForm) => (value: string) => setForm((currentForm) => ({ ...currentForm, [field]: value }));

  async function openDocument(documentId: number) {
    setDocumentError("");
    try {
      const { url } = await getWarrantyDocumentUrl(documentId);
      window.open(url, "_blank", "noopener");
    } catch (err) {
      const message = errorText(err, "Could not open document.");
      setDocumentError(message);
      showToast(message, { tone: "error" });
    }
  }

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-4 rounded-lg border border-line bg-canvas p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="text-title text-ink">Warranty</h3>
        <WarrantyStatusBadge status={current?.status ?? "unknown"} />
      </div>

      {warranty.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      {warranty.error ? <ErrorText message={errorText(warranty.error, "Could not load the warranty.")} /> : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <WarrantyInput label="Purchased" type="date" value={form.purchased_on} disabled={fieldsDisabled} onChange={setField("purchased_on")} />
        <WarrantyInput label="Expires" type="date" value={form.warranty_expires_on} disabled={fieldsDisabled} onChange={setField("warranty_expires_on")} />
        <WarrantyInput label="Vendor" value={form.vendor_name} disabled={fieldsDisabled} onChange={setField("vendor_name")} />
        <WarrantyInput label="Contact" value={form.vendor_contact} disabled={fieldsDisabled} onChange={setField("vendor_contact")} />
      </div>

      {!disabled ? (
        <div className="grid gap-2">
          <div>
            <Button variant="primary" size="sm" loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>
              {current ? "Save warranty" : "Create warranty"}
            </Button>
          </div>
          {save.error ? <ErrorText message={errorText(save.error, "Could not save warranty.")} /> : null}
        </div>
      ) : null}

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
                  <Button size="sm" variant="danger-quiet" disabled={remove.isPending} onClick={() => setRemoveTarget(document)}>
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
          current ? (
            <div className="flex flex-wrap items-center gap-3">
              {/* The button opens this picker; the input itself stays out of the tab order. */}
              <input
                ref={inputRef}
                type="file"
                multiple
                tabIndex={-1}
                aria-hidden="true"
                accept={acceptedDocumentTypes}
                disabled={upload.isPending}
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  if (files.length) upload.mutate(files);
                }}
                className="sr-only"
              />
              <Button size="sm" startIcon={<Upload />} loading={upload.isPending} loadingLabel="Uploading…" onClick={() => inputRef.current?.click()}>
                Add warranty documents
              </Button>
              <span className="text-caption text-ink-muted">PDF, JPEG, PNG or WebP</span>
            </div>
          ) : (
            <p className="text-caption text-ink-muted">Save warranty details first to attach documents.</p>
          )
        ) : null}
        <ErrorText message={documentError} />
        {remove.error ? <ErrorText message={errorText(remove.error, "Could not remove document.")} /> : null}
      </div>
      <ConfirmDialog
        open={Boolean(removeTarget)}
        title="Remove this document?"
        message={removeTarget ? `${removeTarget.original_filename} will be detached from this warranty.` : ""}
        confirmLabel="Remove document"
        tone="danger"
        pending={remove.isPending}
        onCancel={() => setRemoveTarget(null)}
        onConfirm={() => { if (removeTarget) remove.mutate(removeTarget.id); }}
      />
    </section>
  );
}

function WarrantyInput({
  label,
  value,
  onChange,
  disabled,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
  type?: "text" | "date";
}) {
  return (
    <Field label={label}>
      <Input type={type} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

function formFromWarranty(warranty: Warranty | null): WarrantyForm {
  if (!warranty) return emptyForm;
  return {
    purchased_on: warranty.purchased_on ?? "",
    warranty_expires_on: warranty.warranty_expires_on ?? "",
    vendor_name: warranty.vendor_name ?? "",
    vendor_contact: warranty.vendor_contact ?? "",
  };
}

function payloadFromForm(form: WarrantyForm): WarrantyPayload {
  return {
    purchased_on: form.purchased_on || null,
    warranty_expires_on: form.warranty_expires_on || null,
    vendor_name: form.vendor_name.trim(),
    vendor_contact: form.vendor_contact.trim(),
  };
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

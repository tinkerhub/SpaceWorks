import { useEffect, useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, ErrorText, Field, Input, Skeleton, useToast } from "../../components/ui";
import { errorText } from "./panels/shared";
import { WarrantyStatusBadge } from "./WarrantyStatusBadge";
import {
  getWarranty,
  saveWarranty,
  type Warranty,
  type WarrantyHostKind,
  type WarrantyPayload,
} from "./warrantyApi";

import { WarrantyDocuments } from "./WarrantyDocuments";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";
import { getSessionGeneration } from "../../lib/apiSession";

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

export function WarrantySection(props: WarrantySectionProps) {
  return <OwnedWarrantySection key={`${props.hostKind}:${props.hostId}:${getSessionGeneration()}`} {...props} />;
}
function OwnedWarrantySection({ hostKind, hostId, disabled = false }: WarrantySectionProps) {
  const owner = useAuthActionOwner(`${hostKind}:${hostId}`);
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const headingId = useId();
  const queryKey = ["warranty", hostKind, hostId] as const;
  const warranty = useQuery({
    queryKey,
    queryFn: () => getWarranty(hostKind, hostId),
  });
  const [editor, setEditor] = useState({ values: emptyForm, initialized: false, dirty: false });
  const form = editor.values;

  const metadata = warranty.data === undefined ? undefined : JSON.stringify(formFromWarranty(warranty.data));
  useEffect(() => {
    if (metadata === undefined) return;
    const values = JSON.parse(metadata) as WarrantyForm;
    // Read dirty state when applying the update, so a late refetch cannot erase edits.
    setEditor((currentEditor) => currentEditor.dirty ? currentEditor : { values, initialized: true, dirty: false });
  }, [metadata]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey });
    queryClient.invalidateQueries({ queryKey: ["warranties"] });
  };

  const save = useMutation({
    mutationFn: ({ action, payload }: { action: AuthAction; payload: WarrantyPayload }) => {
      if (!owner.isCurrent(action)) throw new Error("This warranty edit is no longer current.");
      return saveWarranty(hostKind, hostId, payload);
    },
    onSuccess: (updated, { action }) => {
      if (!owner.isCurrent(action)) return;
      setEditor({ values: formFromWarranty(updated), initialized: true, dirty: false });
      queryClient.setQueryData(queryKey, updated);
      queryClient.invalidateQueries({ queryKey: ["warranties"] });
      showToast("Warranty saved.", { tone: "success" });
    },
    onError: (err, { action }) => {
      if (owner.isCurrent(action)) showToast(errorText(err, "Could not save warranty."), { tone: "error" });
    },
    onSettled: (_result, _error, { action }) => { owner.finish(action); },
  });

  const current = warranty.data;
  const saving = owner.isCurrent(save.variables?.action ?? null) && save.isPending;
  const saveError = owner.isCurrent(save.variables?.action ?? null) ? save.error : null;
  const formReady = editor.initialized && warranty.data !== undefined;
  const fieldsDisabled = disabled || saving || !formReady;
  const setField = (field: keyof WarrantyForm) => (value: string) => {
    if (fieldsDisabled || !owner.isIntentCurrent() || owner.isPending()) return;
    setEditor((currentEditor) => ({
      ...currentEditor, values: { ...currentEditor.values, [field]: value }, dirty: true,
    }));
  };
  function submitSave() {
    if (fieldsDisabled || !owner.isIntentCurrent() || owner.isPending()) return;
    const payload = payloadFromForm(form);
    const action = owner.begin();
    if (action) save.mutate({ action, payload });
  }

  return (
    <section aria-labelledby={headingId} className="grid min-w-0 gap-4 rounded-lg border border-line bg-canvas p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={headingId} className="text-title text-ink">Warranty</h3>
        <WarrantyStatusBadge status={current?.status ?? "unknown"} />
      </div>

      {warranty.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      {warranty.error ? <ErrorText message={errorText(warranty.error, "Could not load the warranty.")} /> : null}
      {warranty.error && warranty.data === undefined ? (
        <div>
          <Button size="sm" variant="quiet" disabled={warranty.isFetching} onClick={() => {
            if (owner.isIntentCurrent() && !owner.isPending() && !warranty.isFetching) void warranty.refetch();
          }}>Retry</Button>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <WarrantyInput label="Purchased" type="date" value={form.purchased_on} disabled={fieldsDisabled} onChange={setField("purchased_on")} />
        <WarrantyInput label="Expires" type="date" value={form.warranty_expires_on} disabled={fieldsDisabled} onChange={setField("warranty_expires_on")} />
        <WarrantyInput label="Vendor" value={form.vendor_name} disabled={fieldsDisabled} onChange={setField("vendor_name")} />
        <WarrantyInput label="Contact" value={form.vendor_contact} disabled={fieldsDisabled} onChange={setField("vendor_contact")} />
      </div>

      {!disabled ? (
        <div className="grid gap-2">
          <div>
            <Button variant="primary" size="sm" disabled={fieldsDisabled} loading={saving} loadingLabel="Saving…" onClick={submitSave}>
              {current ? "Save warranty" : "Create warranty"}
            </Button>
          </div>
          {saveError ? <ErrorText message={errorText(saveError, "Could not save warranty.")} /> : null}
        </div>
      ) : null}

      {current ? <WarrantyDocuments key={current.id} warrantyId={current.id} documents={current.documents} disabled={disabled} onChanged={invalidate} />
        : <p className="text-caption text-ink-muted">Save warranty details first to attach documents.</p>}

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

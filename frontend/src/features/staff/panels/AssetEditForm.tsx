import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, Callout, CheckboxField, Dropdown, ErrorText, Field, Input, Textarea, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { errorText } from "./shared";

type AssetEditRow = {
  id: number;
  asset_tag: string;
  serial_number: string;
  status: string;
  box: number | null;
  notes: string;
  public_self_checkout_enabled: boolean;
};

type ContainerOption = { id: number; label: string };

const LOCKED_STATUSES = ["issued", "reserved"];

export function AssetEditForm({
  asset,
  containers,
  onSaved,
  onCancel,
}: {
  asset: AssetEditRow;
  containers: ContainerOption[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const { showToast } = useToast();
  const [assetTag, setAssetTag] = useState(asset.asset_tag);
  const [serial, setSerial] = useState(asset.serial_number);
  const [boxId, setBoxId] = useState(asset.box ? String(asset.box) : "");
  const [notes, setNotes] = useState(asset.notes ?? "");
  const [publicEnabled, setPublicEnabled] = useState(asset.public_self_checkout_enabled);
  const locked = LOCKED_STATUSES.includes(asset.status);

  const save = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/assets/${asset.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          asset_tag: assetTag.trim(),
          serial_number: serial.trim(),
          box: boxId ? Number(boxId) : null,
          notes: notes.trim(),
          public_self_checkout_enabled: publicEnabled,
        }),
      }),
    onSuccess: () => {
      showToast(`${assetTag.trim()} saved`, { tone: "success" });
      onSaved();
    },
    onError: (error) => showToast(errorText(error, "Could not save the asset."), { tone: "error" }),
  });

  if (locked) {
    return (
      <Callout tone="warning" title={`This asset is ${asset.status}.`}>
        Finish its loan before editing its details.
      </Callout>
    );
  }

  return (
    <form
      className="grid gap-4 rounded-md bg-subtle p-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (assetTag.trim()) save.mutate();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Asset tag"><Input value={assetTag} onChange={(e) => setAssetTag(e.target.value)} required /></Field>
        <Field label="Serial number" optional><Input value={serial} onChange={(e) => setSerial(e.target.value)} /></Field>
      </div>
      <Field label="Container">
        <Dropdown value={boxId} onChange={(e) => setBoxId(e.target.value)}>
          <option value="">No container</option>
          {containers.map((container) => (
            <option key={container.id} value={String(container.id)}>{container.label}</option>
          ))}
        </Dropdown>
      </Field>
      <Field label="Notes" optional><Textarea rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      <CheckboxField label="Enabled for public self-checkout" checked={publicEnabled} onCheckedChange={(checked) => setPublicEnabled(checked === true)} />
      <ErrorText message={save.error?.message} />
      <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
        <Button size="sm" disabled={save.isPending} onClick={onCancel}>Cancel</Button>
        <Button size="sm" variant="secondary" type="submit" loading={save.isPending} loadingLabel="Saving…" disabled={!assetTag.trim()}>Save asset</Button>
      </div>
    </form>
  );
}

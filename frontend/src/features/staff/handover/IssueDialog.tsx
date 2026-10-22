import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, DetailDrawer, Field, Input, Textarea, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { EvidenceUpload } from "../panels/EvidenceUpload";
import { errorText } from "../panels/shared";
import { DialogError, submit } from "./shared";
import type { DialogProps } from "./types";

export function IssueDialog({ row, makerspace, onClose }: DialogProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [remark, setRemark] = useState("");
  const [assetInputs, setAssetInputs] = useState<Record<string, string>>({});
  const individualItems = row.items.filter((item) => item.tracking_mode === "individual");
  const assetFields = individualItems.flatMap((item) =>
    Array.from({ length: item.accepted_quantity }, (_, index) => ({
      key: `${item.id}-${index}`,
      label: `${item.product_name} unit ${index + 1} asset QR`,
    })),
  );
  const requiredAssetCount = individualItems.reduce((total, item) => total + item.accepted_quantity, 0);
  const assetQrPayloads = assetFields.map((field) => assetInputs[field.key]?.trim() ?? "").filter(Boolean);
  const mutation = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/requests/${row.id}/issue`, {
        method: "POST",
        body: JSON.stringify({
          evidence_id: evidenceId,
          remark: remark.trim(),
          asset_qr_payloads: assetQrPayloads,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      showToast(`Request #${row.id} issued.`, { tone: "success" });
      onClose();
    },
    onError: (failure) => showToast(errorText(failure, "Could not issue the request."), { tone: "error" }),
  });
  const canSubmit = Boolean(evidenceId) && assetQrPayloads.length === requiredAssetCount;
  const close = () => {
    if (!mutation.isPending) onClose();
  };

  return (
    <DetailDrawer open title={`Issue request #${row.id}`} onClose={close}>
      <form
        className="grid gap-5"
        onSubmit={(event) => submit(event, () => {
          if (canSubmit) mutation.mutate();
        })}
      >
        {row.assigned_box_code ? (
          <Callout tone="info" title="Assigned box">
            <span className="font-mono">{row.assigned_box_code}</span>
          </Callout>
        ) : (
          <Callout tone="warning" title="No box is assigned to this request.">
            Assign and scan a box before issuing.
          </Callout>
        )}
        <EvidenceUpload makerspaceId={makerspace.id} evidenceType="issue" label="Evidence photo" disabled={mutation.isPending} onUploaded={setEvidenceId} />
        <Field label="Remark" optional>
          <Textarea value={remark} onChange={(event) => setRemark(event.target.value)} />
        </Field>
        {individualItems.length ? (
          <fieldset className="grid gap-3">
            <legend className="mb-1 text-label text-ink">Asset QR codes</legend>
            {assetFields.map((field) => (
              <Field key={field.key} label={field.label}>
                <Input
                  className="font-mono"
                  value={assetInputs[field.key] ?? ""}
                  onChange={(event) => setAssetInputs((current) => ({ ...current, [field.key]: event.target.value }))}
                />
              </Field>
            ))}
          </fieldset>
        ) : null}
        <DialogError error={mutation.error} />
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button disabled={mutation.isPending} onClick={close}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={!canSubmit} loading={mutation.isPending} loadingLabel="Issuing…">
            Issue
          </Button>
        </div>
      </form>
    </DetailDrawer>
  );
}

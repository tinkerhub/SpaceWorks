import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, DetailDrawer, Field, Input, Textarea, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { EvidenceUpload } from "../panels/EvidenceUpload";
import { errorText } from "../panels/shared";
import {
  defaultReturnValues,
  DialogError,
  parseReturnValues,
  QuantityInput,
  remainingQuantity,
  submit,
  updateReturnValue,
  valuesAreValid,
} from "./shared";
import type { DialogProps, ReturnValues } from "./types";

export function ReturnDialog({ row, makerspace, onClose }: DialogProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [boxCode, setBoxCode] = useState(row.assigned_box_code ?? "");
  const [remark, setRemark] = useState("");
  const [values, setValues] = useState<Record<number, ReturnValues>>(() => defaultReturnValues(row));
  const rows = useMemo(
    () =>
      row.items.map((item) => {
        const remaining = remainingQuantity(item);
        const value = values[item.id] ?? { returned: "0", damaged: "0", missing: "0" };
        const parsed = parseReturnValues(value);
        const total = parsed.returned + parsed.damaged + parsed.missing;
        return {
          item,
          remaining,
          value,
          parsed,
          total,
          valid: valuesAreValid(parsed) && total <= remaining,
        };
      }),
    [row, values],
  );
  const resolutions = rows
    .map(({ item, parsed }) => ({ item_id: item.id, ...parsed }))
    .filter((resolution) => resolution.returned + resolution.damaged + resolution.missing > 0);
  const hasInvalidRow = rows.some((returnRow) => !returnRow.valid);
  const mutation = useMutation({
    mutationFn: () =>
      staffRequest(`/admin/requests/${row.id}/return`, {
        method: "POST",
        body: JSON.stringify({
          evidence_id: evidenceId,
          box_code: boxCode.trim(),
          remark: remark.trim(),
          resolutions,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries();
      showToast(`Return recorded for request #${row.id}.`, { tone: "success" });
      onClose();
    },
    onError: (failure) => showToast(errorText(failure, "Could not record the return."), { tone: "error" }),
  });
  const canSubmit = Boolean(evidenceId) && Boolean(remark.trim()) && resolutions.length > 0 && !hasInvalidRow;

  const close = () => {
    if (!mutation.isPending) onClose();
  };

  // Reset only when a different request opens. Keyed on the object, every background
  // refetch (a new `row` with the same id) wiped the half-filled form and the uploaded
  // photo id while the upload still showed as done, silently disabling Return.
  useEffect(() => {
    setEvidenceId(null);
    setBoxCode(row.assigned_box_code ?? "");
    setRemark("");
    setValues(defaultReturnValues(row));
  }, [row.id]);

  return (
    <DetailDrawer open title={`Return request #${row.id}`} onClose={close}>
      <form
        className="grid gap-5"
        onSubmit={(event) => submit(event, () => {
          if (canSubmit) mutation.mutate();
        })}
      >
        <EvidenceUpload key={row.id} makerspaceId={makerspace.id} evidenceType="return" label="Evidence photo" disabled={mutation.isPending} onUploaded={setEvidenceId} />
        <Field label="Box QR code">
          <Input className="font-mono" value={boxCode} onChange={(event) => setBoxCode(event.target.value)} />
        </Field>
        <fieldset className="grid gap-3">
          <legend className="mb-1 text-label text-ink">Return quantities</legend>
          {rows.map(({ item, remaining, value, total, valid }) => (
            <div key={item.id} className="grid gap-3 rounded-lg border border-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-label text-ink">{item.product_name}</span>
                <span className="text-caption text-ink-muted">{remaining} remaining</span>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                <QuantityInput label="Returned" value={value.returned} onChange={(next) => updateReturnValue(setValues, item.id, "returned", next)} />
                <QuantityInput label="Damaged" value={value.damaged} onChange={(next) => updateReturnValue(setValues, item.id, "damaged", next)} />
                <QuantityInput label="Missing" value={value.missing} onChange={(next) => updateReturnValue(setValues, item.id, "missing", next)} />
              </div>
              {!valid ? (
                <p className="text-caption text-danger-fg">
                  Row total must be between 0 and {remaining}. Current total: {total}.
                </p>
              ) : null}
            </div>
          ))}
        </fieldset>
        <Field label="Remark" helperText="Required. Note the condition of what came back.">
          <Textarea required value={remark} onChange={(event) => setRemark(event.target.value)} />
        </Field>
        <DialogError error={mutation.error} />
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button disabled={mutation.isPending} onClick={close}>Cancel</Button>
          <Button variant="primary" type="submit" disabled={!canSubmit} loading={mutation.isPending} loadingLabel="Returning…">
            Return
          </Button>
        </div>
      </form>
    </DetailDrawer>
  );
}

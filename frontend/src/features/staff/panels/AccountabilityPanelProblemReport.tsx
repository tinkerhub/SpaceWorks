import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, Card, ErrorText, Field, Input, SegmentedControl, Textarea, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { OUTCOME_OPTIONS, type ProblemReport, type TriageOutcome } from "./AccountabilityPanelTypes";
import { errorText, type Makerspace } from "./shared";

/** One open problem report from a public return, with its triage form. */
export function ProblemReportCard({ row, makerspace, onTriaged }: { row: ProblemReport; makerspace: Makerspace; onTriaged: () => void }) {
  const { showToast } = useToast();
  const [outcome, setOutcome] = useState<TriageOutcome>("no_issue");
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [note, setNote] = useState("");
  const actionable = outcome !== "no_issue";
  const resolutions = actionable
    ? row.items
        .map((item) => ({ item_id: item.id, quantity: Number(quantities[item.id] || 0) }))
        .filter((resolution) => resolution.quantity > 0)
    : [];
  const triage = useMutation({
    mutationFn: () => staffRequest(`/admin/makerspace/${makerspace.id}/problem-reports/${row.id}/triage`, {
      method: "POST",
      body: JSON.stringify({ outcome, resolutions, note }),
    }),
    onSuccess: () => {
      showToast(`Triage saved for ${row.label || "the tool"}.`, { tone: "success" });
      onTriaged();
    },
    onError: (error) => showToast(errorText(error, "Could not save triage."), { tone: "error" }),
  });

  return (
    <Card as="article" className="grid gap-4">
      <div className="min-w-0">
        <h3 className="text-label text-ink">{row.label || "(tool)"}</h3>
        <p className="text-caption text-ink-muted">{row.requester_username} · {new Date(row.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</p>
        {row.note ? <p className="mt-2 break-words text-body-ui text-ink">{row.note}</p> : null}
      </div>
      <SegmentedControl<TriageOutcome>
        ariaLabel={`Outcome for ${row.label || "this report"}`}
        size="sm"
        value={outcome}
        onValueChange={setOutcome}
        options={OUTCOME_OPTIONS}
        className="w-max max-w-full flex-wrap"
      />
      {actionable ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {row.items.map((item) => (
            <Field key={item.id} label={`${item.product_name} (${item.issued_quantity} issued)`}>
              <Input
                type="number"
                min={0}
                max={item.issued_quantity}
                value={quantities[item.id] ?? ""}
                onChange={(event) => setQuantities((current) => ({ ...current, [item.id]: event.target.value }))}
                placeholder="0"
              />
            </Field>
          ))}
        </div>
      ) : null}
      <Field label="Triage note" optional><Textarea rows={3} value={note} onChange={(event) => setNote(event.target.value)} /></Field>
      {triage.error ? <ErrorText message={errorText(triage.error, "Could not save triage.")} /> : null}
      <div className="flex flex-wrap items-center justify-end gap-3">
        {actionable && resolutions.length === 0 ? <span className="text-caption text-ink-muted">Enter how many units this applies to.</span> : null}
        <Button size="sm" loading={triage.isPending} loadingLabel="Saving…" disabled={actionable && resolutions.length === 0} onClick={() => triage.mutate()}>
          Save triage
        </Button>
      </div>
    </Card>
  );
}

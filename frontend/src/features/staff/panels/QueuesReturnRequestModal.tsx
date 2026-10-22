import { useEffect, useState } from "react";

import { ErrorText, Dropdown, Field, Input, Modal, SectionHeading, Textarea } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { evidenceErrorText } from "../evidenceUi";
import { EvidenceUpload } from "./EvidenceUpload";
import { BoxCodeField, FormFooter, ShelfLine, submitForm } from "./QueuesModalShared";
import type { AssetReturnOutcome, FormModalProps, ReturnRequestValues } from "./QueuesModalTypes";

type PendingOutcome = AssetReturnOutcome | "pending";

type AssetOutcomeState = Record<number, Record<number, PendingOutcome>>;

export function ReturnRequestModal({ row, open, pending, error, onClose, onSubmit, makerspaceId }: FormModalProps<ReturnRequestValues> & { makerspaceId: number }) {
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [boxCode, setBoxCode] = useState(row?.assigned_box?.code ?? "");
  const [remark, setRemark] = useState("");
  const [resolutions, setResolutions] = useState<ReturnRequestValues["resolutions"]>([]);
  const [assetOutcomes, setAssetOutcomes] = useState<AssetOutcomeState>({});
  const [validationError, setValidationError] = useState("");
  const [issueUrl, setIssueUrl] = useState("");
  const [issueError, setIssueError] = useState("");

  useEffect(() => {
    if (!open || !row) {
      setIssueUrl("");
      setIssueError("");
      return;
    }
    setEvidenceId(null);
    setBoxCode(row.assigned_box?.code ?? "");
    setRemark("");
    setValidationError("");
    setIssueUrl("");
    setIssueError("");
    setResolutions(row.items.map((item) => item.requires_asset_qr ? { item_id: item.id, returned: 0, damaged: 0, missing: 0, assets: [] } : {
      item_id: item.id,
      returned: remainingCount(item),
      damaged: 0,
      missing: 0,
    }));
    setAssetOutcomes(Object.fromEntries(row.items.filter((item) => item.requires_asset_qr).map((item) => [item.id, Object.fromEntries((item.issued_assets ?? []).map((asset) => [asset.asset_id, "returned"]))])));
  }, [open, row]);

  useEffect(() => {
    if (!open || !row?.issue_evidence_id) {
      setIssueUrl("");
      setIssueError("");
      return;
    }
    let cancelled = false;
    staffRequest<{ url: string }>(`/admin/evidence/${row.issue_evidence_id}`)
      .then((result) => {
        if (!cancelled) setIssueUrl(result.url);
      })
      .catch((loadError) => {
        if (!cancelled) {
          setIssueUrl("");
          setIssueError(evidenceErrorText(loadError));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, row?.issue_evidence_id]);

  const updateResolution = (itemId: number, key: "returned" | "damaged" | "missing", value: string) => {
    setResolutions((current) => current.map((resolution) => (resolution.item_id === itemId ? { ...resolution, [key]: Number(value) || 0 } : resolution)));
  };

  const updateAssetOutcome = (itemId: number, assetId: number, outcome: PendingOutcome) => {
    setAssetOutcomes((current) => ({ ...current, [itemId]: { ...(current[itemId] ?? {}), [assetId]: outcome } }));
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={row ? `Return request #${row.id}` : "Return request"}
      description="Photograph what came back, note its condition, then record each item."
      footer={<FormFooter formId="return-request-form" pending={pending} submitLabel="Submit return" onCancel={onClose} />}
    >
      <form id="return-request-form" className="grid gap-5" onSubmit={(event) => submitForm(event, submitReturn)}>
        <div className="grid gap-4 sm:grid-cols-2">
          {issueUrl ? (
            <figure className="grid min-w-0 gap-1.5">
              <figcaption className="text-label text-ink">Issue photo</figcaption>
              <img src={issueUrl} alt="Issue photo for comparison" className="max-h-56 w-full rounded-lg border border-line object-contain" />
            </figure>
          ) : null}
          {issueError ? <p className="text-caption text-warning-fg" role="status">{issueError}</p> : null}
          <EvidenceUpload makerspaceId={makerspaceId} evidenceType="return" label="Return photo" disabled={pending} onUploaded={setEvidenceId} />
        </div>
        {row?.assigned_box_label ? <p className="text-caption text-ink-muted">Box: <span className="font-semibold text-ink">{row.assigned_box_label}</span></p> : null}
        <BoxCodeField value={boxCode} onChange={setBoxCode} makerspaceId={makerspaceId} pending={pending} />
        <Field label="Remark" helperText="Required. Note the condition of what came back.">
          <Textarea rows={3} value={remark} disabled={pending} onChange={(event) => setRemark(event.target.value)} />
        </Field>
        <ReturnItems row={row} resolutions={resolutions} assetOutcomes={assetOutcomes} pending={pending} onQuantityChange={updateResolution} onAssetOutcomeChange={updateAssetOutcome} />
        <ErrorText message={validationError || error} />
      </form>
    </Modal>
  );

  function submitReturn() {
    if (evidenceId === null) return setValidationError("Upload a return photo before submitting.");
    if (!remark.trim()) return setValidationError("Return remark is required.");
    const finalResolutions = buildFinalResolutions();
    if (finalResolutions.length === 0) return setValidationError("Resolve at least one item.");
    if (finalResolutions.some((resolution) => resolution.returned < 0 || resolution.damaged < 0 || resolution.missing < 0)) return setValidationError("Resolution quantities cannot be negative.");
    const overReturn = overReturnError(row, finalResolutions);
    if (overReturn) return setValidationError(overReturn);
    setValidationError("");
    onSubmit({ evidenceId, boxCode: boxCode.trim(), remark: remark.trim(), resolutions: finalResolutions });
  }

  function buildFinalResolutions(): ReturnRequestValues["resolutions"] {
    return (row?.items ?? []).map((item) => {
      if (!item.requires_asset_qr) return resolutions.find((entry) => entry.item_id === item.id) ?? { item_id: item.id, returned: 0, damaged: 0, missing: 0 };
      const assets = Object.entries(assetOutcomes[item.id] ?? {}).filter(([, outcome]) => outcome !== "pending").map(([assetId, outcome]) => ({ asset_id: Number(assetId), outcome: outcome as AssetReturnOutcome }));
      const counts = countAssetOutcomes(assets);
      return { item_id: item.id, ...counts, assets };
    }).filter((resolution) => resolution.returned + resolution.damaged + resolution.missing > 0);
  }
}

function ReturnItems({ row, resolutions, assetOutcomes, pending, onQuantityChange, onAssetOutcomeChange }: { row: FormModalProps<ReturnRequestValues>["row"]; resolutions: ReturnRequestValues["resolutions"]; assetOutcomes: AssetOutcomeState; pending: boolean; onQuantityChange: (itemId: number, key: "returned" | "damaged" | "missing", value: string) => void; onAssetOutcomeChange: (itemId: number, assetId: number, outcome: PendingOutcome) => void }) {
  return (
    <section className="grid gap-3">
      <SectionHeading as="h3" title="Return outcomes" />
      {row?.items.map((item) => item.requires_asset_qr ? <SerializedReturnItem key={item.id} item={item} outcomes={assetOutcomes[item.id] ?? {}} pending={pending} onChange={onAssetOutcomeChange} /> : <QuantityReturnItem key={item.id} item={item} resolution={resolutions.find((entry) => entry.item_id === item.id)} pending={pending} onChange={onQuantityChange} />)}
    </section>
  );
}

function SerializedReturnItem({ item, outcomes, pending, onChange }: { item: NonNullable<FormModalProps<ReturnRequestValues>["row"]>["items"][number]; outcomes: Record<number, PendingOutcome>; pending: boolean; onChange: (itemId: number, assetId: number, outcome: PendingOutcome) => void }) {
  return (
    <div className="grid gap-3 rounded-lg border border-line px-4 py-3">
      <div className="min-w-0">
        <p className="text-label text-ink [overflow-wrap:anywhere]">{item.product_name}</p>
        <ShelfLine location={item.storage_location} />
      </div>
      <div className="grid gap-3">
        {(item.issued_assets ?? []).map((asset) => (
          <Field key={asset.asset_id} label={<span className="font-mono">{asset.asset_tag}{asset.serial_number ? ` - ${asset.serial_number}` : ""}</span>}>
            <Dropdown value={outcomes[asset.asset_id] ?? "returned"} disabled={pending} onChange={(event) => onChange(item.id, asset.asset_id, event.target.value as PendingOutcome)}>
              <option value="returned">Returned</option>
              <option value="damaged">Damaged</option>
              <option value="missing">Missing</option>
              <option value="pending">Not returned now</option>
            </Dropdown>
          </Field>
        ))}
      </div>
    </div>
  );
}

function QuantityReturnItem({ item, resolution, pending, onChange }: { item: NonNullable<FormModalProps<ReturnRequestValues>["row"]>["items"][number]; resolution?: ReturnRequestValues["resolutions"][number]; pending: boolean; onChange: (itemId: number, key: "returned" | "damaged" | "missing", value: string) => void }) {
  return (
    <div className="grid gap-3 rounded-lg border border-line px-4 py-3">
      <div className="min-w-0">
        <p className="text-label text-ink [overflow-wrap:anywhere]">{item.product_name} <span className="font-normal text-ink-muted">{remainingCount(item)} out</span></p>
        <ShelfLine location={item.storage_location} />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {(["returned", "damaged", "missing"] as const).map((key) => (
          <Field key={key} label={OUTCOME_LABELS[key]}>
            <Input type="number" min="0" max={remainingCount(item)} value={resolution?.[key] ?? 0} disabled={pending} onChange={(event) => onChange(item.id, key, event.target.value)} />
          </Field>
        ))}
      </div>
    </div>
  );
}

const OUTCOME_LABELS = { returned: "Returned", damaged: "Damaged", missing: "Missing" } as const;

function overReturnError(row: FormModalProps<ReturnRequestValues>["row"], resolutions: ReturnRequestValues["resolutions"]) {
  for (const item of row?.items ?? []) {
    const resolution = resolutions.find((entry) => entry.item_id === item.id);
    if (!resolution) continue;
    const resolved = resolution.returned + resolution.damaged + resolution.missing;
    const remaining = remainingCount(item);
    if (resolved > remaining) {
      return `${item.product_name}: return outcomes (${resolved}) exceed remaining issued quantity (${remaining}).`;
    }
  }
  return "";
}
function countAssetOutcomes(assets: Array<{ outcome: AssetReturnOutcome }>) {
  return {
    returned: assets.filter((asset) => asset.outcome === "returned").length,
    damaged: assets.filter((asset) => asset.outcome === "damaged").length,
    missing: assets.filter((asset) => asset.outcome === "missing").length,
  };
}

function remainingCount(item: NonNullable<FormModalProps<ReturnRequestValues>["row"]>["items"][number]) {
  return item.issued_quantity - item.returned_quantity - item.damaged_quantity - item.missing_quantity;
}

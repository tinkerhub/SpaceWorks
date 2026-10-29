import { useEffect, useState } from "react";
import { QrCode, X } from "lucide-react";

import { Button, CheckboxField, Chip, Dropdown, ErrorText, Field, Input, Modal, SectionHeading, Textarea } from "../../../components/ui";
import QrScanner from "../../../components/ui/QrScanner";
import { staffRequest } from "../../../lib/api";
import { isQrNotRecognised, QR_NOT_RECOGNISED } from "../evidenceUi";
import { EvidenceUpload } from "./EvidenceUpload";
import { BoxCodeField, FormFooter, ShelfLine, submitForm } from "./QueuesModalShared";
import type { AssignIssueValues, FormModalProps } from "./QueuesModalTypes";

type ScannedAsset = { payload: string; label: string };
type Disposition = "needs_fix" | "remove";
type RejectState = Record<number, { broken: number; disposition: Disposition }>;

export function AssignIssueModal({ row, open, pending, error, onClose, onSubmit, makerspaceId, assignedContainerCode = "" }: FormModalProps<AssignIssueValues> & { makerspaceId: number; assignedContainerCode?: string }) {
  const rowHasContainer = row?.assigned_box_id != null || (row?.assigned_box_id === undefined && Boolean(row?.assigned_box_label || row?.assigned_box));
  const hasAssignedContainer = rowHasContainer || Boolean(assignedContainerCode);
  const [useContainer, setUseContainer] = useState(rowHasContainer);
  const containerSelected = hasAssignedContainer || useContainer;
  const [boxCode, setBoxCode] = useState(row?.assigned_box?.code ?? "");
  const [evidenceId, setEvidenceId] = useState<number | null>(null);
  const [remark, setRemark] = useState("Issued from staff app.");
  const [rejects, setRejects] = useState<RejectState>({});
  const [scanned, setScanned] = useState<ScannedAsset[]>([]);
  const [showScanner, setShowScanner] = useState(false);
  const [validationError, setValidationError] = useState("");

  const requiredScans = (row?.items ?? []).filter((item) => item.requires_asset_qr).reduce((sum, item) => sum + item.accepted_quantity, 0);

  useEffect(() => {
    if (open) {
      setBoxCode(row?.assigned_box?.code ?? "");
      setUseContainer(rowHasContainer);
      setEvidenceId(null);
      setRemark("Issued from staff app.");
      setRejects({});
      setScanned([]);
      setShowScanner(false);
      setValidationError("");
    }
  }, [open, row, rowHasContainer]);

  const handleScan = async (payload: string) => {
    const clean = payload.trim();
    if (!clean || scanned.some((item) => item.payload === clean)) return;
    let label = "Scanned QR";
    try {
      const result = await staffRequest<{ target: { type: string; product?: string; asset_tag?: string } }>("/admin/qr/resolve", {
        method: "POST",
        body: JSON.stringify({ payload: clean }),
      });
      label = result.target.product || result.target.asset_tag || "Scanned QR";
    } catch (error) {
      // A tenant-origin 403 means the same as a 404: not a code of this site.
      label = isQrNotRecognised(error) ? QR_NOT_RECOGNISED : "Unrecognised QR";
    }
    setScanned((items) => (items.some((item) => item.payload === clean) ? items : [...items, { payload: clean, label }]));
  };

  const setBroken = (itemId: number, broken: number) => setRejects((current) => ({
    ...current,
    [itemId]: { broken: Math.max(0, broken || 0), disposition: current[itemId]?.disposition ?? "needs_fix" },
  }));
  const setDisposition = (itemId: number, disposition: Disposition) => setRejects((current) => ({
    ...current,
    [itemId]: { broken: current[itemId]?.broken ?? 0, disposition },
  }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title={row ? `Issue request #${row.id}` : "Issue request"}
      description="Take the issue photo and scan each individually tracked unit. Use a container if needed."
      footer={<FormFooter formId="assign-issue-form" pending={pending} submitLabel="Issue" onCancel={onClose} />}
    >
      <form id="assign-issue-form" className="grid gap-5" onSubmit={(event) => submitForm(event, () => submitAssign())}>
        <CheckboxField label="Use a container" checked={containerSelected} disabled={pending || hasAssignedContainer} onCheckedChange={(checked) => { setUseContainer(checked === true); setValidationError(""); }} description={hasAssignedContainer ? "A container is already assigned to this request." : "Optional. Scan or choose a container to carry the items."} />
        {assignedContainerCode ? (
          <p className="text-caption text-ink-muted">Assigned container: <span className="font-mono text-ink">{assignedContainerCode}</span></p>
        ) : containerSelected ? (
          <>
            {row?.assigned_box_label ? <p className="text-caption text-ink-muted">Assigned container: <span className="font-semibold text-ink">{row.assigned_box_label}</span></p> : null}
            <BoxCodeField value={boxCode} onChange={(code) => { setBoxCode(code); setValidationError(""); }} makerspaceId={makerspaceId} pending={pending} />
          </>
        ) : null}
        <EvidenceUpload makerspaceId={makerspaceId} evidenceType="issue" label="Issue photo" disabled={pending} onUploaded={setEvidenceId} />
        <Field label="Remark">
          <Textarea rows={3} value={remark} disabled={pending} onChange={(event) => setRemark(event.target.value)} />
        </Field>
        {requiredScans > 0 ? <AssetScanList scanned={scanned} requiredScans={requiredScans} pending={pending} onScan={() => setShowScanner(true)} onManual={(payload) => void handleScan(payload)} onRemove={(payload) => setScanned((items) => items.filter((item) => item.payload !== payload))} /> : null}
        <IssueItems row={row} pending={pending} rejects={rejects} setBroken={setBroken} setDisposition={setDisposition} />
        {showScanner ? <QrScanner onScan={handleScan} onClose={() => setShowScanner(false)} /> : null}
        <ErrorText message={validationError || error} />
      </form>
    </Modal>
  );

  function submitAssign() {
    const selectedCode = containerSelected ? (assignedContainerCode || boxCode).trim() : "";
    if (containerSelected && !selectedCode) return setValidationError("Scan or choose a container before issuing.");
    if (evidenceId === null) return setValidationError("Upload an issue photo before issuing.");
    const overflow = (row?.items ?? []).find((item) => (rejects[item.id]?.broken ?? 0) > item.accepted_quantity);
    if (overflow) return setValidationError(`Can't reject more than ${overflow.accepted_quantity} of ${overflow.product_name}.`);
    if (scanned.length !== requiredScans) return setValidationError(`Scan exactly ${requiredScans} asset QR code(s) for the individually-tracked items (scanned ${scanned.length}).`);
    const rejectList = Object.entries(rejects).filter(([, value]) => value.broken > 0).map(([itemId, value]) => ({ item_id: Number(itemId), broken: value.broken, disposition: value.disposition }));
    setValidationError("");
    onSubmit({ boxCode: selectedCode, evidenceId, remark, rejects: rejectList, assetQrPayloads: scanned.map((item) => item.payload) });
  }
}

// A handheld (keyboard-wedge) scanner types the payload into a field: the fallback for a desk
// without a camera, as the container field and the direct-handout form already offer. It
// resolves exactly like a camera scan.
function AssetScanList({ scanned, requiredScans, pending, onScan, onManual, onRemove }: { scanned: ScannedAsset[]; requiredScans: number; pending: boolean; onScan: () => void; onManual: (payload: string) => void; onRemove: (payload: string) => void }) {
  const [manual, setManual] = useState("");
  const addManual = () => {
    if (!manual.trim()) return;
    onManual(manual);
    setManual("");
  };
  return (
    <section className="grid gap-3">
      <SectionHeading
        as="h3"
        title={`Asset QR codes (${scanned.length}/${requiredScans})`}
        description="Scan each individually tracked unit you hand over."
        action={<Button size="sm" startIcon={<QrCode />} disabled={pending} onClick={onScan}>Scan asset QR</Button>}
      />
      {scanned.length ? (
        <ul className="flex flex-wrap gap-2">
          {scanned.map((item) => (
            <li key={item.payload} className="inline-flex items-center gap-1 rounded-full border border-line-strong bg-canvas py-1 pl-3 pr-1 text-body-ui text-ink">
              {item.label}
              <button
                type="button"
                aria-label={`Remove ${item.label}`}
                disabled={pending}
                onClick={() => onRemove(item.payload)}
                className="inline-flex size-7 items-center justify-center rounded-full text-ink-muted hover:bg-emphasis hover:text-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus disabled:cursor-not-allowed"
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex items-start gap-2">
        <Field label="Asset QR code" optional helperText="No camera? Scan into this field with a handheld scanner." className="min-w-0 flex-1">
          <Input className="font-mono" value={manual} disabled={pending} onChange={(event) => setManual(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addManual(); } }} />
        </Field>
        <Button className="mt-[26px]" disabled={pending || !manual.trim()} onClick={addManual}>Add code</Button>
      </div>
    </section>
  );
}

function IssueItems({ row, pending, rejects, setBroken, setDisposition }: { row: FormModalProps<AssignIssueValues>["row"]; pending: boolean; rejects: RejectState; setBroken: (itemId: number, broken: number) => void; setDisposition: (itemId: number, disposition: Disposition) => void }) {
  return (
    <section className="grid gap-3">
      <SectionHeading as="h3" title="Items" description="Reject any broken units before they leave." />
      <ul className="grid gap-2">
        {row?.items.map((item) => (
          <li key={item.id} className="grid gap-3 rounded-lg border border-line px-4 py-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-label text-ink [overflow-wrap:anywhere]">{item.product_name} <span className="font-normal text-ink-muted">×{item.accepted_quantity}</span></p>
                <ShelfLine location={item.storage_location} />
              </div>
              {item.requires_asset_qr ? <Chip size="sm">Scan each unit</Chip> : null}
            </div>
            {item.requires_asset_qr ? (
              <p className="text-caption text-ink-muted">Individually tracked - issued by the asset QR scans above.</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)] sm:items-start">
                <Field label="Reject as broken">
                  <Input type="number" min="0" max={item.accepted_quantity} value={rejects[item.id]?.broken ?? 0} disabled={pending} onChange={(event) => setBroken(item.id, Number(event.target.value))} />
                </Field>
                {(rejects[item.id]?.broken ?? 0) > 0 ? (
                  <Field label="Send broken units to">
                    <Dropdown value={rejects[item.id]?.disposition ?? "needs_fix"} disabled={pending} onChange={(event) => setDisposition(item.id, event.target.value as Disposition)}>
                      <option value="needs_fix">To-be-fixed shelf</option>
                      <option value="remove">Remove from inventory</option>
                    </Dropdown>
                  </Field>
                ) : null}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

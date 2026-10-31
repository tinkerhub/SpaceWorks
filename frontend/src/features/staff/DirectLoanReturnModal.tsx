import { useEffect, useState } from "react";
import type React from "react";
import { ScanLine } from "lucide-react";

import { Button, ErrorText, Field, Input, Modal, Textarea } from "../../components/ui";
import QrScanner from "../../components/ui/QrScanner";
import { useHardwareQrVisit } from "./useHardwareQrVisit";
import { EvidenceUpload } from "./panels/EvidenceUpload";
import type { DirectLoan, DirectLoanReturnItem } from "./DirectLoanList";
import { DirectLoanReturnOutcomes, type AssetOutcome, type AssetState, type QtyState } from "./DirectLoanReturnOutcomes";

type QuantityResolution = { item_id: number; returned: number; damaged: number; missing: number };
type AssetResolution = QuantityResolution & { assets: { asset_id: number; outcome: AssetOutcome }[] };
export type DirectLoanResolution = QuantityResolution | AssetResolution;

type DirectLoanReturnModalProps = {
  loan: DirectLoan | null;
  makerspaceId: number;
  evidenceId: number | null;
  notes: string;
  qrPayload: string;
  pending: boolean;
  canEdit?: () => boolean;
  error: string;
  onEvidenceUploaded: (evidenceId: number | null) => void;
  onNotesChange: (notes: string) => void;
  onQrPayloadChange: (payload: string) => void;
  onCancel: () => void;
  onSubmit: (resolutions: DirectLoanResolution[]) => void;
};

export function DirectLoanReturnModal({
  loan,
  makerspaceId,
  evidenceId,
  notes,
  qrPayload,
  pending,
  canEdit = () => !pending,
  error,
  onEvidenceUploaded,
  onNotesChange,
  onQrPayloadChange,
  onCancel,
  onSubmit,
}: DirectLoanReturnModalProps) {
  const [showScanner, setShowScanner] = useState(false);
  const [qtyState, setQtyState] = useState<QtyState>({});
  const [assetState, setAssetState] = useState<AssetState>({});
  const qr = useHardwareQrVisit(`${makerspaceId}:${loan?.id}`, () => Boolean(loan) && !pending && canEdit());
  const cameraVisit = qr.cameraVisit;
  const closeScanner = () => {
    if (qr.canEdit() && qr.cameraCurrent(cameraVisit)) { qr.closeCamera(); setShowScanner(false); }
  };
  const returnItems: DirectLoanReturnItem[] = loan?.return_items ?? [];

  useEffect(() => {
    // A scanner left open when the dialog closed must not pop up over the next return.
    setShowScanner(false);
    if (!loan) return;
    const items = loan.return_items ?? [];
    // Default a clean return: quantity items pre-fill returned = remaining; individual
    // items default every still-issued asset to "returned". Staff reclassify as needed.
    setQtyState(
      Object.fromEntries(
        items
          .filter((item) => item.tracking_mode !== "individual")
          .map((item) => [item.item_id, { returned: item.remaining_quantity, damaged: 0, missing: 0 }]),
      ),
    );
    setAssetState(
      Object.fromEntries(
        items
          .filter((item) => item.tracking_mode === "individual")
          .map((item) => [item.item_id, Object.fromEntries(item.assets.map((asset) => [asset.asset_id, "returned" as AssetOutcome]))]),
      ),
    );
  }, [loan?.id]);

  const scanRequired = Boolean(loan?.return_scan_required);
  const buildResolutions = (): DirectLoanResolution[] =>
    returnItems.map((item) => {
      if (item.tracking_mode === "individual") {
        const outcomes = assetState[item.item_id] ?? {};
        const assets = item.assets.map((asset) => ({ asset_id: asset.asset_id, outcome: outcomes[asset.asset_id] ?? ("returned" as AssetOutcome) }));
        return {
          item_id: item.item_id,
          returned: assets.filter((a) => a.outcome === "returned").length,
          damaged: assets.filter((a) => a.outcome === "damaged").length,
          missing: assets.filter((a) => a.outcome === "missing").length,
          assets,
        };
      }
      const buckets = qtyState[item.item_id] ?? { returned: item.remaining_quantity, damaged: 0, missing: 0 };
      return { item_id: item.item_id, ...buckets };
    });

  // Every outstanding unit must be resolved (direct loans have no partial state).
  const resolutions = buildResolutions();
  const fullyResolved = returnItems.every((item) => {
    const r = resolutions.find((res) => res.item_id === item.item_id);
    return r ? r.returned + r.damaged + r.missing === item.remaining_quantity : false;
  });
  const canSubmit = evidenceId !== null && notes.trim().length > 0 && (!scanRequired || qrPayload.trim().length > 0) && fullyResolved && !pending;
  const missing = [
    evidenceId === null ? "a return photo" : null,
    !notes.trim() ? "return notes" : null,
    scanRequired && !qrPayload.trim() ? "the return QR scan" : null,
  ].filter(Boolean);

  const updateQty = (itemId: number, key: "returned" | "damaged" | "missing", value: string) => {
    if (!qr.canEdit()) return;
    setQtyState((current) => ({
      ...current,
      [itemId]: { ...(current[itemId] ?? { returned: 0, damaged: 0, missing: 0 }), [key]: Number(value) || 0 },
    }));
  };
  const updateAsset = (itemId: number, assetId: number, outcome: AssetOutcome) => {
    if (!qr.canEdit()) return;
    setAssetState((current) => ({ ...current, [itemId]: { ...(current[itemId] ?? {}), [assetId]: outcome } }));
  };

  return (
    <Modal
      open={Boolean(loan)}
      onClose={() => {
        if (qr.canEdit()) onCancel();
      }}
      title={loan ? `Return ${loan.target_label}` : "Return direct handout"}
      description="A return needs a photo of what came back and a note on its condition."
      size="lg"
      footer={
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:items-center sm:justify-end">
          {missing.length ? <p className="text-caption text-ink-muted sm:mr-auto">Still needed: {missing.join(", ")}.</p> : null}
          <Button disabled={pending} onClick={() => { if (qr.canEdit()) onCancel(); }}>Cancel</Button>
          <Button variant="primary" type="submit" form="direct-loan-return-form" disabled={!canSubmit} loading={pending} loadingLabel="Returning…">
            Submit return
          </Button>
        </div>
      }
    >
      <form
        id="direct-loan-return-form"
        className="grid gap-5"
        onSubmit={(event: React.FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          if (canSubmit && qr.canEdit()) onSubmit(resolutions);
        }}
      >
        <EvidenceUpload resourceContext={loan?.id} makerspaceId={makerspaceId} evidenceType="return" label="Return photo" disabled={pending} onUploaded={(id) => { if (qr.canEdit()) onEvidenceUploaded(id); }} />
        <DirectLoanReturnOutcomes
          items={returnItems}
          qtyState={qtyState}
          assetState={assetState}
          disabled={pending}
          fullyResolved={fullyResolved}
          onQtyChange={updateQty}
          onAssetChange={updateAsset}
        />
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <Field label="Return QR scan" optional={!scanRequired} className="min-w-0 flex-1">
            <Input className="font-mono text-sm" value={qrPayload} disabled={pending} onChange={(event) => { if (qr.canEdit()) { qr.closeCamera(); setShowScanner(false); onQrPayloadChange(event.target.value); } }} />
          </Field>
          <Button startIcon={<ScanLine />} disabled={pending} onClick={() => { if (qr.canEdit()) { qr.openCamera(); setShowScanner(true); } }}>Scan QR</Button>
        </div>
        <Field label="Return notes" helperText="What came back, and in what condition.">
          <Textarea value={notes} disabled={pending} onChange={(event) => { if (qr.canEdit()) onNotesChange(event.target.value); }} />
        </Field>
        <ErrorText message={error} />
        {showScanner ? (
          <QrScanner
            onScan={(payload) => {
              const scan = qr.captureSingleCamera(cameraVisit);
              if (!qr.current(scan)) return;
              qr.closeCamera();
              onQrPayloadChange(payload.trim());
              setShowScanner(false);
            }}
            onClose={closeScanner}
          />
        ) : null}
      </form>
    </Modal>
  );
}

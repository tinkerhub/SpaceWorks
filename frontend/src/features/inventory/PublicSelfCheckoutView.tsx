import { useRef, useState } from "react";
import { QrCode } from "lucide-react";

import { Button, Card, ErrorText, Field, SegmentedControl, Textarea } from "../../components/ui";
import QrScanner from "../../components/ui/QrScanner";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";
import type { CheckinMatch } from "./api";
import { CheckinIdentityStep } from "./CheckinIdentityStep";
import { PendingToolCheckoutControls } from "./PendingToolCheckoutControls";
import { PublicEvidenceUpload } from "./PublicEvidenceUpload";
import { PublicSelfCheckoutResult } from "./PublicSelfCheckoutResult";
import { usePublicToolOperation } from "./usePublicToolOperation";

type Mode = "checkout" | "return";
type Props = { makerspaceSlug: string; requiresCheckin: boolean; sessionReady: boolean };

export function PublicSelfCheckoutView(props: Props) {
  const [mode, setMode] = useState<Mode>("checkout");
  const [confirmed, setConfirmed] = useState<CheckinMatch | null>(null);
  const [visit, setVisit] = useState(0);
  const owner = useAuthActionOwner(JSON.stringify([props.makerspaceSlug, visit, mode, confirmed?.mid, confirmed?.name]));
  return <CheckoutContent key={visit} {...props} mode={mode} confirmed={confirmed} owner={owner}
    onMode={(next) => {
      if (next === mode || !owner.begin()) return;
      setMode(next);
    }}
    onConfirm={(match) => {
      const transition = owner.begin();
      if (!transition) return;
      if (confirmed?.mid === match?.mid && confirmed?.name === match?.name) { owner.finish(transition); return; }
      setConfirmed(match); setVisit((current) => current + 1);
    }} />;
}

function CheckoutContent({ makerspaceSlug, requiresCheckin, sessionReady, mode, confirmed, owner, onMode, onConfirm }: Props & {
  mode: Mode; confirmed: CheckinMatch | null; owner: ReturnType<typeof useAuthActionOwner>;
  onMode: (mode: Mode) => void; onConfirm: (match: CheckinMatch | null) => void;
}) {
  const [issueEvidenceId, setIssueEvidenceId] = useState<number | null>(null);
  const [returnEvidenceId, setReturnEvidenceId] = useState<number | null>(null);
  const [returnRemark, setReturnRemark] = useState("");
  const [pendingPayloads, setPendingPayloads] = useState<string[]>([]);
  const [uploadKey, setUploadKey] = useState(0);
  const activeScanner = useRef<AuthAction | null>(null);
  const [scanner, setScanner] = useState<AuthAction | null>(null);
  const identityReady = requiresCheckin ? confirmed !== null : sessionReady;
  const checkinPayload = requiresCheckin && confirmed ? { name: confirmed.name, checkin_mid: confirmed.mid } : {};
  const loan = usePublicToolOperation(makerspaceSlug, owner, (input) => {
    if (input.operation === "checkout") setPendingPayloads([]);
    else setReturnRemark("");
    setIssueEvidenceId(null); setReturnEvidenceId(null);
    setUploadKey((key) => key + 1);
  });
  const canEdit = () => owner.isContextCurrent() && !owner.isPending();
  const canSubmitCheckout = identityReady && issueEvidenceId !== null && pendingPayloads.length > 0 && !loan.pending;
  const canReturn = identityReady && returnEvidenceId !== null && returnRemark.trim().length > 0 && !loan.pending;

  function openScanner() {
    if (!canEdit() || !identityReady || (mode === "return" && !canReturn)) return;
    const action = owner.capture();
    if (action) { activeScanner.current = action; setScanner(action); }
  }
  function scanTool(payload: string) {
    if (!owner.isCurrent(scanner) || activeScanner.current !== scanner || !canEdit()) return;
    const normalized = payload.trim();
    if (!normalized) return;
    activeScanner.current = null; setScanner(null);
    if (mode === "checkout") {
      setPendingPayloads((current) => current.includes(normalized) ? current : [...current, normalized]);
    } else if (canReturn) {
      loan.submit({ operation: "return", body: {
        payload: normalized, evidence_id: returnEvidenceId as number, remark: returnRemark.trim(), ...checkinPayload,
      } });
    }
  }

  return (
    <Card className="space-y-4">
      {requiresCheckin ? <CheckinIdentityStep makerspaceSlug={makerspaceSlug} confirmed={confirmed}
        onConfirm={onConfirm} disabled={loan.pending} /> : null}
      <SegmentedControl ariaLabel="Checkout mode" className="grid w-full grid-cols-2" value={mode}
        onValueChange={onMode} options={[
          { value: "checkout", label: "Use (check out)", disabled: loan.pending },
          { value: "return", label: "Return", disabled: loan.pending },
        ]} />
      {mode === "checkout" ? (
        <PublicEvidenceUpload key={`issue-${uploadKey}`} slug={makerspaceSlug} evidenceType="issue"
          checkinIdentity={requiresCheckin ? confirmed ?? undefined : undefined} disabled={!identityReady || loan.pending}
          onUploaded={(id) => { if (canEdit()) setIssueEvidenceId(id); }} />
      ) : (
        <>
          <PublicEvidenceUpload key={`return-${uploadKey}`} slug={makerspaceSlug} evidenceType="return"
            checkinIdentity={requiresCheckin ? confirmed ?? undefined : undefined} disabled={!identityReady || loan.pending}
            onUploaded={(id) => { if (canEdit()) setReturnEvidenceId(id); }} />
          <Field label="Return condition notes" helperText="Describe the tool's condition as you hand it back.">
            <Textarea required disabled={loan.pending} value={returnRemark}
              onChange={(event) => { if (canEdit()) setReturnRemark(event.target.value); }} />
          </Field>
        </>
      )}
      {mode === "checkout" ? (
        <PendingToolCheckoutControls payloads={pendingPayloads} isPending={loan.pending}
          submitDisabled={!canSubmitCheckout} showScanWhenEmpty pendingLabel="Submitting…"
          onRemove={(payload) => { if (canEdit()) setPendingPayloads((current) => current.filter((item) => item !== payload)); }}
          onScanAnother={openScanner} onSubmit={() => {
            if (!canSubmitCheckout) return;
            loan.submit({ operation: "checkout", body: {
              ...(pendingPayloads.length === 1 ? { payload: pendingPayloads[0] } : { qr_payloads: [...pendingPayloads] }),
              evidence_id: issueEvidenceId as number, ...checkinPayload,
            } });
          }} />
      ) : (
        <Button variant="primary" fullWidth startIcon={<QrCode />} disabled={!canReturn}
          loading={loan.pending} loadingLabel="Submitting…" onClick={openScanner}>Scan QR</Button>
      )}
      {loan.error ? <ErrorText message={loan.error} /> : null}
      {loan.result ? <PublicSelfCheckoutResult result={loan.result} /> : null}
      {scanner && owner.isCurrent(scanner) ? <QrScanner
        onClose={() => {
          if (owner.isCurrent(scanner) && activeScanner.current === scanner) { activeScanner.current = null; setScanner(null); }
        }} onScan={scanTool} /> : null}
    </Card>
  );
}

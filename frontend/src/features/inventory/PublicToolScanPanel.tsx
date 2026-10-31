import { useRef, useState } from "react";

import { QrCode } from "lucide-react";

import { Button, Callout, Card, CheckboxField, ErrorText, Field, Textarea } from "../../components/ui";
import QrScanner from "../../components/ui/QrScanner";
import type { PublicToolLoan } from "../../types/inventory";
import { getSessionGeneration } from "../../lib/apiSession";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";
import { usePublicToolOperation } from "./usePublicToolOperation";
import type { CheckinMatch } from "./api";
import { CheckinIdentityStep } from "./CheckinIdentityStep";
import { PendingToolCheckoutControls } from "./PendingToolCheckoutControls";
import { PublicEvidenceUpload } from "./PublicEvidenceUpload";

type PublicToolScanPanelProps = {
  makerspaceSlug: string;
  requiresCheckin?: boolean;
};

function LoanResult({ loan }: { loan: PublicToolLoan }) {
  const status = loan.status.replace(/_/g, " ");
  return (
    <Callout
      tone="success"
      role="status"
      title={`${status.charAt(0).toUpperCase()}${status.slice(1)}: ${loan.items.map((item) => item.product_name).join(", ") || "Tool loan"}`}
    >
      <p className="mt-1 break-all font-mono text-xs">{loan.public_token}</p>
      <ul className="mt-2 space-y-1">
        {loan.items.map((item) => (
          <li className="flex justify-between gap-3 text-caption" key={item.product_name}>
            <span className="min-w-0 flex-1">{item.product_name}</span>
            <span className="shrink-0 font-mono tabular-nums">×{item.quantity}</span>
          </li>
        ))}
      </ul>
    </Callout>
  );
}

export function PublicToolScanPanel(props: PublicToolScanPanelProps) {
  const scope = JSON.stringify([props.makerspaceSlug, props.requiresCheckin, getSessionGeneration()]);
  return <PublicToolScanDesk key={scope} {...props} />;
}

function PublicToolScanDesk({ makerspaceSlug, requiresCheckin = false }: PublicToolScanPanelProps) {
  const [confirmed, setConfirmed] = useState<CheckinMatch | null>(null);
  const [visit, setVisit] = useState(0);
  const owner = useAuthActionOwner(JSON.stringify([makerspaceSlug, visit, confirmed?.mid, confirmed?.name]));
  return <PublicToolScanContent key={visit} makerspaceSlug={makerspaceSlug} requiresCheckin={requiresCheckin}
    confirmedCheckin={confirmed} owner={owner} onConfirm={(match) => {
      const transition = owner.begin();
      if (!transition) return;
      if (confirmed?.mid === match?.mid && confirmed?.name === match?.name) { owner.finish(transition); return; }
      setConfirmed(match); setVisit((current) => current + 1);
    }} />;
}

function PublicToolScanContent({ makerspaceSlug, requiresCheckin, confirmedCheckin, owner, onConfirm }: {
  makerspaceSlug: string; requiresCheckin: boolean; confirmedCheckin: CheckinMatch | null;
  owner: ReturnType<typeof useAuthActionOwner>; onConfirm: (match: CheckinMatch | null) => void;
}) {
  const [pendingPayloads, setPendingPayloads] = useState<string[]>([]);
  const [returnPayload, setReturnPayload] = useState("");
  const activeScanner = useRef<AuthAction | null>(null);
  const [scanner, setScanner] = useState<{ action: AuthAction; target: "both" | "checkout" } | null>(null);
  const [issueEvidenceId, setIssueEvidenceId] = useState<number | null>(null);
  const [returnEvidenceId, setReturnEvidenceId] = useState<number | null>(null);
  const [returnRemark, setReturnRemark] = useState("");
  const [reportProblem, setReportProblem] = useState(false);
  const [problemNote, setProblemNote] = useState("");
  const [uploadKey, setUploadKey] = useState(0);
  const effectiveReturnPayload = returnPayload.trim();
  const identityReady = !requiresCheckin || confirmedCheckin !== null;
  const checkinPayload =
    requiresCheckin && confirmedCheckin
      ? { name: confirmedCheckin.name, checkin_mid: confirmedCheckin.mid }
      : {};
  const loan = usePublicToolOperation(makerspaceSlug, owner, (input) => {
    if (input.operation === "checkout") {
      setPendingPayloads([]); setIssueEvidenceId(null);
    } else {
      setReturnPayload("");
      setPendingPayloads((current) => current.filter((item) => item !== input.body.payload));
      setReturnEvidenceId(null); setReturnRemark(""); setReportProblem(false); setProblemNote("");
    }
    setIssueEvidenceId(null); setReturnEvidenceId(null);
    setUploadKey((key) => key + 1);
  });
  const canEdit = () => owner.isContextCurrent() && !owner.isPending();
  function openScanner(target: "both" | "checkout") {
    if (!canEdit() || !identityReady) return;
    const action = owner.capture();
    if (action) { activeScanner.current = action; setScanner({ action, target }); }
  }
  const checkoutDisabled =
    !identityReady || loan.pending ||
    pendingPayloads.length === 0 ||
    issueEvidenceId === null;
  const returnDisabled =
    !identityReady || loan.pending ||
    !effectiveReturnPayload ||
    returnEvidenceId === null ||
    !returnRemark.trim() ||
    (reportProblem && !problemNote.trim());
  const { error, result } = loan;

  return (
    <Card className="@container">
      <p className="text-body-ui text-ink-muted">QR tool checkout</p>
      <h2 className="mt-1 text-h4 text-ink">Scan public tool</h2>
      <p className="mt-2 text-body-ui text-ink-secondary">
        Upload the required photo, then scan the tool QR with your camera.
      </p>
      {requiresCheckin ? (
        <div className="mt-4">
          <CheckinIdentityStep
            makerspaceSlug={makerspaceSlug}
            confirmed={confirmedCheckin}
            onConfirm={onConfirm}
            disabled={loan.pending}
          />
        </div>
      ) : null}
      <Button
        className="mt-4"
        fullWidth
        startIcon={<QrCode />}
        disabled={!identityReady || loan.pending}
        onClick={() => openScanner("both")}
      >
        Scan QR with camera
      </Button>
      {returnPayload ? (
        <p className="mt-2 inline-flex items-center gap-1 rounded-full bg-success-bg py-0.5 pl-3 pr-1 text-sm font-semibold text-success-fg">
          Scanned OK
          <Button variant="quiet" size="sm" className="text-success-fg hover:text-success-fg" disabled={loan.pending} onClick={() => { if (canEdit()) setReturnPayload(""); }}>
            Clear
          </Button>
        </p>
      ) : null}
      <div className="mt-4 grid gap-4 @min-[36rem]:grid-cols-2">
        <section className="min-w-0 rounded-lg border border-line p-4">
          <h3 className="text-title text-ink">Check out</h3>
          <PendingToolCheckoutControls
            payloads={pendingPayloads}
            isPending={loan.pending}
            submitDisabled={checkoutDisabled}
            onRemove={(payload) => { if (canEdit()) setPendingPayloads((current) => current.filter((item) => item !== payload)); }}
            onScanAnother={() => openScanner("checkout")}
            onSubmit={() => {
              if (checkoutDisabled) return;
              loan.submit({ operation: "checkout", body: {
                ...(pendingPayloads.length === 1 ? { payload: pendingPayloads[0] } : { qr_payloads: [...pendingPayloads] }),
                evidence_id: issueEvidenceId as number, ...checkinPayload,
              } });
            }}
          >
            <div className="mt-3">
              <PublicEvidenceUpload
                key={`issue-${uploadKey}`}
                slug={makerspaceSlug}
                evidenceType="issue"
                checkinIdentity={
                  requiresCheckin ? confirmedCheckin ?? undefined : undefined
                }
                disabled={!identityReady || loan.pending}
                onUploaded={(id) => { if (canEdit()) setIssueEvidenceId(id); }}
              />
            </div>
          </PendingToolCheckoutControls>
        </section>
        <section className="min-w-0 space-y-3 rounded-lg border border-line p-4">
          <h3 className="text-title text-ink">Return</h3>
          <PublicEvidenceUpload
            key={`return-${uploadKey}`}
            slug={makerspaceSlug}
            evidenceType="return"
            checkinIdentity={
              requiresCheckin ? confirmedCheckin ?? undefined : undefined
            }
            disabled={!identityReady || loan.pending}
            onUploaded={(id) => { if (canEdit()) setReturnEvidenceId(id); }}
          />
          <Field label="Return condition notes">
            <Textarea rows={3} className="min-h-20" disabled={loan.pending} value={returnRemark} onChange={(event) => { if (canEdit()) setReturnRemark(event.target.value); }} />
          </Field>
          <CheckboxField
            label="Report a problem with this tool"
            checked={reportProblem} disabled={loan.pending}
            onCheckedChange={(checked) => { if (canEdit()) setReportProblem(checked === true); }}
          />
          {reportProblem ? (
            <Field label="What's wrong?" helperText="Staff will review it.">
              <Textarea rows={2} className="min-h-16" disabled={loan.pending} value={problemNote} onChange={(event) => { if (canEdit()) setProblemNote(event.target.value); }} />
            </Field>
          ) : null}
          <Button fullWidth disabled={returnDisabled} loading={loan.pending} loadingLabel="Returning…" onClick={() => {
            if (returnDisabled) return;
            loan.submit({ operation: "return", body: {
              payload: effectiveReturnPayload, evidence_id: returnEvidenceId as number, remark: returnRemark.trim(),
              report_problem: reportProblem, problem_note: reportProblem ? problemNote.trim() : "", ...checkinPayload,
            } });
          }}>
            Return
          </Button>
        </section>
      </div>
      {error ? <div className="mt-3"><ErrorText message={error} /></div> : null}
      {result ? (
        <div className="mt-3">
          <LoanResult loan={result} />
        </div>
      ) : null}
      {scanner && owner.isCurrent(scanner.action) ? (
        <QrScanner
          onClose={() => {
            if (owner.isCurrent(scanner.action) && activeScanner.current === scanner.action) {
              activeScanner.current = null; setScanner(null);
            }
          }}
          onScan={(scanned) => {
            if (!owner.isCurrent(scanner.action) || activeScanner.current !== scanner.action || !canEdit()) return;
            const normalized = scanned.trim();
            if (!normalized) return;
            setPendingPayloads((current) =>
              current.includes(normalized) ? current : [...current, normalized],
            );
            if (scanner.target === "both") {
              setReturnPayload(normalized);
            }
            activeScanner.current = null; setScanner(null);
          }}
        />
      ) : null}
    </Card>
  );
}

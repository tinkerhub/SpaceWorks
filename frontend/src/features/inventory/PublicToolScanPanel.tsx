import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { QrCode } from "lucide-react";

import { Button, Callout, Card, CheckboxField, ErrorText, Field, Textarea, useToast } from "../../components/ui";
import QrScanner from "../../components/ui/QrScanner";
import type { PublicToolLoan } from "../../types/inventory";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import {
  publicToolCheckout,
  publicToolReturn,
  type CheckinMatch,
} from "./api";
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

export function PublicToolScanPanel({
  makerspaceSlug,
  requiresCheckin = false,
}: PublicToolScanPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [confirmedCheckin, setConfirmedCheckin] = useState<CheckinMatch | null>(
    null,
  );
  const [pendingPayloads, setPendingPayloads] = useState<string[]>([]);
  const [returnPayload, setReturnPayload] = useState("");
  const [scannerTarget, setScannerTarget] = useState<"both" | "checkout">("both");
  const [scannerOpen, setScannerOpen] = useState(false);
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
  const checkout = useMutation({
    mutationFn: () =>
      publicToolCheckout(makerspaceSlug, {
        ...(pendingPayloads.length === 1
          ? { payload: pendingPayloads[0] }
          : { qr_payloads: pendingPayloads }),
        evidence_id: issueEvidenceId as number,
        ...checkinPayload,
      }),
    onSuccess: () => {
      invalidatePublicInventory(queryClient, makerspaceSlug);
      setPendingPayloads([]);
      setIssueEvidenceId(null);
      setUploadKey((key) => key + 1);
      showToast("Tool checked out", { tone: "success" });
    },
    onError: () => showToast("Checkout failed", { tone: "error" }),
  });
  const returnTool = useMutation({
    mutationFn: () =>
      publicToolReturn(makerspaceSlug, {
        payload: effectiveReturnPayload,
        evidence_id: returnEvidenceId as number,
        remark: returnRemark.trim(),
        report_problem: reportProblem,
        problem_note: reportProblem ? problemNote.trim() : "",
        ...checkinPayload,
      }),
    onSuccess: () => {
      invalidatePublicInventory(queryClient, makerspaceSlug);
      setReturnEvidenceId(null);
      setReturnRemark("");
      setReportProblem(false);
      setProblemNote("");
      setUploadKey((key) => key + 1);
      showToast("Tool returned", { tone: "success" });
    },
    onError: () => showToast("Return failed", { tone: "error" }),
  });
  const checkoutDisabled =
    !identityReady ||
    pendingPayloads.length === 0 ||
    issueEvidenceId === null;
  const returnDisabled =
    !identityReady ||
    !effectiveReturnPayload ||
    returnEvidenceId === null ||
    !returnRemark.trim() ||
    (reportProblem && !problemNote.trim());
  const error = checkout.error?.message ?? returnTool.error?.message;
  const result = checkout.data ?? returnTool.data;

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
            onConfirm={(match) => {
              setConfirmedCheckin(match);
              setIssueEvidenceId(null);
              setReturnEvidenceId(null);
              setUploadKey((key) => key + 1);
            }}
            disabled={checkout.isPending || returnTool.isPending}
          />
        </div>
      ) : null}
      <Button
        className="mt-4"
        fullWidth
        startIcon={<QrCode />}
        disabled={!identityReady || checkout.isPending || returnTool.isPending}
        onClick={() => {
          setScannerTarget("both");
          setScannerOpen(true);
        }}
      >
        Scan QR with camera
      </Button>
      {returnPayload ? (
        <p className="mt-2 inline-flex items-center gap-1 rounded-full bg-success-bg py-0.5 pl-3 pr-1 text-sm font-semibold text-success-fg">
          Scanned OK
          <Button variant="quiet" size="sm" className="text-success-fg hover:text-success-fg" onClick={() => setReturnPayload("")}>
            Clear
          </Button>
        </p>
      ) : null}
      <div className="mt-4 grid gap-4 @min-[36rem]:grid-cols-2">
        <section className="min-w-0 rounded-lg border border-line p-4">
          <h3 className="text-title text-ink">Check out</h3>
          <PendingToolCheckoutControls
            payloads={pendingPayloads}
            isPending={checkout.isPending}
            submitDisabled={checkoutDisabled}
            onRemove={(payload) =>
              setPendingPayloads((current) =>
                current.filter((item) => item !== payload),
              )
            }
            onScanAnother={() => {
              setScannerTarget("checkout");
              setScannerOpen(true);
            }}
            onSubmit={() => checkout.mutate()}
          >
            <div className="mt-3">
              <PublicEvidenceUpload
                key={`issue-${uploadKey}`}
                slug={makerspaceSlug}
                evidenceType="issue"
                checkinIdentity={
                  requiresCheckin ? confirmedCheckin ?? undefined : undefined
                }
                disabled={!identityReady || checkout.isPending}
                onUploaded={setIssueEvidenceId}
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
            disabled={!identityReady || returnTool.isPending}
            onUploaded={setReturnEvidenceId}
          />
          <Field label="Return condition notes">
            <Textarea rows={3} className="min-h-20" value={returnRemark} onChange={(event) => setReturnRemark(event.target.value)} />
          </Field>
          <CheckboxField
            label="Report a problem with this tool"
            checked={reportProblem}
            onCheckedChange={(checked) => setReportProblem(checked === true)}
          />
          {reportProblem ? (
            <Field label="What's wrong?" helperText="Staff will review it.">
              <Textarea rows={2} className="min-h-16" value={problemNote} onChange={(event) => setProblemNote(event.target.value)} />
            </Field>
          ) : null}
          <Button fullWidth disabled={returnDisabled} loading={returnTool.isPending} loadingLabel="Returning…" onClick={() => returnTool.mutate()}>
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
      {scannerOpen ? (
        <QrScanner
          onClose={() => setScannerOpen(false)}
          onScan={(scanned) => {
            const normalized = scanned.trim();
            if (!normalized) return;
            setPendingPayloads((current) =>
              current.includes(normalized) ? current : [...current, normalized],
            );
            if (scannerTarget === "both") {
              setReturnPayload(normalized);
            }
            setScannerOpen(false);
          }}
        />
      ) : null}
    </Card>
  );
}

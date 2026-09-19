import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Card } from "../../components/ui/Card";
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
  return (
    <div className="rounded-xl border border-success bg-success px-3 py-2 text-on-success dark:bg-success/15 dark:text-success-ink">
      <h3 className="title-section capitalize text-on-success dark:text-success-ink">
        {loan.status.replace(/_/g, " ")}: {loan.items.map((item) => item.product_name).join(", ") || "Tool loan"}
      </h3>
      <p className="mt-1 break-all font-mono text-xs">{loan.public_token}</p>
      <div className="mt-2 space-y-1">
        {loan.items.map((item) => (
          <div className="flex justify-between gap-3 text-xs" key={item.product_name}>
            <span>{item.product_name}</span>
            <span className="font-mono">x{item.quantity}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function PublicToolScanPanel({
  makerspaceSlug,
  requiresCheckin = false,
}: PublicToolScanPanelProps) {
  const queryClient = useQueryClient();
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
    },
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
    },
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
    <Card>
      <p className="eyebrow text-secondary-ink">
        QR Tool Checkout
      </p>
      <h2 className="title-panel mt-2">Scan public tool</h2>
      <p className="mt-2 text-sm leading-6 text-muted">
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
      <button
        className="desk-button mt-4 w-full"
        disabled={!identityReady || checkout.isPending || returnTool.isPending}
        type="button"
        onClick={() => {
          setScannerTarget("both");
          setScannerOpen(true);
        }}
      >
        Scan QR with camera
      </button>
      {returnPayload ? (
        <p className="mt-2 inline-flex items-center gap-2 rounded-lg border border-success bg-success px-3 py-1 text-sm font-semibold text-on-success dark:bg-success/15 dark:text-success-ink">
          Scanned OK
          <button
            type="button"
            className="min-h-11 px-2 text-xs font-normal underline"
            onClick={() => setReturnPayload("")}
          >
            clear
          </button>
        </p>
      ) : null}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <section className="rounded-lg border border-line p-3">
          <h3 className="title-section">Check out</h3>
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
        <section className="rounded-lg border border-line p-3">
          <h3 className="title-section">Return</h3>
          <div className="mt-3">
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
          </div>
          <label className="mt-3 block">
            <span className="eyebrow mb-1 block">
              Return condition notes
            </span>
            <textarea
              className="desk-input min-h-20 w-full"
              value={returnRemark}
              onChange={(event) => setReturnRemark(event.target.value)}
            />
          </label>
          <label className="mt-3 flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={reportProblem}
              onChange={(event) => setReportProblem(event.target.checked)}
            />
            <span>Report a problem with this tool</span>
          </label>
          {reportProblem ? (
            <label className="mt-2 block">
              <span className="eyebrow mb-1 block">
                What's wrong? (staff will review)
              </span>
              <textarea
                className="desk-input min-h-16 w-full"
                value={problemNote}
                onChange={(event) => setProblemNote(event.target.value)}
              />
            </label>
          ) : null}
          <button
            className="desk-button mt-3 w-full disabled:cursor-not-allowed disabled:opacity-50"
            disabled={returnDisabled || returnTool.isPending}
            type="button"
            onClick={() => returnTool.mutate()}
          >
            {returnTool.isPending ? "Returning..." : "Return"}
          </button>
        </section>
      </div>
      {error ? (
        <p className="mt-3 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
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

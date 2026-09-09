import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { Card } from "../../components/ui/Card";
import QrScanner from "../../components/ui/QrScanner";
import { featureEnabled } from "../../lib/features";
import { useTenant, useTenantPath } from "../../lib/tenant";
import { formatSlug } from "./PublicInventoryParts";
import { CheckinIdentityStep } from "./CheckinIdentityStep";
import { PendingToolCheckoutControls } from "./PendingToolCheckoutControls";
import { PublicEvidenceUpload } from "./PublicEvidenceUpload";
import type { CheckinMatch } from "./api";
import { checkoutTool, returnTool } from "./selfCheckoutApi";
import { PublicSelfCheckoutResult } from "./PublicSelfCheckoutResult";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import { useTenantBootstrap } from "./usePublicInventory";

type Mode = "checkout" | "return";

type MutationInput =
  | { operation: "checkout"; payloads: string[] }
  | { operation: "return"; payload: string };

export function PublicSelfCheckoutPage() {
  const queryClient = useQueryClient();
  const { slug } = useParams();
  const tenant = useTenant();
  const makerspaceSlug = tenant.mode === "single" ? tenant.slug : slug ?? "";
  const tenantPath = useTenantPath(makerspaceSlug);
  const [mode, setMode] = useState<Mode>("checkout");
  const [confirmedCheckin, setConfirmedCheckin] = useState<CheckinMatch | null>(
    null,
  );
  const [issueEvidenceId, setIssueEvidenceId] = useState<number | null>(null);
  const [returnEvidenceId, setReturnEvidenceId] = useState<number | null>(null);
  const [returnRemark, setReturnRemark] = useState("");
  const [pendingPayloads, setPendingPayloads] = useState<string[]>([]);
  const [uploadKey, setUploadKey] = useState(0);
  const [scannerOpen, setScannerOpen] = useState(false);

  const bootstrapQuery = useTenantBootstrap(makerspaceSlug, tenant.mode === "central");
  const bootstrap = tenant.mode === "single" ? tenant.bootstrap : bootstrapQuery.data;
  const features = tenant.mode === "single" ? tenant.bootstrap?.features ?? [] : bootstrap?.features ?? [];
  const displayName =
    bootstrap?.branding.display_name ||
    bootstrap?.makerspace.name ||
    formatSlug(makerspaceSlug) ||
    "Makerspace";
  const enabled = featureEnabled(features, "inventory.self_checkout");
  const requiresCheckin = bootstrap?.makerspace.request_access === "checked_in";
  const identityReady = !requiresCheckin || confirmedCheckin !== null;
  const checkinPayload =
    requiresCheckin && confirmedCheckin
      ? { name: confirmedCheckin.name, checkin_mid: confirmedCheckin.mid }
      : {};

  const loanMutation = useMutation({
    mutationFn: (input: MutationInput) =>
      input.operation === "checkout"
        ? checkoutTool(makerspaceSlug, {
            ...(input.payloads.length === 1
              ? { payload: input.payloads[0] }
              : { qr_payloads: input.payloads }),
            evidence_id: issueEvidenceId as number,
            ...checkinPayload,
          })
        : returnTool(makerspaceSlug, {
            payload: input.payload,
            evidence_id: returnEvidenceId as number,
            remark: returnRemark.trim(),
            ...checkinPayload,
          }),
    onSuccess: (_, input) => {
      invalidatePublicInventory(queryClient, makerspaceSlug);
      if (input.operation === "checkout") {
        setPendingPayloads([]);
        setIssueEvidenceId(null);
      } else {
        setReturnEvidenceId(null);
        setReturnRemark("");
      }
      setUploadKey((key) => key + 1);
    },
  });
  const canSubmitCheckout =
    identityReady && issueEvidenceId !== null && pendingPayloads.length > 0;
  const canReturn =
    identityReady && returnEvidenceId !== null && returnRemark.trim().length > 0;

  function scanTool(payload: string) {
    const normalized = payload.trim();
    if (!normalized) {
      return;
    }
    setScannerOpen(false);
    if (mode === "checkout") {
      setPendingPayloads((current) =>
        current.includes(normalized) ? current : [...current, normalized],
      );
    } else if (canReturn) {
      loanMutation.mutate({ operation: "return", payload: normalized });
    }
  }

  return (
    <main className="desk-shell">
      <header className="border-b border-line bg-panel">
        <div className="mx-auto flex max-w-screen-xl flex-col gap-4 px-5 py-6 sm:px-8">
          <p className="eyebrow text-secondary-ink">
            Public Tool Checkout
          </p>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="min-w-0">
              <h1 className="title-page">
                <MakerspaceBrand
                  name={displayName}
                  logoUrl={bootstrap?.makerspace.logo_url}
                  size="lg"
                />
              </h1>
              <p className="mt-2 text-sm text-muted">
                Scan a physical tool label to check it out or return it.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <SpaceWorksBadge />
              <Link className="desk-button" to={tenantPath()}>
                Back to inventory
              </Link>
            </div>
          </div>
        </div>
      </header>

      <section className="mx-auto max-w-screen-sm px-5 py-6 sm:px-8">
        {bootstrapQuery.isLoading ? (
          <Card>
            <p className="text-sm text-muted">Loading checkout access...</p>
          </Card>
        ) : null}

        {bootstrapQuery.isError ? (
          <Card>
            <p className="text-sm text-danger">Could not load checkout access. Try again in a moment.</p>
          </Card>
        ) : null}
        {!bootstrapQuery.isLoading && !bootstrapQuery.isError && !enabled ? (
          <Card>
            <p className="eyebrow text-secondary-ink">
              Self-checkout
            </p>
            <h2 className="title-panel mt-2">
              Self-checkout is not enabled for this makerspace.
            </h2>
            <Link className="desk-button mt-4" to={tenantPath()}>
              Back to inventory
            </Link>
          </Card>
        ) : null}

        {!bootstrapQuery.isLoading && !bootstrapQuery.isError && enabled ? (
          <Card>
            {requiresCheckin ? (
              <div className="mb-4">
                <CheckinIdentityStep
                  makerspaceSlug={makerspaceSlug}
                  confirmed={confirmedCheckin}
                  onConfirm={(match) => {
                    setConfirmedCheckin(match);
                    setIssueEvidenceId(null);
                    setReturnEvidenceId(null);
                    setUploadKey((key) => key + 1);
                  }}
                  disabled={loanMutation.isPending}
                />
              </div>
            ) : null}
            <div
              aria-label="Checkout mode"
              className="desk-panel mt-4 flex gap-1 p-1"
            >
              <button
                aria-pressed={mode === "checkout"}
                className={
                  mode === "checkout"
                    ? "desk-tab desk-tab-active border-secondary bg-secondary text-on-secondary hover:bg-secondary hover:text-on-secondary"
                    : "desk-tab hover:text-secondary-ink"
                }
                type="button"
                onClick={() => setMode("checkout")}
              >
                Use (check out)
              </button>
              <button
                aria-pressed={mode === "return"}
                className={
                  mode === "return"
                    ? "desk-tab desk-tab-active border-secondary bg-secondary text-on-secondary hover:bg-secondary hover:text-on-secondary"
                    : "desk-tab hover:text-secondary-ink"
                }
                type="button"
                onClick={() => setMode("return")}
              >
                Return
              </button>
            </div>

            <div className="mt-4">
              {mode === "checkout" ? (
                <PublicEvidenceUpload
                  key={`issue-${uploadKey}`}
                  slug={makerspaceSlug}
                  evidenceType="issue"
                  checkinIdentity={
                    requiresCheckin ? confirmedCheckin ?? undefined : undefined
                  }
                  disabled={!identityReady || loanMutation.isPending}
                  onUploaded={setIssueEvidenceId}
                />
              ) : (
                <>
                  <PublicEvidenceUpload
                    key={`return-${uploadKey}`}
                    slug={makerspaceSlug}
                    evidenceType="return"
                    checkinIdentity={
                      requiresCheckin ? confirmedCheckin ?? undefined : undefined
                    }
                    disabled={!identityReady || loanMutation.isPending}
                    onUploaded={setReturnEvidenceId}
                  />
                  <label className="mt-3 block">
                    <span className="eyebrow mb-1 block">
                      Return condition notes
                    </span>
                    <textarea
                      className="desk-input min-h-24 w-full"
                      required
                      value={returnRemark}
                      onChange={(event) => setReturnRemark(event.target.value)}
                    />
                  </label>
                </>
              )}
            </div>

            {mode === "checkout" ? (
              <PendingToolCheckoutControls
                payloads={pendingPayloads}
                isPending={loanMutation.isPending}
                submitDisabled={!canSubmitCheckout}
                showScanWhenEmpty
                pendingLabel="Submitting..."
                onRemove={(payload) =>
                  setPendingPayloads((current) =>
                    current.filter((item) => item !== payload),
                  )
                }
                onScanAnother={() => setScannerOpen(true)}
                onSubmit={() =>
                  loanMutation.mutate({ operation: "checkout", payloads: pendingPayloads })
                }
              />
            ) : (
              <button
                className="desk-button-primary mt-4 w-full disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!canReturn || loanMutation.isPending}
                type="button"
                onClick={() => setScannerOpen(true)}
              >
                {loanMutation.isPending ? "Submitting..." : "Scan QR"}
              </button>
            )}

            {loanMutation.isError ? (
              <p className="mt-4 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
                {loanMutation.error.message}
              </p>
            ) : null}

            {loanMutation.isSuccess ? (
              <div className="mt-4">
                <PublicSelfCheckoutResult result={loanMutation.data} />
              </div>
            ) : null}
          </Card>
        ) : null}
      </section>

      {scannerOpen ? (
        <QrScanner onClose={() => setScannerOpen(false)} onScan={scanTool} />
      ) : null}
    </main>
  );
}

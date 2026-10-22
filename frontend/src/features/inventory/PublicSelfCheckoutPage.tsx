import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { QrCode } from "lucide-react";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { Button, Card, EmptyState, ErrorText, Field, PageHeader, SegmentedControl, Skeleton, Textarea, buttonClasses, useToast } from "../../components/ui";
import QrScanner from "../../components/ui/QrScanner";
import { featureEnabled } from "../../lib/features";
import { useModules } from "../../lib/modules";
import { CheckinIdentityStep } from "./CheckinIdentityStep";
import { PendingToolCheckoutControls } from "./PendingToolCheckoutControls";
import { PublicEvidenceUpload } from "./PublicEvidenceUpload";
import type { CheckinMatch } from "./api";
import { checkoutTool, returnTool } from "./selfCheckoutApi";
import { PublicSelfCheckoutResult } from "./PublicSelfCheckoutResult";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import { useMakerspacePublic } from "./useMakerspacePublic";

type Mode = "checkout" | "return";

type MutationInput =
  | { operation: "checkout"; payloads: string[] }
  | { operation: "return"; payload: string };

export function PublicSelfCheckoutPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const space = useMakerspacePublic();
  const { tenant, makerspaceSlug, tenantPath, bootstrapQuery, bootstrap, displayName } = space;
  const { moduleEnabled } = useModules();
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

  const features = tenant.mode === "single" ? tenant.bootstrap?.features ?? [] : bootstrap?.features ?? [];
  const requiresCheckin = bootstrap?.makerspace.request_access === "checked_in";
  // Off the check-in roster the backend demands membership, waiver and presence, which
  // nobody can hold with `membership` off, so the feature alone does not make it usable.
  const enabled =
    featureEnabled(features, "inventory.self_checkout") &&
    (requiresCheckin || moduleEnabled("membership"));
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
      showToast(input.operation === "checkout" ? "Tool checked out" : "Tool returned", { tone: "success" });
    },
    onError: (_, input) => showToast(input.operation === "checkout" ? "Checkout failed" : "Return failed", { tone: "error" }),
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

  const ready = !bootstrapQuery.isLoading && !bootstrapQuery.isError;

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Tool checkout" />}>
      <PublicContainer width="sm">
        <PageHeader
          kicker="Public tool checkout"
          title={<MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace?.logo_url} size="lg" />}
          description="Scan a physical tool label to check it out or return it."
        />

        <div className="mt-8">
          {bootstrapQuery.isLoading ? (
            <Card aria-busy="true" aria-label="Loading checkout access" className="space-y-3">
              <Skeleton className="h-10 w-full rounded-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-11 w-full rounded-full" />
            </Card>
          ) : null}

          {bootstrapQuery.isError ? (
            <EmptyState tone="error" title="Checkout access didn't load" description="Try again in a moment." />
          ) : null}

          {ready && !enabled ? (
            <EmptyState
              title="Self-checkout is not enabled for this makerspace."
              description="Browse the inventory and send a borrow request instead."
              action={<Link className={buttonClasses({ variant: "secondary" })} to={tenantPath()}>Back to inventory</Link>}
            />
          ) : null}

          {ready && enabled ? (
            <Card className="space-y-4">
              {requiresCheckin ? (
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
              ) : null}
              <SegmentedControl
                ariaLabel="Checkout mode"
                className="grid w-full grid-cols-2"
                value={mode}
                onValueChange={setMode}
                options={[
                  { value: "checkout", label: "Use (check out)" },
                  { value: "return", label: "Return" },
                ]}
              />

              {mode === "checkout" ? (
                <PublicEvidenceUpload
                  key={`issue-${uploadKey}`}
                  slug={makerspaceSlug}
                  evidenceType="issue"
                  checkinIdentity={requiresCheckin ? confirmedCheckin ?? undefined : undefined}
                  disabled={!identityReady || loanMutation.isPending}
                  onUploaded={setIssueEvidenceId}
                />
              ) : (
                <>
                  <PublicEvidenceUpload
                    key={`return-${uploadKey}`}
                    slug={makerspaceSlug}
                    evidenceType="return"
                    checkinIdentity={requiresCheckin ? confirmedCheckin ?? undefined : undefined}
                    disabled={!identityReady || loanMutation.isPending}
                    onUploaded={setReturnEvidenceId}
                  />
                  <Field label="Return condition notes" helperText="Describe the tool's condition as you hand it back.">
                    <Textarea required value={returnRemark} onChange={(event) => setReturnRemark(event.target.value)} />
                  </Field>
                </>
              )}

              {mode === "checkout" ? (
                <PendingToolCheckoutControls
                  payloads={pendingPayloads}
                  isPending={loanMutation.isPending}
                  submitDisabled={!canSubmitCheckout}
                  showScanWhenEmpty
                  pendingLabel="Submitting…"
                  onRemove={(payload) => setPendingPayloads((current) => current.filter((item) => item !== payload))}
                  onScanAnother={() => setScannerOpen(true)}
                  onSubmit={() => loanMutation.mutate({ operation: "checkout", payloads: pendingPayloads })}
                />
              ) : (
                <Button
                  variant="primary"
                  fullWidth
                  startIcon={<QrCode />}
                  disabled={!canReturn}
                  loading={loanMutation.isPending}
                  loadingLabel="Submitting…"
                  onClick={() => setScannerOpen(true)}
                >
                  Scan QR
                </Button>
              )}

              {loanMutation.isError ? <ErrorText message={loanMutation.error.message} /> : null}
              {loanMutation.isSuccess ? <PublicSelfCheckoutResult result={loanMutation.data} /> : null}
            </Card>
          ) : null}
        </div>
      </PublicContainer>

      {scannerOpen ? <QrScanner onClose={() => setScannerOpen(false)} onScan={scanTool} /> : null}
    </PublicShell>
  );
}

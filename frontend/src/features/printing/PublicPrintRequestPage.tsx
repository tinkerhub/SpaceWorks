import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { MakerspaceBrand } from "../../components/MakerspaceBrand";
import { PageHeader, useToast } from "../../components/ui";
import { useMakerspacePublic } from "../inventory/useMakerspacePublic";
import { PrintDetailsForm, initialForm, optional, printQuantity, type FormState } from "./PublicPrintRequestForm";
import { fetchPrintQueues, fetchPublicConsumablePools, fetchPrintStatus, presignPrintUpload, submitPrintRequest, uploadToStorage } from "./publicApi";
import { PrintAccessErrorPanel, PrintAccessLoadingPanel, PrintStatusPanel, PrintUnavailablePanel } from "./PublicPrintRequestPanels";
import { uploadPrintFilesBounded } from "./PublicPrintUploads";
import { CheckinIdentityStep } from "../inventory/CheckinIdentityStep";
import type { CheckinMatch } from "../inventory/api";
import { PublicSignInCallout, memberSignInHref } from "../inventory/PublicSignInCallout";
import { usePublicSession } from "../inventory/usePublicSession";
import { readStorage, writeStorage } from "../../lib/safeStorage";

export function PublicPrintRequestPage() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const space = useMakerspacePublic();
  const { tenant, makerspaceSlug, tenantPath, bootstrapQuery, bootstrap, displayName } = space;
  const [form, setForm] = useState<FormState>(initialForm);
  const [modelFiles, setModelFiles] = useState<File[]>([]);
  const [screenshotFiles, setScreenshotFiles] = useState<File[]>([]);
  const [uploadProgress, setUploadProgress] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [activeStatusToken, setActiveStatusToken] = useState("");
  const [website, setWebsite] = useState("");
  const [confirmedCheckin, setConfirmedCheckin] = useState<CheckinMatch | null>(null);
  const statusLinkHandledRef = useRef(false);
  const modules = useMemo(() => tenant.mode === "single" ? tenant.modules : new Set(bootstrap?.modules ?? []), [bootstrap?.modules, tenant]);
  // The public printer API is gated on `printing` (which itself requires machine_service).
  const moduleEnabled = modules.has("printing");
  const queuesQuery = useQuery({ queryKey: ["public-printer-queues", makerspaceSlug], queryFn: () => fetchPrintQueues(makerspaceSlug), enabled: Boolean(makerspaceSlug) && moduleEnabled });
  const poolsQuery = useQuery({ queryKey: ["public-printer-consumable-pools", makerspaceSlug], queryFn: () => fetchPublicConsumablePools(makerspaceSlug), enabled: Boolean(makerspaceSlug) && moduleEnabled });
  const printerAvailable = Boolean(queuesQuery.data?.length);
  const enabled = moduleEnabled && printerAvailable;
  const requiresCheckin = bootstrap?.makerspace.request_access === "checked_in";
  const identityReady = !requiresCheckin || confirmedCheckin !== null;
  const checkinPayload = requiresCheckin && confirmedCheckin ? { name: confirmedCheckin.name, checkin_mid: confirmedCheckin.mid } : {};
  // Off the roster a print request is filed under the signed-in account.
  const session = usePublicSession(makerspaceSlug, enabled && !requiresCheckin);
  const needsSignIn = !requiresCheckin && session.signedOut;
  const statusQuery = useQuery({ queryKey: ["public-printer-status", activeStatusToken], queryFn: () => fetchPrintStatus(activeStatusToken), enabled: Boolean(activeStatusToken), refetchInterval: (query) => {
    const status = query.state.data?.status;
    return status === "in_progress" ? 30_000 : status === "pending" || status === "accepted" ? 90_000 : false;
  }});
  const statusStorageKey = makerspaceSlug ? `tinkerspace.printStatus.${makerspaceSlug}` : "";
  useEffect(() => { if (statusLinkHandledRef.current) return; statusLinkHandledRef.current = true; const token = new URLSearchParams(window.location.search).get("token")?.trim(); const stored = statusStorageKey ? readStorage(statusStorageKey).trim() : ""; if (token || stored) setActiveStatusToken(token || stored || ""); }, [statusStorageKey]);
  useEffect(() => { if (statusStorageKey && activeStatusToken) writeStorage(statusStorageKey, activeStatusToken); }, [activeStatusToken, statusStorageKey]);
  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) { setForm((current) => ({ ...current, [key]: value })); }
  const submitMutation = useMutation({ mutationFn: async () => {
    const files = [...modelFiles.map((file) => ({ file, kind: "stl" as const })), ...screenshotFiles.map((file) => ({ file, kind: "screenshot" as const }))];
    const fileIds = await uploadPrintFilesBounded(files, async (item) => { const presigned = await presignPrintUpload(makerspaceSlug, { kind: item.kind, filename: item.file.name, content_type: item.kind === "stl" ? item.file.type || "application/octet-stream" : item.file.type, ...checkinPayload }); await uploadToStorage(presigned.upload, item.file); return presigned.file_id; }, setUploadProgress);
    const chosenPool = poolsQuery.data?.find((pool) => String(pool.id) === form.consumablePoolId);
    return submitPrintRequest(makerspaceSlug, { website, queue_id: queuesQuery.data?.[0]?.id ?? null, title: form.title.trim(), project_brief: optional(form.projectBrief), preferred_settings: optional(form.preferredSettings), material: chosenPool?.material, color: chosenPool?.color, consumable_pool_id: form.consumablePoolId ? Number(form.consumablePoolId) : null, estimated_filament_grams: form.estimatedFilamentGrams.trim() || null, quantity: printQuantity(form.quantity), source_link: optional(form.sourceLink), file_ids: fileIds, ...checkinPayload });
  }, onSuccess: (response) => { queryClient.invalidateQueries({ queryKey: ["public-printer-consumable-pools", makerspaceSlug] }); setUploadProgress(""); setForm(initialForm); setModelFiles([]); setScreenshotFiles([]); setSubmitted(true); setActiveStatusToken(response.public_token); showToast("Print request submitted", { tone: "success" }); }, onError: () => { setUploadProgress(""); showToast("Print request wasn't submitted", { tone: "error" }); } });
  const identityStep = requiresCheckin ? <CheckinIdentityStep makerspaceSlug={makerspaceSlug} confirmed={confirmedCheckin} onConfirm={setConfirmedCheckin} disabled={submitMutation.isPending} /> : undefined;
  const settled = !bootstrapQuery.isLoading && !queuesQuery.isLoading && !bootstrapQuery.isError && !queuesQuery.isError;
  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={(key) => modules.has(key)} page="3D printing" />}>
      <PublicContainer>
        <PageHeader
          kicker="Public 3D print request"
          title={<MakerspaceBrand name={displayName} logoUrl={bootstrap?.makerspace?.logo_url} size="lg" />}
          description="Submit print files and keep your private token link to check progress."
        />
        <div className="mt-8">
          {bootstrapQuery.isLoading || (moduleEnabled && queuesQuery.isLoading) ? <PrintAccessLoadingPanel /> : null}
          {bootstrapQuery.isError || queuesQuery.isError ? <PrintAccessErrorPanel /> : null}
          {settled && !enabled ? (
            <div className="mx-auto max-w-[640px]">
              <PrintUnavailablePanel catalogPath={tenantPath()} tokenStatus={statusQuery.data} tokenStatusPending={Boolean(activeStatusToken) && statusQuery.isPending} tokenStatusError={statusQuery.error} />
            </div>
          ) : null}
          {enabled ? (
            <section className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_360px]" aria-label="Print request">
              {needsSignIn ? (
                <PublicSignInCallout href={memberSignInHref(space.header.homePath, modules.has("member_accounts"))}>
                  Print requests are filed under your member account.
                </PublicSignInCallout>
              ) : <PrintDetailsForm
                form={form}
                updateField={updateField}
                poolsQuery={poolsQuery}
                modelFiles={modelFiles}
                setModelFiles={setModelFiles}
                screenshotFiles={screenshotFiles}
                setScreenshotFiles={setScreenshotFiles}
                submitPending={submitMutation.isPending}
                identityReady={identityReady}
                identityStep={identityStep}
                submitError={submitMutation.error}
                uploadProgress={uploadProgress}
                website={website}
                onWebsiteChange={setWebsite}
                onSubmit={(event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (form.title.trim() && identityReady && !submitMutation.isPending) submitMutation.mutate(); }}
              />}
              <aside aria-label="Print status">
                <PrintStatusPanel submitted={submitted} tokenStatus={statusQuery.data} tokenStatusPending={Boolean(activeStatusToken) && statusQuery.isPending} tokenStatusError={statusQuery.error} />
              </aside>
            </section>
          ) : null}
        </div>
      </PublicContainer>
    </PublicShell>
  );
}

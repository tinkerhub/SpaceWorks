import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, CheckboxField, ErrorText, Field, Input, SettingsRow, StatusChip, useToast } from "../../components/ui";
import type { ApiPath } from "../../generated/api";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace } from "./panels/shared";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
  isSuperadmin: boolean;
};

type VerifyDomainResponse = {
  status: DomainStatus;
  token: string;
  expected_record: DomainRecord | null;
  verified_at: string | null;
  detail: string;
};

type DomainStatus = "pending" | "verified" | "failed";
type DomainRecord = { host: string; type: "TXT"; value: string };

const VERIFY_DOMAIN_API_PATH: ApiPath = "/api/v1/admin/makerspace/{makerspace_id}/verify-domain";

function verifyDomainStaffPath(makerspaceId: number) {
  return VERIFY_DOMAIN_API_PATH.replace("/api/v1", "").replace("{makerspace_id}", String(makerspaceId));
}

export function MakerspaceCustomDomainSettings({ makerspace, settings, loading, isSuperadmin }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [domainInput, setDomainInput] = useState("");
  const [hideFromDirectory, setHideFromDirectory] = useState(false);
  const [verifyDetail, setVerifyDetail] = useState("");

  const currentDomain = settings?.frontend_domain ?? makerspace.frontend_domain ?? null;
  const currentHidden =
    settings?.hidden_from_central_directory ?? makerspace.hidden_from_central_directory ?? false;
  const status = settings?.frontend_domain_status ?? makerspace.frontend_domain_status ?? "pending";
  const record = settings?.domain_verification_record ?? makerspace.domain_verification_record ?? null;
  const token = settings?.domain_verification_token ?? makerspace.domain_verification_token ?? "";
  // On a self-hosted instance (`platform_hosting` false) the backend lets only a superadmin
  // change the domain (`validate_frontend_domain`). Unknown hosting reads as self-hosted.
  const domainReadOnly = !isSuperadmin && (settings?.platform_hosting ?? makerspace.platform_hosting) !== true;

  useEffect(() => {
    setDomainInput(currentDomain ?? "");
    setHideFromDirectory(Boolean(currentDomain) && currentHidden);
    setVerifyDetail("");
  }, [currentDomain, currentHidden, makerspace.id]);

  const refreshSettings = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };

  const trimmedDomain = domainInput.trim();
  const hasDomainInput = trimmedDomain.length > 0;
  const effectiveHidden = hasDomainInput ? hideFromDirectory : false;
  const domainChanged = trimmedDomain !== (currentDomain ?? "");
  const hiddenChanged = effectiveHidden !== currentHidden;
  const customDomainUrls = useMemo(
    () => [`https://${trimmedDomain}/`, `https://${trimmedDomain}/admin`],
    [trimmedDomain],
  );

  const updateCustomDomain = useMutation({
    mutationFn: () =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          frontend_domain: trimmedDomain,
          hidden_from_central_directory: effectiveHidden,
        }),
      }),
    onSuccess: (updated) => {
      setDomainInput(updated.frontend_domain ?? "");
      setHideFromDirectory(
        Boolean(updated.frontend_domain) && updated.hidden_from_central_directory,
      );
      setVerifyDetail("");
      refreshSettings();
      showToast("Domain saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the domain"), { tone: "error" }),
  });

  const verifyDomain = useMutation({
    mutationFn: () =>
      staffRequest<VerifyDomainResponse>(verifyDomainStaffPath(makerspace.id), {
        method: "POST",
      }),
    onSuccess: (result) => {
      setVerifyDetail(result.detail);
      refreshSettings();
      showToast(result.status === "verified" ? "Domain verified" : "Domain not verified yet", { tone: result.status === "verified" ? "success" : "warning" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't check the domain"), { tone: "error" }),
  });

  const domainSaveDisabled =
    loading || updateCustomDomain.isPending || (!domainChanged && !hiddenChanged);
  const verifyDisabled = loading || verifyDomain.isPending || !currentDomain || domainChanged;
  const visibleRecord = domainChanged ? null : record;
  // Self-host mode returns no DNS verification record; a VERIFIED domain with no
  // record is trusted automatically, so show a compact "Active" state and hide the
  // TXT-record instructions + Verify button (managed domains keep the DNS/verify UI).
  const isSelfHostActive =
    Boolean(currentDomain) && !record && status === "verified" && !domainChanged;

  return (
    <Card as="section" aria-labelledby="custom-domain-title">
      <form
        className="grid min-w-0"
        onSubmit={(event) => {
          event.preventDefault();
          if (!domainSaveDisabled) {
            updateCustomDomain.mutate();
          }
        }}
      >
        <CardHeader
          className="mb-0"
          title={<span id="custom-domain-title">Custom domain</span>}
          description="Route this makerspace's public and staff pages through a dedicated domain."
          action={(
            <StatusChip tone={isSelfHostActive ? "success" : domainStatusTone(status)}>
              {isSelfHostActive ? "Active" : domainStatusLabel(status)}
            </StatusChip>
          )}
        />

        <SettingsRow title="Address" description="Staff use it at /admin; the public site lives at its root.">
          <div className="grid min-w-0 max-w-xl gap-4">
            <Field
              label="Domain"
              id="custom-domain"
              helperText={domainReadOnly ? "Only a superadmin can change the custom domain on this instance." : undefined}
            >
              <Input
                placeholder="alphamakerspace.com"
                readOnly={domainReadOnly}
                value={domainInput}
                onChange={(event) => {
                  const next = event.target.value;
                  setDomainInput(next);
                  if (!next.trim()) {
                    setHideFromDirectory(false);
                  }
                }}
              />
            </Field>
            <CheckboxField
              label="Hide from central directory"
              description="Available only after a custom domain is set."
              checked={effectiveHidden}
              disabled={!hasDomainInput}
              onCheckedChange={(value) => setHideFromDirectory(value === true)}
            />
          </div>
        </SettingsRow>

        {hasDomainInput ? (
          <SettingsRow title="Setup" description="Point DNS and your reverse proxy at this deployment.">
            <div className="grid min-w-0 gap-4 text-body-ui text-ink-secondary">
              <div className="min-w-0">
                <p className="text-label text-ink">Resulting URLs</p>
                <ul className="mt-1.5 grid gap-1">
                  {customDomainUrls.map((url) => (
                    <li className="break-all font-mono text-sm" key={url}>{url}</li>
                  ))}
                </ul>
              </div>
              {visibleRecord ? <DnsRecord record={visibleRecord} /> : null}
              <p>
                TLS and reverse proxy routing must terminate HTTPS for this hostname and forward both
                the public site and <code className="font-mono">/admin</code> staff console to this deployment.
              </p>
              {isSelfHostActive ? (
                <Callout tone="success">
                  This custom domain is active. Staff and public traffic on this hostname are
                  trusted automatically on a self-hosted instance.
                </Callout>
              ) : (
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={verifyDisabled}
                    loading={verifyDomain.isPending}
                    loadingLabel="Checking…"
                    onClick={() => verifyDomain.mutate()}
                  >
                    Verify domain
                  </Button>
                  {token ? <span className="break-all text-caption text-ink-muted">Token: <span className="font-mono">{token}</span></span> : null}
                </div>
              )}
              {domainChanged && currentDomain ? (
                <p className="text-caption text-ink-muted">Save the new domain before verifying DNS.</p>
              ) : null}
              {verifyDetail ? <p className="text-body-ui text-ink" role="status">{verifyDetail}</p> : null}
            </div>
          </SettingsRow>
        ) : null}

        <div className="grid gap-2">
          <ErrorText message={updateCustomDomain.error?.message} />
          <ErrorText message={verifyDomain.error?.message} />
        </div>
        <div className="flex justify-end pt-4">
          <Button variant="primary" type="submit" disabled={domainSaveDisabled} loading={updateCustomDomain.isPending} loadingLabel="Saving…">
            Save domain
          </Button>
        </div>
      </form>
    </Card>
  );
}

function DnsRecord({ record }: { record: DomainRecord }) {
  return (
    <div className="grid min-w-0 gap-2">
      <p className="text-label text-ink">DNS TXT record</p>
      <dl className="grid min-w-0 gap-x-4 gap-y-2 rounded-md border border-line bg-subtle p-3 sm:grid-cols-[96px_minmax(0,1fr)]">
        <dt className="text-caption text-ink-muted">Host</dt>
        <dd className="break-all font-mono text-sm text-ink">{record.host}</dd>
        <dt className="text-caption text-ink-muted">Type</dt>
        <dd className="font-mono text-sm text-ink">{record.type}</dd>
        <dt className="text-caption text-ink-muted">Value</dt>
        <dd className="break-all font-mono text-sm text-ink">{record.value}</dd>
      </dl>
    </div>
  );
}

function domainStatusTone(status: DomainStatus) {
  return status === "verified" ? "success" : status === "failed" ? "danger" : "warning";
}

function domainStatusLabel(status: DomainStatus) {
  return {
    pending: "Pending",
    verified: "Verified",
    failed: "Failed",
  }[status];
}

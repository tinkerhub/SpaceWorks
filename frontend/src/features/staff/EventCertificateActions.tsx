import { useState } from "react";

import { Button, ConfirmDialog, ErrorText, StatusChip, useToast, type StatusTone } from "../../components/ui";
import {
  useCertificateAction,
  useCertificateDownload,
  type CertificateSummary,
} from "./eventFeedbackApi";
import { eventErrorText, eventStatusLabel } from "./eventUi";

const CERTIFICATE_TONES: Record<string, StatusTone> = {
  active: "success",
  pending: "info",
  failed: "danger",
  revoked: "neutral",
};

export function EventCertificateActions({ certificate, eventId, makerspaceId }: {
  certificate: CertificateSummary;
  eventId: number;
  makerspaceId: number;
}) {
  const download = useCertificateDownload(eventId, makerspaceId);
  const revoke = useCertificateAction(eventId, makerspaceId, "revoke");
  const reissue = useCertificateAction(eventId, makerspaceId, "reissue");
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const { showToast } = useToast();
  const failed = (cause: unknown) => showToast(eventErrorText(cause), { tone: "error" });
  const error = download.error || revoke.error || reissue.error;
  const downloadLabel = certificate.status === "active" ? "Download" : "Prepare certificate";
  return (
    <div className="mt-3 grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip tone={CERTIFICATE_TONES[certificate.status] ?? "neutral"} size="sm">{eventStatusLabel(certificate.status)}</StatusChip>
        <span className="text-caption text-ink-muted">Certificate <span className="font-mono">r{certificate.revision}</span></span>
        {certificate.status === "active" || certificate.status === "pending" || certificate.status === "failed" ? (
          <Button size="sm" loading={download.isPending} onClick={() => download.mutate(certificate.id, { onSuccess: (result) => window.location.assign(result.url), onError: failed })}>{downloadLabel}</Button>
        ) : null}
        {certificate.status === "active" ? <Button size="sm" variant="danger-quiet" disabled={revoke.isPending} onClick={() => setConfirmRevoke(true)}>Revoke…</Button> : null}
        {certificate.status === "revoked" ? (
          <Button size="sm" variant="success" loading={reissue.isPending} onClick={() => reissue.mutate(certificate.id, { onSuccess: () => showToast("Certificate reissued", { tone: "success" }), onError: failed })}>Reissue</Button>
        ) : null}
      </div>
      {error ? <ErrorText message={eventErrorText(error)} /> : null}
      <ConfirmDialog
        open={confirmRevoke}
        title="Revoke certificate?"
        message="This attendee loses the certificate. You can reissue it later."
        confirmLabel="Revoke"
        tone="danger"
        pending={revoke.isPending}
        onCancel={() => setConfirmRevoke(false)}
        onConfirm={() => revoke.mutate(certificate.id, {
          onSuccess: () => { setConfirmRevoke(false); showToast("Certificate revoked", { tone: "success" }); },
          onError: (cause) => { setConfirmRevoke(false); failed(cause); },
        })}
      />
    </div>
  );
}

import { useEffect, useState, type ReactNode } from "react";
import { ImageIcon } from "lucide-react";

import { Button, DetailDrawer, ErrorBlock, SectionHeading, type StatusTone } from "../../../components/ui";
import { StatusStepper } from "../../../components/ui/StatusStepper";
import { staffRequest } from "../../../lib/api";
import { evidenceErrorText } from "../evidenceUi";
import type { HardwareRequest, RequestItem } from "./Queues";
import { RequestTimelineBlock } from "./LoanTimeline";
import { StatusWord } from "./shared";

type RequestActor = { username: string; role: string };
type RequestAttributionFields = {
  accepted_by?: RequestActor | null;
  issued_by?: RequestActor | null;
};

const REQUEST_STATUS: Record<string, { label: string; tone: StatusTone }> = {
  draft: { label: "Draft", tone: "neutral" },
  pending_approval: { label: "Pending review", tone: "warning" },
  accepted: { label: "Approved", tone: "info" },
  issued: { label: "On loan", tone: "info" },
  partially_returned: { label: "Partly returned", tone: "warning" },
  returned: { label: "Returned", tone: "success" },
  rejected: { label: "Rejected", tone: "danger" },
  closed_with_issue: { label: "Closed with issue", tone: "danger" },
};

/** The request's workflow status as a word + icon chip. */
export function RequestStatus({ status }: { status: string }) {
  const known = REQUEST_STATUS[status];
  return <StatusWord status={status} label={known?.label} tone={known?.tone ?? "neutral"} />;
}

/** Date + time without seconds, in the viewer's locale. */
export function formatWhen(value: string) {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function hasItemIssues(item: RequestItem) {
  return Boolean(item.damaged_quantity || item.missing_quantity || item.needs_fix_quantity);
}

function formatActor(actor: RequestActor) {
  return actor.role ? `${actor.username} (${actor.role})` : actor.username;
}

/** Everything about one request that does not fit a table row: progress, people, evidence, timeline. */
export function RequestDetailDrawer({ row, canViewAudit, onClose }: { row: HardwareRequest | null; canViewAudit: boolean; onClose: () => void }) {
  const [evidenceError, setEvidenceError] = useState("");
  const [opening, setOpening] = useState<number | null>(null);

  useEffect(() => {
    setEvidenceError("");
    setOpening(null);
  }, [row?.id]);

  // Evidence object keys are never exposed; fetch a short-lived signed URL on click and open it.
  const openEvidence = async (evidenceId: number) => {
    setEvidenceError("");
    setOpening(evidenceId);
    try {
      const res = await staffRequest<{ url: string }>(`/admin/evidence/${evidenceId}`);
      window.open(res.url, "_blank", "noopener");
    } catch (error) {
      setEvidenceError(evidenceErrorText(error));
    } finally {
      setOpening(null);
    }
  };

  const attributed = row as (HardwareRequest & RequestAttributionFields) | null;
  const returnIds = row?.return_evidence_ids ?? [];
  const issues = row?.items.filter(hasItemIssues) ?? [];

  return (
    <DetailDrawer open={Boolean(row)} title={row ? `Request #${row.id}` : "Request"} onClose={onClose}>
      {row ? (
        <div className="grid gap-6">
          <div className="flex flex-wrap items-center gap-2">
            <RequestStatus status={row.status} />
            <span className="text-body-ui text-ink-secondary">{row.requester_display || row.requester_username}</span>
          </div>
          <StatusStepper status={row.status} />
          <dl className="grid gap-3 rounded-lg border border-line p-4 text-body-ui sm:grid-cols-[max-content_minmax(0,1fr)] sm:gap-x-6">
            <DetailRow label="Purpose">{row.requested_for || "No note"}</DetailRow>
            {row.requester_contact_email || row.requester_contact_phone ? (
              <DetailRow label="Contact">{[row.requester_contact_email, row.requester_contact_phone].filter(Boolean).join(" · ")}</DetailRow>
            ) : null}
            {row.checkin_purpose || row.checkin_project_name ? (
              <DetailRow label="Checked in">
                {[row.checkin_purpose, row.checkin_project_name].filter(Boolean).join(" · ")}
                {row.checkin_verified_at ? ` · verified ${formatWhen(row.checkin_verified_at)}` : ""}
              </DetailRow>
            ) : null}
            {attributed?.accepted_by ? <DetailRow label="Accepted by">{formatActor(attributed.accepted_by)}</DetailRow> : null}
            {attributed?.issued_by ? <DetailRow label="Issued by">{formatActor(attributed.issued_by)}</DetailRow> : null}
            {row.assigned_box_label ? <DetailRow label="Box">{row.assigned_box_label}</DetailRow> : null}
            <DetailRow label="Return due">
              {row.return_due_at ? formatWhen(row.return_due_at) : "Not set"}
              {row.return_reminder_sent_at ? ` · reminder sent ${formatWhen(row.return_reminder_sent_at)}` : ""}
            </DetailRow>
            {row.status === "rejected" && row.rejection_reason ? (
              <DetailRow label="Rejected because"><span className="text-danger-fg">{row.rejection_reason}</span></DetailRow>
            ) : null}
          </dl>
          <section className="grid gap-3">
            <SectionHeading as="h3" title="Items" />
            <ul className="grid gap-2">
              {row.items.map((item) => (
                <li key={item.id} className="rounded-lg border border-line px-4 py-3 text-body-ui">
                  <p className="font-semibold text-ink">{item.product_name} <span className="font-normal text-ink-muted">×{item.requested_quantity}</span></p>
                  {item.storage_location ? <p className="text-caption text-ink-muted">Shelf: {item.storage_location}</p> : null}
                </li>
              ))}
            </ul>
            {issues.length ? (
              <ul className="grid gap-1 rounded-lg bg-danger-bg px-4 py-3 text-body-ui text-danger-fg">
                {issues.map((item) => (
                  <li key={item.id}>
                    {item.product_name}:
                    {item.damaged_quantity ? ` ${item.damaged_quantity} damaged` : ""}
                    {item.missing_quantity ? ` ${item.missing_quantity} missing` : ""}
                    {item.needs_fix_quantity ? ` ${item.needs_fix_quantity} to fix` : ""}
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
          {row.issue_evidence_id || returnIds.length > 0 ? (
            <section className="grid gap-3">
              <SectionHeading as="h3" title="Evidence" />
              <div className="flex flex-wrap gap-2">
                {row.issue_evidence_id ? (
                  <Button size="sm" startIcon={<ImageIcon />} loading={opening === row.issue_evidence_id} onClick={() => void openEvidence(row.issue_evidence_id as number)}>View issue photo</Button>
                ) : null}
                {returnIds.map((id, index) => (
                  <Button key={id} size="sm" startIcon={<ImageIcon />} loading={opening === id} onClick={() => void openEvidence(id)}>
                    View return photo{returnIds.length > 1 ? ` ${index + 1}` : ""}
                  </Button>
                ))}
              </div>
              {evidenceError ? <ErrorBlock error={new Error(evidenceError)} /> : null}
            </section>
          ) : null}
          {canViewAudit ? <RequestTimelineBlock requestId={row.id} /> : null}
        </div>
      ) : null}
    </DetailDrawer>
  );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-caption font-semibold text-ink-muted sm:text-body-ui">{label}</dt>
      <dd className="min-w-0 text-ink [overflow-wrap:anywhere]">{children}</dd>
    </>
  );
}

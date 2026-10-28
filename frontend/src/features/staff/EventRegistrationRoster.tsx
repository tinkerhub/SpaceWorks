import { useState } from "react";

import {
  Button,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  ErrorText,
  SectionHeading,
  SkeletonRows,
  StatusChip,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Table,
  useToast,
  type StatusTone,
} from "../../components/ui";
import { EventCheckInOperator } from "./EventCheckInOperator";
import { EventBadgeActions } from "./EventBadgeActions";
import { EventRegisterMember } from "./EventRegisterMember";
import { PaymentReconcileActions } from "./PaymentReconcileActions";
import { useCorrectAttendance } from "./eventFeedbackApi";
import {
  eventKeys,
  useApproveEventRegistration,
  useEventRegistrations,
  useMarkEventAttended,
  usePromoteEventRegistration,
  useRejectEventRegistration,
  type StaffEvent,
} from "./eventsApi";
import { eventErrorText, eventStatusLabel } from "./eventUi";

const REGISTRATION_TONES: Record<string, StatusTone> = {
  registered: "success",
  attended: "info",
  pending_approval: "warning",
  waitlisted: "warning",
  rejected: "danger",
  cancelled: "neutral",
};

type Confirming = { id: number; name: string; action: "reject" | "correct" };

export function EventRegistrationRoster({ event, makerspaceId, offlineCheckInEnabled }: {
  event: StaffEvent;
  makerspaceId: number;
  offlineCheckInEnabled: boolean;
}) {
  const [page, setPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [includeAttended, setIncludeAttended] = useState(false);
  const [confirming, setConfirming] = useState<Confirming | null>(null);
  const { showToast } = useToast();
  const rows = useEventRegistrations(event.id, page);
  const approve = useApproveEventRegistration(makerspaceId, event.id);
  const reject = useRejectEventRegistration(makerspaceId, event.id);
  const promote = usePromoteEventRegistration(makerspaceId, event.id);
  const attended = useMarkEventAttended(makerspaceId, event.id);
  const correct = useCorrectAttendance(makerspaceId, event.id);
  const mutations = [approve, reject, promote, attended, correct];

  function pendingFor(registrationId: number) {
    return mutations.some((mutation) => mutation.isPending && mutation.variables === registrationId);
  }

  function errorFor(registrationId: number) {
    return mutations.find((mutation) => mutation.error && mutation.variables === registrationId)?.error;
  }

  // Every row action toasts its outcome; the row keeps its own inline error too.
  function run(mutate: (id: number, options: { onSuccess: () => void; onError: (error: unknown) => void }) => void, id: number, success: string) {
    mutate(id, {
      onSuccess: () => { setConfirming(null); showToast(success, { tone: "success" }); },
      onError: (error) => { setConfirming(null); showToast(eventErrorText(error), { tone: "error" }); },
    });
  }

  const fallbackCount = Object.values(event.registration_counts).reduce((sum, value) => sum + value, 0);
  const checkable = event.status === "published" || event.status === "completed";
  const results = rows.data?.results ?? [];

  return (
    <section aria-labelledby="registrations-title" className="grid gap-4">
      <SectionHeading
        as="h3"
        title={<span id="registrations-title">Registrations ({rows.data?.count ?? fallbackCount})</span>}
        description="Contact details are staff-only."
      />
      <EventRegisterMember makerspaceId={makerspaceId} eventId={event.id} customForm={event.custom_form} disabled={event.status !== "published" || !event.registration_open} />
      {checkable ? <EventCheckInOperator makerspaceId={makerspaceId} eventId={event.id} offlineEnabled={offlineCheckInEnabled} /> : null}
      {results.length ? <EventBadgeActions event={event} makerspaceId={makerspaceId} selectedIds={selectedIds} includeAttended={includeAttended} onIncludeAttended={(value) => { setIncludeAttended(value); if (!value) setSelectedIds([]); }} /> : null}
      {rows.error ? <ErrorText message={eventErrorText(rows.error)} /> : null}
      {rows.data && !results.length ? <EmptyState title="No registrations yet" description="Share the event page, or register a member above." /> : null}
      {rows.isLoading || results.length ? (
        <Table label="Registrations">
          <caption className="sr-only">Event registration contact details and badge selection</caption>
          <THead>
            <tr><TH>Badge</TH><TH>Person</TH><TH>Status</TH><TH>Action</TH></tr>
          </THead>
          <TBody>
            {rows.isLoading ? <SkeletonRows rows={4} cols={4} /> : null}
            {results.map((row) => {
              const pending = pendingFor(row.id);
              const rowError = errorFor(row.id);
              const hasAction = row.status === "pending_approval"
                || (row.status === "waitlisted" && event.registration_requires_approval)
                || (row.status === "registered" && checkable)
                || row.status === "attended";
              return (
                <TR key={row.id}>
                  <TD>
                    <Checkbox
                      aria-label={`Select ${row.name} for a badge`}
                      disabled={row.status !== "registered" && !(includeAttended && row.status === "attended")}
                      checked={selectedIds.includes(row.id)}
                      onCheckedChange={(checked) => setSelectedIds((ids) => checked === true ? [...ids, row.id] : ids.filter((id) => id !== row.id))}
                    />
                  </TD>
                  <TD>
                    <span className="block text-label text-ink">{row.name}</span>
                    <a className="block break-all text-caption text-ink-secondary hover:underline" href={`mailto:${row.email}`}>{row.email}</a>
                    {row.phone ? <a className="block text-caption text-ink-muted hover:underline" href={`tel:${row.phone}`}>{row.phone}</a> : null}
                    <PaymentReconcileActions makerspaceId={makerspaceId} payment={row.payment} invalidateKeys={[eventKeys.registrations(event.id), eventKeys.detail(event.id), eventKeys.all(makerspaceId)]} />
                  </TD>
                  <TD><StatusChip tone={REGISTRATION_TONES[row.status] ?? "neutral"} size="sm">{eventStatusLabel(row.status)}</StatusChip></TD>
                  <TD>
                    <div className="flex flex-wrap gap-2">
                      {row.status === "pending_approval" ? <Button size="sm" variant="success" disabled={pending} onClick={() => run(approve.mutate, row.id, `${row.name} approved`)}>Approve</Button> : null}
                      {row.status === "waitlisted" && event.registration_requires_approval ? <Button size="sm" variant="success" disabled={pending} onClick={() => run(promote.mutate, row.id, `${row.name} promoted`)}>Promote</Button> : null}
                      {row.status === "pending_approval" || (row.status === "waitlisted" && event.registration_requires_approval)
                        ? <Button size="sm" variant="danger-quiet" disabled={pending} onClick={() => setConfirming({ id: row.id, name: row.name, action: "reject" })}>Reject…</Button>
                        : null}
                      {row.status === "registered" && checkable ? <Button size="sm" variant="success" disabled={pending} onClick={() => run(attended.mutate, row.id, `${row.name} marked attended`)}>Mark attended</Button> : null}
                      {row.status === "attended" ? <Button size="sm" variant="danger-quiet" disabled={pending} onClick={() => setConfirming({ id: row.id, name: row.name, action: "correct" })}>Correct attendance…</Button> : null}
                      {!hasAction ? <span className="text-ink-muted">—</span> : null}
                    </div>
                    {rowError ? <p className="mt-1 text-caption text-danger-fg" role="alert">{eventErrorText(rowError)}</p> : null}
                  </TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      ) : null}
      {rows.data?.previous || rows.data?.next ? (
        <div className="flex flex-wrap items-center justify-end gap-2 text-body-ui text-ink-muted">
          <span className="mr-auto tabular-nums">Page {page}</span>
          <Button size="sm" disabled={!rows.data?.previous} onClick={() => setPage((value) => Math.max(1, value - 1))}>Previous</Button>
          <Button size="sm" disabled={!rows.data?.next} onClick={() => setPage((value) => value + 1)}>Next</Button>
        </div>
      ) : null}
      <ConfirmDialog
        open={confirming !== null}
        title={confirming?.action === "correct" ? "Correct attendance?" : "Reject registration?"}
        message={confirming?.action === "correct"
          ? `${confirming.name} goes back to registered, and any certificate issued for this event is revoked.`
          : `The registration for ${confirming?.name ?? "this person"} is rejected.`}
        confirmLabel={confirming?.action === "correct" ? "Correct attendance" : "Reject"}
        tone="danger"
        pending={reject.isPending || correct.isPending}
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (!confirming) return;
          if (confirming.action === "correct") run(correct.mutate, confirming.id, `Attendance corrected for ${confirming.name}`);
          else run(reject.mutate, confirming.id, `${confirming.name} rejected`);
        }}
      />
    </section>
  );
}

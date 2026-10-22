import { useEffect, useState, type ReactNode } from "react";
import { QrCode } from "lucide-react";

import { Button, Callout, EmptyState, ErrorText, StatusChip } from "../../components/ui";
import { AccountCard } from "../account/AccountCard";
import { staffRequestBlob } from "../../lib/api";
import { MemberEventFeedback } from "./MemberEventFeedback";
import { MemberCalendarActions } from "./MemberCalendarActions";
import { statusLabel, statusTone } from "./memberUi";

type Loan = { label: string; checked_out_at: string; due_at: string | null; overdue: boolean };
type MachineServiceRequest = { machine_type?: string; title: string; status: string; queue_position: number | null };
type Booking = { space_name: string; starts_at: string; ends_at: string; status: string };
type Registration = {
  registration_id: number;
  event_title: string;
  starts_at: string;
  status: string;
  waitlist_position: number | null;
  // Non-null only for a REGISTERED row: a waitlisted registration has nothing confirmable
  // behind it, and a QR that scans and then fails is worse than no QR at all.
  checkin_token: string | null;
  feedback_available: boolean;
  feedback_path: string | null;
  certificate: { id: number; status: string; revision: number } | null;
};
type Presence = { started_at: string; expires_at: string; active: boolean };

export type MemberActivity = {
  active_hardware_loans: Loan[];
  machine_service_requests?: MachineServiceRequest[];
  bookings?: { upcoming: Booking[]; past: Booking[] };
  event_registrations?: Registration[];
  recent_presence_sessions: Presence[];
  currently_checked_in: boolean;
  accountability: { membership_active: boolean; waiver_acceptance_required: boolean; restriction_code: string | null };
};

/** The member's own check-in QR, fetched rather than linked.
 *
 * `<img src>` cannot carry an Authorization header, so the SVG is fetched through the
 * refresh-aware authenticated path and handed to the DOM as an object URL. That URL is
 * revoked on unmount and whenever it is replaced -- otherwise every open-and-close leaks a
 * blob for the lifetime of the tab.
 */
function CheckInQr({ makerspaceId, registrationId }: { makerspaceId: number; registrationId: number }) {
  const [open, setOpen] = useState(false);
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    let url: string | null = null;
    staffRequestBlob(
      `/member/makerspaces/${makerspaceId}/event-registrations/${registrationId}/qr`,
    )
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
      })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Could not load your code.");
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
      setSrc(null);
    };
  }, [open, makerspaceId, registrationId]);

  return <div className="flex flex-col items-start gap-2">
    <Button
      size="sm"
      startIcon={<QrCode />}
      aria-expanded={open}
      onClick={() => { setError(null); setOpen((value) => !value); }}
    >
      {open ? "Hide check-in QR" : "Show check-in QR"}
    </Button>
    {/* Unmounted rather than hidden, so the blob is released and keyboard users cannot tab
        into an image that is not on screen. */}
    {open && src ? <img src={src} alt="Your check-in QR code" className="max-w-[220px] rounded-md border border-line bg-white p-2" /> : null}
    {open && error ? <ErrorText message={error} /> : null}
  </div>;
}

function Section({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return <AccountCard title={title} description={description}>{children}</AccountCard>;
}
function Empty({ children = "Nothing to show yet." }: { children?: ReactNode }) {
  return <EmptyState className="min-h-0 py-5" title={children} />;
}
function Rows({ children }: { children: ReactNode }) {
  return <ul className="divide-y divide-line rounded-lg border border-line">{children}</ul>;
}
function Row({ children }: { children: ReactNode }) {
  return <li className="flex flex-col gap-2 px-4 py-3">{children}</li>;
}
function When({ value }: { value: string }) {
  return <span className="font-mono text-caption text-ink-muted">{new Date(value).toLocaleString()}</span>;
}
const REGISTRATION_LABELS: Record<string, string> = {
  pending_approval: "Awaiting approval",
  registered: "Confirmed",
  waitlisted: "Waitlisted",
  rejected: "Not approved",
  cancelled: "Cancelled",
  attended: "Attended",
};

function RequestRows({ rows }: { rows: MachineServiceRequest[] }) {
  if (!rows.length) return <Empty />;
  return <Rows>{rows.map((item) => <Row key={`${item.title}-${item.status}`}>
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-semibold text-ink">{item.title}</span>
      <StatusChip size="sm" tone={statusTone(item.status)}>{statusLabel(item.status)}</StatusChip>
      {item.queue_position ? <span className="font-mono text-caption text-ink-muted">{`Queue ${item.queue_position}`}</span> : null}
    </div>
  </Row>)}</Rows>;
}

function BookingRows({ rows }: { rows: Booking[] }) {
  if (!rows.length) return <Empty />;
  return <Rows>{rows.map((item) => <Row key={`${item.space_name}-${item.starts_at}`}>
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-semibold text-ink">{item.space_name}</span>
      <StatusChip size="sm" tone={statusTone(item.status)}>{statusLabel(item.status)}</StatusChip>
    </div>
    <When value={item.starts_at} />
  </Row>)}</Rows>;
}

export function MemberActivityPanel({ activity, makerspaceId, makerspaceSlug }: { activity: MemberActivity; makerspaceId: number; makerspaceSlug: string }) {
  const printerRequests = (activity.machine_service_requests ?? []).filter((request) => request.machine_type === "3d_printer");
  const otherServiceRequests = (activity.machine_service_requests ?? []).filter((request) => request.machine_type !== "3d_printer");
  return <div className="flex flex-col gap-5">
    <Section title="My activity" description={activity.currently_checked_in ? "You are currently checked in." : "You are not currently checked in."}>
      {activity.accountability.waiver_acceptance_required ? <Callout tone="warning">Accept the current waiver before making facility requests.</Callout> : null}
    </Section>
    <Section title="Active hardware loans">{activity.active_hardware_loans.length ? <Rows>{activity.active_hardware_loans.map((loan) => <Row key={`${loan.label}-${loan.checked_out_at}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-ink">{loan.label}</span>
        {loan.overdue ? <StatusChip size="sm" tone="danger">Overdue</StatusChip> : null}
      </div>
      <span className="font-mono text-caption text-ink-muted">{loan.due_at ? `Due ${new Date(loan.due_at).toLocaleString()}` : "No due date"}</span>
    </Row>)}</Rows> : <Empty />}</Section>
    {activity.machine_service_requests ? <>
      <Section title="3D print requests"><RequestRows rows={printerRequests} /></Section>
      {otherServiceRequests.length ? <Section title="Machine-service requests"><RequestRows rows={otherServiceRequests} /></Section> : null}
    </> : null}
    {activity.bookings ? <Section title="Bookings">
      <div className="grid gap-5 sm:grid-cols-2">
        <div className="flex flex-col gap-2"><h3 className="text-label text-ink">Upcoming</h3><BookingRows rows={activity.bookings.upcoming} /></div>
        <div className="flex flex-col gap-2"><h3 className="text-label text-ink">Past</h3><BookingRows rows={activity.bookings.past} /></div>
      </div>
    </Section> : null}
    {activity.event_registrations ? <Section title="Event registrations">
      <div className="flex flex-col gap-4">
        <MemberCalendarActions makerspaceId={makerspaceId} makerspaceSlug={makerspaceSlug} />
        {activity.event_registrations.length ? <Rows>{activity.event_registrations.map((item) => <Row key={item.registration_id}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-ink">{item.event_title}</span>
            <StatusChip size="sm" tone={statusTone(item.status)}>{REGISTRATION_LABELS[item.status] ?? statusLabel(item.status)}</StatusChip>
            {item.waitlist_position ? <span className="font-mono text-caption text-ink-muted">{`Waitlist ${item.waitlist_position}`}</span> : null}
          </div>
          {item.status === "pending_approval" ? <p className="text-caption text-ink-muted">No payment until confirmed</p> : null}
          {item.checkin_token ? <CheckInQr makerspaceId={makerspaceId} registrationId={item.registration_id} /> : null}
          <MemberEventFeedback makerspaceId={makerspaceId} makerspaceSlug={makerspaceSlug} registrationId={item.registration_id} feedbackPath={item.feedback_path} certificate={item.certificate} />
        </Row>)}</Rows> : <Empty />}
      </div>
    </Section> : null}
    <Section title="Recent presence">{activity.recent_presence_sessions.length ? <Rows>{activity.recent_presence_sessions.map((item) => <Row key={item.started_at}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-caption text-ink-secondary">{new Date(item.started_at).toLocaleString()} to {new Date(item.expires_at).toLocaleString()}</span>
        {item.active ? <StatusChip size="sm" tone="success">Active</StatusChip> : null}
      </div>
    </Row>)}</Rows> : <Empty />}</Section>
  </div>;
}

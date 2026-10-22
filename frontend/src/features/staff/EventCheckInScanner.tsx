import { useState } from "react";
import { ScanLine } from "lucide-react";

import { Button, Callout, Card, useToast } from "../../components/ui";
import QrScanner from "../../components/ui/QrScanner";
import { StructuredApiError } from "../../lib/api";
import {
  useMarkEventAttended,
  useResolveEventCheckIn,
  type EventCheckInResolution,
} from "./eventsApi";
import { StatusWord } from "./panels/shared";

/** Staff-side QR check-in: scan, see who it is, then confirm.
 *
 * The two steps are deliberate and must not be collapsed into one. Resolving is read-only
 * and only reports a name; confirming is the mutation. Auto-confirming on scan would mean
 * a mis-aimed camera marks the wrong person present, and attendance is the record a paid
 * event is reconciled against.
 */
export default function EventCheckInScanner({
  makerspaceId,
  eventId,
  onClose,
}: {
  makerspaceId: number;
  eventId: number;
  onClose: () => void;
}) {
  const [scanning, setScanning] = useState(true);
  const [resolved, setResolved] = useState<EventCheckInResolution | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState<string | null>(null);
  const resolve = useResolveEventCheckIn(eventId);
  const attend = useMarkEventAttended(makerspaceId, eventId, "qr");
  const { showToast } = useToast();

  const handleScan = async (value: string) => {
    setScanning(false);
    setError(null);
    setConfirmed(null);
    setResolved(null);
    try {
      setResolved(await resolve.mutateAsync(value.trim()));
    } catch (cause) {
      // A 404 covers unknown, malformed and wrong-event tokens alike -- the endpoint
      // answers them identically on purpose -- so say the one thing that is true of all
      // three rather than surfacing a bare "not found".
      setError(
        cause instanceof StructuredApiError && cause.status === 404
          ? "That is not a check-in code for this event."
          : cause instanceof Error
            ? cause.message
            : "Could not read that code.",
      );
    }
  };

  const handleConfirm = async () => {
    if (!resolved) return;
    setError(null);
    try {
      await attend.mutateAsync(resolved.registration_id);
      setConfirmed(`${resolved.name} checked in.`);
      showToast(`${resolved.name} checked in`, { tone: "success" });
      setResolved(null);
    } catch (cause) {
      if (cause instanceof StructuredApiError && cause.status === 409) {
        // A conflict is NOT proof of a duplicate check-in. `mark_attended` returns 409 for
        // every non-registered status, so between resolving and confirming another staffer
        // could have cancelled the registration or the whole event. Claiming "already
        // checked in" would then be a false statement made to someone standing at a door,
        // so say what is actually known and force a re-scan rather than leaving a stale
        // resolution with Confirm still enabled.
        setResolved(null);
        showToast("Couldn't check in — scan again", { tone: "error" });
        setError(
          `${resolved.name} could not be checked in -- the registration changed. Scan again to see its current state.`,
        );
        return;
      }
      const message = cause instanceof Error ? cause.message : "Could not confirm attendance.";
      showToast(message, { tone: "error" });
      setError(message);
    }
  };

  // Gate on "registered" rather than excluding "waitlisted": `mark-attended` refuses every
  // other status, so an allow-list keeps a cancelled or already-attended code from offering
  // a button that can only fail. Excluding one status at a time is how the cancelled case
  // slipped through and reported a false "already checked in" to someone at the door.
  const confirmable = resolved?.status === "registered" && resolved.confirmable;
  const blockedReason = !resolved || confirmable
    ? null
    : resolved.status === "waitlisted"
      ? "Waitlisted registrations cannot be checked in until they are promoted."
      : resolved.status === "attended"
        ? "This registration is already checked in."
        : resolved.status === "cancelled"
          ? "This registration was cancelled, so it cannot be checked in."
          : resolved.event_status === "cancelled"
            ? "This event was cancelled, so attendance cannot be confirmed."
            : `Attendance cannot be confirmed while this event is ${resolved.event_status}.`;

  return (
    <Card as="section" padding="sm" className="grid gap-3" aria-labelledby="event-checkin-title">
      <div className="flex items-start justify-between gap-3">
        <h4 id="event-checkin-title" className="text-title text-ink">
          Check in by QR
        </h4>
        <Button size="sm" onClick={onClose}>
          Done
        </Button>
      </div>

      {resolved ? (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-label text-ink">{resolved.name}</span>
            <StatusWord status={resolved.status} />
          </div>
          {resolved.payment_status ? (
            // Information only. A payment problem must never stop the door: staff take
            // cash and reconcile later, and a card outage is not a reason to refuse
            // someone entry to an event they registered for.
            <p className="text-body-ui text-ink-muted">Payment: {resolved.payment_status}</p>
          ) : null}
          {resolved.host_waiver_state === "missing" ? (
            // Reported, not enforced. Someone standing at the door with nothing on file is
            // exactly who the host wants to hand a waiver to; refusing them entry is not
            // this screen's job, the same way payment state is shown without blocking.
            <Callout tone="warning">No host waiver on file — take one at the desk.</Callout>
          ) : null}
          {blockedReason ? <Callout tone="danger">{blockedReason}</Callout> : null}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="primary"
              disabled={!confirmable}
              loading={attend.isPending}
              loadingLabel="Checking in…"
              onClick={handleConfirm}
            >
              Confirm attendance
            </Button>
            <Button
              onClick={() => {
                setResolved(null);
                setScanning(true);
              }}
            >
              Scan another
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid gap-2">
          {confirmed ? <Callout tone="success" role="status">{confirmed}</Callout> : null}
          <Button
            className="w-fit"
            startIcon={<ScanLine />}
            disabled={resolve.isPending}
            onClick={() => {
              setError(null);
              setScanning(true);
            }}
          >
            {resolve.isPending ? "Reading…" : "Scan a code"}
          </Button>
        </div>
      )}

      {error ? <Callout tone="danger" role="alert">{error}</Callout> : null}

      {/* Unmounted rather than hidden, so the camera stops and keyboard users cannot tab
          into a scanner they cannot see. */}
      {scanning ? (
        <QrScanner onScan={handleScan} onClose={() => setScanning(false)} />
      ) : null}
    </Card>
  );
}

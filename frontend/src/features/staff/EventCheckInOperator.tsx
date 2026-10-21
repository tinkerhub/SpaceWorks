import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ScanLine } from "lucide-react";

import { Button } from "../../components/ui";
import EventCheckInScanner from "./EventCheckInScanner";
import { EventStationSettings } from "./EventStationSettings";
import { eventKeys } from "./eventsApi";
import { organizedEventKeys } from "./organizedEventsApi";
import { downloadStaffRoster, syncStaffRoster } from "./eventCheckInOfflineApi";
import { OfflineCheckInOperator } from "./OfflineCheckInOperator";
import { wipeOfflineState } from "./eventCheckInOfflineStore";

export function EventCheckInOperator({ makerspaceId, eventId, offlineEnabled }: {
  makerspaceId: number; eventId: number; offlineEnabled: boolean;
}) {
  const [scanning, setScanning] = useState(false);
  const queryClient = useQueryClient();
  useEffect(() => {
    if (!offlineEnabled) void wipeOfflineState(`staff:${eventId}`);
  }, [eventId, offlineEnabled]);
  const invalidate = async () => { await Promise.all([
    queryClient.invalidateQueries({ queryKey: eventKeys.registrations(eventId) }),
    queryClient.invalidateQueries({ queryKey: eventKeys.detail(eventId) }),
    queryClient.invalidateQueries({ queryKey: eventKeys.list(makerspaceId) }),
    queryClient.invalidateQueries({ queryKey: eventKeys.checkinHistory(eventId) }),
    queryClient.invalidateQueries({ queryKey: organizedEventKeys.all }),
  ]); };
  return (
    <section aria-labelledby="event-checkin-operator-title" className="grid gap-3">
      <div>
        <h4 id="event-checkin-operator-title" className="text-title text-ink">Attendance check-in</h4>
        <p className="mt-1 text-body-ui text-ink-muted">Scan a guest's code at the door, or keep a roster on this device for when the connection drops.</p>
      </div>
      {scanning ? (
        <EventCheckInScanner makerspaceId={makerspaceId} eventId={eventId} onClose={() => setScanning(false)} />
      ) : (
        <Button className="w-fit" startIcon={<ScanLine />} onClick={() => setScanning(true)}>Scan online</Button>
      )}
      {offlineEnabled ? (
        <>
          <OfflineCheckInOperator scope={`staff:${eventId}`} download={() => downloadStaffRoster(eventId)} synchronize={(roster, operations) => syncStaffRoster(eventId, roster, operations)} onSynchronized={invalidate} />
          <EventStationSettings eventId={eventId} />
        </>
      ) : null}
    </section>
  );
}

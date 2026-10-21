import { useState, type FormEvent } from "react";
import { useParams } from "react-router-dom";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, Card, ConfirmDialog, ErrorText, Field, Input, PageHeader, useToast } from "../../components/ui";
import { useModules } from "../../lib/modules";
import { useMakerspacePublic } from "../inventory/useMakerspacePublic";
import {
  downloadStationRoster,
  endStationSession,
  startStationSession,
  syncStationRoster,
} from "../staff/eventCheckInOfflineApi";
import { wipeOfflineState } from "../staff/eventCheckInOfflineStore";
import { OfflineCheckInOperator } from "../staff/OfflineCheckInOperator";

export function EventCheckInStationPage() {
  const { stationToken = "" } = useParams();
  const space = useMakerspacePublic();
  const { moduleEnabled } = useModules();
  const { showToast } = useToast();
  const scope = `station:${stationToken}`;
  const [pin, setPin] = useState("");
  const [active, setActive] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmExit, setConfirmExit] = useState(false);
  const [exiting, setExiting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault(); setPending(true); setError(null);
    try { await startStationSession(stationToken, pin); setPin(""); setActive(true); showToast("Station unlocked", { tone: "success" }); }
    catch { setError("The station credential is invalid or outside its event window."); showToast("Station stayed locked", { tone: "error" }); }
    finally { setPending(false); }
  }

  async function exit() {
    setExiting(true);
    try {
      await wipeOfflineState(scope);
      try { await endStationSession(stationToken); } catch { /* cookie still expires server-bound */ }
      setConfirmExit(false);
      setActive(false); setPin("");
      showToast("Station data wiped and locked", { tone: "success" });
    } catch {
      showToast("Couldn't wipe this station. Try again.", { tone: "error" });
    } finally {
      setExiting(false);
    }
  }

  return (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Event check-in" />}>
      <PublicContainer width={active ? "lg" : "sm"}>
        <PageHeader
          kicker="Door station"
          title="Event check-in station"
          description={active ? "Scan or search guests to check them in. Changes sync when the station is online." : "Enter the eight-digit PIN provided by the event organizer."}
          actions={active ? <Button variant="danger" onClick={() => setConfirmExit(true)}>Wipe data and lock station…</Button> : undefined}
        />
        {!active ? (
          <Card className="mt-8">
            <form className="grid gap-4" onSubmit={submit}>
              <Field label="Station PIN" helperText="Eight digits, from the organizer's check-in desk.">
                <Input
                  id="event-station-pin"
                  className="font-mono text-xl tracking-[0.3em]"
                  inputMode="numeric"
                  autoComplete="off"
                  pattern="[0-9]{8}"
                  maxLength={8}
                  required
                  value={pin}
                  onChange={(event) => setPin(event.target.value.replace(/\D/g, ""))}
                />
              </Field>
              <Button variant="primary" type="submit" disabled={pin.length !== 8} loading={pending} loadingLabel="Unlocking…">
                Unlock station
              </Button>
              {error ? <ErrorText message={error} /> : null}
            </form>
          </Card>
        ) : (
          <section className="mt-8" aria-label="Check-in">
            <OfflineCheckInOperator scope={scope} autoDownload download={() => downloadStationRoster(stationToken)} synchronize={(roster, operations) => syncStationRoster(stationToken, roster, operations)} />
          </section>
        )}
        <ConfirmDialog
          open={confirmExit}
          title="Wipe this station?"
          message="The guest list and any check-ins saved on this device are deleted, and the station locks. Check-ins that already synced stay on the server."
          confirmLabel="Wipe and lock"
          tone="danger"
          pending={exiting}
          onConfirm={() => { void exit(); }}
          onCancel={() => setConfirmExit(false)}
        />
      </PublicContainer>
    </PublicShell>
  );
}

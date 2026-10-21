import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, ConfirmDialog, ErrorText, PasswordInput, StatusChip, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { eventKeys } from "./eventsApi";
import { eventErrorText } from "./eventUi";

type StationStatus = {
  configured: boolean; enabled?: boolean; public_token?: string; version?: number;
  station_url?: string; rotated_at?: string;
};
type Rotation = { pin: string; public_token: string; version: number; station_url: string };

export function EventStationSettings({ eventId }: { eventId: number }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [pin, setPin] = useState<string | null>(null);
  const [password, setPassword] = useState("");
  const [confirmDisable, setConfirmDisable] = useState(false);
  useEffect(() => {
    if (!pin) return undefined;
    const timeout = window.setTimeout(() => setPin(null), 60_000);
    return () => window.clearTimeout(timeout);
  }, [pin]);
  const query = useQuery({
    queryKey: eventKeys.checkinStation(eventId),
    queryFn: () => staffRequest<StationStatus>(`/admin/events/${eventId}/check-in/station/`),
  });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: eventKeys.checkinStation(eventId) });
  const failed = (error: Error) => showToast(eventErrorText(error), { tone: "error" });
  const rotate = useMutation({
    mutationFn: () => staffRequest<Rotation>(`/admin/events/${eventId}/check-in/station/rotate/`, { method: "POST", body: "{}" }),
    onSuccess: async (data) => { setPin(data.pin); showToast("New station PIN ready", { tone: "success" }); await invalidate(); },
    onError: failed,
  });
  const reveal = useMutation({
    mutationFn: () => staffRequest<{ pin: string; version: number }>(`/admin/events/${eventId}/check-in/station/reveal/`, { method: "POST", body: JSON.stringify({ current_password: password }) }),
    onSuccess: (data) => { setPin(data.pin); setPassword(""); },
    onError: failed,
  });
  const disable = useMutation({
    mutationFn: () => staffRequest<StationStatus>(`/admin/events/${eventId}/check-in/station/`, { method: "DELETE" }),
    onSuccess: async () => { setPin(null); setConfirmDisable(false); showToast("Station turned off", { tone: "success" }); await invalidate(); },
    onError: (error) => { setConfirmDisable(false); failed(error); },
  });
  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(query.data?.station_url ?? "");
      showToast("Station link copied", { tone: "success" });
    } catch {
      showToast("Couldn't copy the link. Copy it from Open station instead.", { tone: "error" });
    }
  };
  const error = query.error || rotate.error || reveal.error || disable.error;
  const station = query.data;

  return <Card as="section" className="mt-3" aria-labelledby="station-settings-title">
    <CardHeader
      titleAs="h4"
      title={<span id="station-settings-title">PIN check-in station</span>}
      description="The PIN is scoped to this event and check-in window. Rotating it signs out every open station straight away."
      action={station?.configured ? <StatusChip tone={station.enabled ? "success" : "neutral"} size="sm">{station.enabled ? "On" : "Off"}</StatusChip> : null}
    />
    <div className="grid gap-4">
      {station?.configured ? (
        <div className="grid gap-2 text-body-ui text-ink-secondary">
          <p>Version {station.version}</p>
          {station.station_url ? (
            <div className="flex flex-wrap gap-2">
              <Button asChild size="sm"><a href={station.station_url} target="_blank" rel="noreferrer">Open station</a></Button>
              <Button size="sm" onClick={copyUrl}>Copy link</Button>
            </div>
          ) : null}
        </div>
      ) : <p className="text-body-ui text-ink-muted">No station PIN has been created.</p>}
      {pin ? (
        <p className="rounded-md bg-warning-bg px-4 py-3 text-warning-fg" aria-live="polite">
          <span className="block text-caption">PIN (hidden again in a minute)</span>
          <span className="font-mono text-xl font-semibold tracking-[0.2em]">{pin}</span>
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" size="sm" loading={rotate.isPending} onClick={() => rotate.mutate()}>{station?.configured ? "Rotate PIN" : "Create PIN"}</Button>
        {station?.enabled ? <Button variant="danger" size="sm" disabled={disable.isPending} onClick={() => setConfirmDisable(true)}>Turn off…</Button> : null}
      </div>
      {station?.enabled ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); reveal.mutate(); }}>
          <label className="sr-only" htmlFor="station-current-password">Current password</label>
          <div className="min-w-48 flex-1">
            <PasswordInput id="station-current-password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="Current password" />
          </div>
          <Button type="submit" disabled={!password} loading={reveal.isPending}>Reveal PIN</Button>
        </form>
      ) : null}
      <ErrorText message={error ? eventErrorText(error) : null} />
    </div>
    <ConfirmDialog
      open={confirmDisable}
      title="Turn off the check-in station?"
      message="Open station sessions stop working. You can create a new PIN later."
      confirmLabel="Turn off station"
      tone="danger"
      pending={disable.isPending}
      onCancel={() => setConfirmDisable(false)}
      onConfirm={() => disable.mutate()}
    />
  </Card>;
}

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Field, Input, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace } from "./panels/shared";
import { SettingSwitch } from "./settingsControls";

type Props = { makerspace: Makerspace; settings?: Makerspace; loading: boolean };

export function MakerspaceGeofenceSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const current = settings ?? makerspace;
  const [enabled, setEnabled] = useState(current.geofence_enabled ?? false);
  const [latitude, setLatitude] = useState(String(current.geofence_latitude ?? ""));
  const [longitude, setLongitude] = useState(String(current.geofence_longitude ?? ""));
  const [radius, setRadius] = useState(String(current.geofence_radius_m ?? 25));

  useEffect(() => {
    setEnabled(current.geofence_enabled ?? false);
    setLatitude(String(current.geofence_latitude ?? ""));
    setLongitude(String(current.geofence_longitude ?? ""));
    setRadius(String(current.geofence_radius_m ?? 25));
  }, [current.geofence_enabled, current.geofence_latitude, current.geofence_longitude, current.geofence_radius_m, makerspace.id]);

  const save = useMutation({
    mutationFn: () => staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, { method: "PATCH", body: JSON.stringify({
      geofence_enabled: enabled,
      geofence_latitude: latitude.trim() || null,
      geofence_longitude: longitude.trim() || null,
      geofence_radius_m: Number(radius),
    }) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["tenant-bootstrap"] });
      showToast("Geofence saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the geofence"), { tone: "error" }),
  });
  const changed = enabled !== (current.geofence_enabled ?? false) || latitude !== String(current.geofence_latitude ?? "") || longitude !== String(current.geofence_longitude ?? "") || radius !== String(current.geofence_radius_m ?? 25);

  // The switch is part of one saved draft (it is meaningless without coordinates), so it
  // changes local state and the Save button commits all four fields together.
  return (
    <Card as="section">
      <CardHeader title="Presence geofence" description="Require member location only when a presence session starts. Browsers require HTTPS or localhost for location access." />
      <form onSubmit={(event) => { event.preventDefault(); if (changed) save.mutate(); }}>
        <SettingsRow title="Geofence" description="Turn it on, set the centre and radius, then save.">
          <SettingSwitch
            label="Enable geofence"
            checked={enabled}
            disabled={loading || save.isPending}
            onCheckedChange={setEnabled}
          />
        </SettingsRow>
        <SettingsRow title="Area" description="The centre point in decimal degrees and how far from it counts as present.">
          <div className="grid min-w-0 gap-4">
            <div className="grid min-w-0 gap-4 sm:grid-cols-3">
              <Field label="Latitude">
                <Input inputMode="decimal" value={latitude} onChange={(event) => setLatitude(event.target.value)} placeholder="12.971599" />
              </Field>
              <Field label="Longitude">
                <Input inputMode="decimal" value={longitude} onChange={(event) => setLongitude(event.target.value)} placeholder="77.594566" />
              </Field>
              <Field label="Radius (metres)">
                <Input type="number" min="1" value={radius} onChange={(event) => setRadius(event.target.value)} />
              </Field>
            </div>
            {save.error ? <p className="text-caption text-danger-fg" role="alert">{save.error.message}</p> : null}
            <div>
              <Button type="submit" disabled={loading || !changed} loading={save.isPending} loadingLabel="Saving…">Save geofence</Button>
            </div>
          </div>
        </SettingsRow>
      </form>
    </Card>
  );
}

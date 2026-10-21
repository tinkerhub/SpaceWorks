import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";

import { Button, Card, CardHeader, Field, Input, SettingsRow, StatusChip, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText, type Makerspace } from "./panels/shared";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

export function MakerspaceLocationSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const currentLocation = settings?.location ?? makerspace.location ?? "";
  const currentMapUrl = settings?.map_url ?? makerspace.map_url ?? "";
  const [locationInput, setLocationInput] = useState(currentLocation);
  const [mapUrlInput, setMapUrlInput] = useState(currentMapUrl);

  useEffect(() => {
    setLocationInput(currentLocation);
    setMapUrlInput(currentMapUrl);
  }, [currentLocation, currentMapUrl, makerspace.id]);

  const updateLocation = useMutation({
    mutationFn: () =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          location: locationInput.trim(),
          map_url: mapUrlInput.trim(),
        }),
      }),
    onSuccess: (updated) => {
      setLocationInput(updated.location ?? "");
      setMapUrlInput(updated.map_url ?? "");
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["public-makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["tenant-bootstrap"] });
      showToast("Location saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the location"), { tone: "error" }),
  });

  const changed =
    locationInput.trim() !== currentLocation ||
    mapUrlInput.trim() !== currentMapUrl;
  const saveDisabled = loading || updateLocation.isPending || !changed;
  const savedMapUrl = currentMapUrl.trim();

  return (
    <Card as="section">
      <CardHeader
        title="Location"
        description="Public location label and optional Google Maps link shown on public pages."
        action={<StatusChip tone={savedMapUrl ? "success" : "neutral"} size="sm">{savedMapUrl ? "Maps link set" : "Text only"}</StatusChip>}
      />
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!saveDisabled) updateLocation.mutate();
        }}
      >
        <SettingsRow title="Where to find you" description="Both are optional. The link opens in the visitor's maps app.">
          <div className="grid min-w-0 gap-4">
            <Field label="Location label">
              <Input
                value={locationInput}
                onChange={(event) => setLocationInput(event.target.value)}
                placeholder="Main lab, downtown campus"
              />
            </Field>
            <Field label="Google Maps link" helperText="In Google Maps choose Share, copy the link and paste it here.">
              <Input
                value={mapUrlInput}
                onChange={(event) => setMapUrlInput(event.target.value)}
                placeholder="https://maps.app.goo.gl/…"
              />
            </Field>
            {updateLocation.error ? <p role="alert" className="text-caption text-danger-fg">{updateLocation.error.message}</p> : null}
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={saveDisabled} loading={updateLocation.isPending} loadingLabel="Saving…">
                Save location
              </Button>
              {savedMapUrl ? (
                <a
                  className="inline-flex min-h-9 items-center gap-1 px-1 text-sm font-semibold text-ink-secondary underline-offset-4 hover:text-ink hover:underline"
                  href={savedMapUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Open in Maps
                  <ExternalLink aria-hidden="true" className="size-3.5" />
                </a>
              ) : null}
            </div>
          </div>
        </SettingsRow>
      </form>
    </Card>
  );
}

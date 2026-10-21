import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Field, Input, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { ImageUploader } from "./ImageUploader";
import { errorText, type Makerspace } from "./panels/shared";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

export function MakerspaceBrandingSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const currentRegisteredName = settings?.name ?? makerspace.name;
  const [registeredNameInput, setRegisteredNameInput] = useState(currentRegisteredName);
  const [displayNameInput, setDisplayNameInput] = useState("");
  const currentDisplayName = settings?.branding_config?.display_name ?? "";

  useEffect(() => {
    setRegisteredNameInput(currentRegisteredName);
  }, [currentRegisteredName, makerspace.id]);

  useEffect(() => {
    setDisplayNameInput(currentDisplayName);
  }, [currentDisplayName, makerspace.id]);

  const refreshBranding = () => {
    queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
    queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
    queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
  };

  const updateRegisteredName = useMutation({
    mutationFn: (value: string) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name: value }),
      }),
    onSuccess: () => {
      refreshBranding();
      showToast("Registered name saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the registered name"), { tone: "error" }),
  });

  const updateDisplayName = useMutation({
    mutationFn: (value: string) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ public_display_name: value }),
      }),
    onSuccess: () => {
      refreshBranding();
      showToast("Display name saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the display name"), { tone: "error" }),
  });

  const trimmedRegisteredName = registeredNameInput.trim();
  const registeredNameChanged = trimmedRegisteredName !== currentRegisteredName.trim();
  const registeredNameSaveDisabled =
    loading || updateRegisteredName.isPending || !trimmedRegisteredName || !registeredNameChanged;
  const trimmedDisplayName = displayNameInput.trim();
  const displayNameChanged = trimmedDisplayName !== currentDisplayName.trim();
  const displayNameSaveDisabled = loading || updateDisplayName.isPending || !displayNameChanged;

  return (
    <Card as="section">
      <CardHeader
        title="Branding"
        description="Logo and cover image shown on this makerspace's public pages. When no logo is set, the makerspace name is shown as the wordmark."
      />
      <SettingsRow title="Images" description="A square-ish logo and a wide banner for the public pages.">
        <div className="grid min-w-0 gap-4 lg:grid-cols-2">
          <ImageUploader
            endpoint={`/admin/makerspace/${makerspace.id}/logo`}
            currentUrl={settings?.logo_url}
            label="Logo"
            fit="contain"
            onChanged={refreshBranding}
          />
          <ImageUploader
            endpoint={`/admin/makerspace/${makerspace.id}/cover`}
            currentUrl={settings?.cover_image_url}
            label="Cover image (wide banner)"
            shape="wide"
            onChanged={refreshBranding}
          />
        </div>
      </SettingsRow>
      <SettingsRow
        title="Registered name"
        description="The official name of this makerspace. Used across the app and as the public wordmark when no logo or public display name is set."
      >
        <form
          className="grid min-w-0 max-w-md gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!registeredNameSaveDisabled) updateRegisteredName.mutate(trimmedRegisteredName);
          }}
        >
          <Field label="Registered name" error={updateRegisteredName.error?.message}>
            <Input
              id="registered-name"
              value={registeredNameInput}
              disabled={loading}
              onChange={(event) => setRegisteredNameInput(event.target.value)}
            />
          </Field>
          <div>
            <Button type="submit" disabled={registeredNameSaveDisabled} loading={updateRegisteredName.isPending} loadingLabel="Saving…">
              Save registered name
            </Button>
          </div>
        </form>
      </SettingsRow>
      <SettingsRow title="Public display name" description="Shown on this makerspace's public pages instead of the registered name.">
        <form
          className="grid min-w-0 max-w-md gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!displayNameSaveDisabled) updateDisplayName.mutate(trimmedDisplayName);
          }}
        >
          <Field
            label="Public display name"
            optional
            error={updateDisplayName.error?.message}
            helperText={<>Leave blank to use the registered name (<span className="font-semibold text-ink">{makerspace.name}</span>).</>}
          >
            <Input
              id="public-display-name"
              placeholder={makerspace.name}
              value={displayNameInput}
              disabled={loading}
              onChange={(event) => setDisplayNameInput(event.target.value)}
            />
          </Field>
          <div>
            <Button type="submit" disabled={displayNameSaveDisabled} loading={updateDisplayName.isPending} loadingLabel="Saving…">
              Save display name
            </Button>
          </div>
        </form>
      </SettingsRow>
    </Card>
  );
}

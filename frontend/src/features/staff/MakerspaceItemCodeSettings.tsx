import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Field, Input, SettingsRow, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { CodeChip } from "./panels/CategoryGuide";
import { sampleItemCode } from "./panels/categoryStandard";
import { errorText, type Makerspace } from "./panels/shared";

type Props = {
  makerspace: Makerspace;
  settings?: Makerspace;
  loading: boolean;
};

/** The makerspace prefix that starts every item code (TC in TC-MCU-A). */
export function MakerspaceItemCodeSettings({ makerspace, settings, loading }: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const current = settings?.item_code_prefix ?? makerspace.item_code_prefix ?? "";
  const [prefix, setPrefix] = useState(current);

  useEffect(() => {
    setPrefix(current);
  }, [current, makerspace.id]);

  const save = useMutation({
    mutationFn: (value: string) =>
      staffRequest<Makerspace>(`/admin/makerspaces/${makerspace.id}`, {
        method: "PATCH",
        body: JSON.stringify({ item_code_prefix: value }),
      }),
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["makerspace-settings", makerspace.id] });
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["makerspaces"] });
      queryClient.invalidateQueries({ queryKey: ["inventory", makerspace.id] });
      showToast(`Item codes now start with ${saved.item_code_prefix}`, { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the item-code prefix"), { tone: "error" }),
  });

  const normalized = prefix.trim().toUpperCase();
  return (
    <Card as="section">
      <CardHeader title="Item codes" description="Every item is labelled prefix, category code, letter." />
      <SettingsRow
        title="Item code prefix"
        description="Unique across the platform. Leave it blank to use the default from your makerspace's name."
      >
        <form
          className="flex min-w-0 flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            save.mutate(normalized);
          }}
        >
          <Field label="Item code prefix" hideLabel error={save.error?.message} className="w-32">
            <Input
              className="font-mono uppercase"
              maxLength={6}
              value={prefix}
              placeholder={current || "TC"}
              disabled={loading || save.isPending}
              onChange={(event) => setPrefix(event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
            />
          </Field>
          <Button type="submit" disabled={loading || normalized === current} loading={save.isPending} loadingLabel="Saving…">
            Save prefix
          </Button>
          <p className="basis-full text-caption text-ink-muted" aria-live="polite">
            Items will read <CodeChip>{sampleItemCode(normalized || current)}</CodeChip>, <CodeChip>{sampleItemCode(normalized || current, "SNS")}</CodeChip>…
          </p>
        </form>
      </SettingsRow>
    </Card>
  );
}

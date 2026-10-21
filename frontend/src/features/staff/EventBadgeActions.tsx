import { useEffect, useMemo, useState } from "react";

import { Button, Callout, Card, CardHeader, CheckboxField, Dropdown, ErrorText, Field, Input, SwitchRow, useToast } from "../../components/ui";
import type { StaffEvent } from "./eventsApi";
import {
  type BadgeTemplate,
  useEventBadgeTemplate,
  useGenerateEventBadges,
  useSaveEventBadgeTemplate,
} from "./eventsBadgeApi";
import { eventErrorText } from "./eventUi";

const BASE_FIELDS = [
  ["name", "Name"], ["event_title", "Event"], ["date_time", "Date and time"],
  ["location", "Location"], ["registration_number", "Registration number"],
  ["email", "Email (personal)"], ["phone", "Phone (personal)"],
] as const;

function safeFilename(title: string) {
  return `${title.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-|-$/g, "") || "event"}-badges.pdf`;
}

export function EventBadgeActions({ event, makerspaceId, selectedIds, includeAttended, onIncludeAttended }: {
  event: StaffEvent;
  makerspaceId: number;
  selectedIds: number[];
  includeAttended: boolean;
  onIncludeAttended: (value: boolean) => void;
}) {
  const templateQuery = useEventBadgeTemplate(event.id);
  const save = useSaveEventBadgeTemplate(makerspaceId, event.id);
  const generate = useGenerateEventBadges(event.id);
  const [draft, setDraft] = useState<BadgeTemplate | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const { showToast } = useToast();
  const failed = (cause: unknown) => showToast(eventErrorText(cause), { tone: "error" });
  useEffect(() => { if (templateQuery.data) setDraft(templateQuery.data); }, [templateQuery.data]);
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, [previewUrl]);
  const options = useMemo(() => [
    ...BASE_FIELDS,
    ...(event.custom_form ?? []).map((question) => [`custom:${question.id}`, question.label] as const),
  ], [event.custom_form]);
  const error = templateQuery.error || save.error || generate.error;

  function toggleField(selector: string) {
    if (!draft) return;
    const fields = draft.fields.includes(selector)
      ? draft.fields.filter((item) => item !== selector)
      : [...draft.fields, selector];
    if (fields.length) setDraft({ ...draft, fields });
  }

  function savePdf(blob: Blob) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = safeFilename(event.title);
    link.click();
    URL.revokeObjectURL(url);
  }

  const payload = { registration_ids: selectedIds, include_attended: includeAttended };
  const generationDisabled = !selectedIds.length
    || !["published", "completed"].includes(event.status);

  return (
    <Card padding="sm" className="grid gap-3">
      <CardHeader
        titleAs="h4"
        className="mb-0"
        title="Attendee badges"
        description="Each QR contains that registration's existing check-in credential."
        action={(
          <>
            <Button size="sm" disabled={generationDisabled || generate.isPending} onClick={() => generate.mutate(payload, { onSuccess: (blob) => setPreviewUrl(URL.createObjectURL(blob)), onError: failed })}>Preview</Button>
            <Button size="sm" variant="primary" disabled={generationDisabled} loading={generate.isPending} loadingLabel="Generating…" onClick={() => generate.mutate(payload, { onSuccess: (blob) => { savePdf(blob); showToast("Badges downloaded", { tone: "success" }); }, onError: failed })}>
              {`Download PDF (${selectedIds.length})`}
            </Button>
          </>
        )}
      />
      <CheckboxField label="Allow attended registrations" checked={includeAttended} onCheckedChange={(checked) => onIncludeAttended(checked === true)} />
      {draft ? (
        <details className="group rounded-md border border-line">
          <summary className="cursor-pointer rounded-md px-3 py-2.5 text-label text-ink hover:bg-subtle">Badge template</summary>
          <div className="grid gap-4 border-t border-line p-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Paper">
                <Dropdown value={draft.paper_size} onChange={(e) => setDraft({ ...draft, paper_size: e.target.value as BadgeTemplate["paper_size"] })}>
                  <option value="A4">A4</option><option value="LETTER">Letter</option>
                </Dropdown>
              </Field>
              <Field label="Orientation">
                <Dropdown value={draft.orientation} onChange={(e) => setDraft({ ...draft, orientation: e.target.value as BadgeTemplate["orientation"] })}>
                  <option value="portrait">Portrait</option><option value="landscape">Landscape</option>
                </Dropdown>
              </Field>
              <Field label="Card width (mm)">
                <Input type="number" min="40" max="150" value={draft.card_width_mm} onChange={(e) => setDraft({ ...draft, card_width_mm: Number(e.target.value) })} />
              </Field>
              <Field label="Card height (mm)">
                <Input type="number" min="30" max="120" value={draft.card_height_mm} onChange={(e) => setDraft({ ...draft, card_height_mm: Number(e.target.value) })} />
              </Field>
            </div>
            <fieldset className="grid gap-2">
              <legend className="mb-2 text-label text-ink">Printed fields</legend>
              <div className="flex flex-wrap gap-x-5 gap-y-2">
                {options.map(([value, label]) => <CheckboxField key={value} label={label} checked={draft.fields.includes(value)} onCheckedChange={() => toggleField(value)} />)}
              </div>
            </fieldset>
            {draft.fields.some((field) => field === "email" || field === "phone") ? <Callout tone="warning">This template prints personal contact details. Keep generated PDFs private.</Callout> : null}
            <SwitchRow label="Print check-in QR" checked={draft.include_qr} onCheckedChange={(checked) => setDraft({ ...draft, include_qr: checked })} />
            <Button className="w-fit" loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate(draft, { onSuccess: () => showToast("Badge template saved", { tone: "success" }), onError: failed })}>Save template</Button>
          </div>
        </details>
      ) : null}
      {previewUrl ? (
        <div className="grid gap-2">
          <iframe className="h-96 w-full rounded-md border border-line" src={previewUrl} title="Attendee badge PDF preview" />
          <Button size="sm" className="w-fit" onClick={() => setPreviewUrl(null)}>Close preview</Button>
        </div>
      ) : null}
      {error ? <ErrorText message={eventErrorText(error)} /> : null}
    </Card>
  );
}

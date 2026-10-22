import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Card,
  Chip,
  ConfirmDialog,
  ErrorBlock,
  Field,
  Input,
  Skeleton,
  SwitchRow,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  useToast,
} from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { DefaultReference, PreviewPane, type TemplatePreview } from "./EmailTemplatePreview";
import { EmailTemplateTypeSelector, type MachineTypeOption } from "./EmailTemplateTypeSelector";
import { errorText } from "./shared";

export type TemplateSummary = {
  stream: string;
  audience: string;
  key: string;
  label: string;
  is_active: boolean;
  is_overridden: boolean;
  can_edit_space_default: boolean;
  overridable_types: MachineTypeOption[];
};

export type SelectedTemplate = Pick<TemplateSummary, "stream" | "audience" | "key"> & {
  machineType: MachineTypeOption | null;
  canEditSpaceDefault: boolean;
  overridableTypes: MachineTypeOption[];
};

type TemplateDetail = TemplateSummary & {
  description: string;
  fields: { name: string; description: string }[];
  subject: string;
  text_body: string;
  html_body: string;
  default_subject: string;
  default_text: string;
  default_html: string;
};

type Draft = { subject: string; text_body: string; html_body: string; is_active: boolean };

type FocusedField = "subject" | "text_body" | "html_body";

const emptyDraft: Draft = { subject: "", text_body: "", html_body: "", is_active: true };

export function EmailTemplateEditor({
  makerspaceId,
  selected,
  onSelectMachineType,
}: {
  makerspaceId: number;
  selected: SelectedTemplate;
  onSelectMachineType: (machineType: MachineTypeOption | null) => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [draft, setDraft] = useState<Draft>(emptyDraft);
  const [debouncedDraft, setDebouncedDraft] = useState<Draft>(emptyDraft);
  const [tab, setTab] = useState("edit");
  const [resetDialogOpen, setResetDialogOpen] = useState(false);
  const [lastFocused, setLastFocused] = useState<FocusedField>("text_body");
  const subjectRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const htmlRef = useRef<HTMLTextAreaElement>(null);
  const detailKey = [
    "email-template",
    makerspaceId,
    selected.stream,
    selected.audience,
    selected.key,
    selected.machineType?.id ?? "space",
  ];
  const path = templatePath(makerspaceId, selected);
  const typeOverride = Boolean(selected.machineType);

  const detail = useQuery({
    queryKey: detailKey,
    queryFn: () => staffRequest<TemplateDetail>(path),
  });

  useEffect(() => {
    if (detail.data) {
      const next = detailToDraft(detail.data);
      setDraft(next);
      setDebouncedDraft(next);
    }
  }, [detail.data]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedDraft(draft), 400);
    return () => window.clearTimeout(timer);
  }, [draft]);

  const preview = useQuery({
    queryKey: [
      "email-template-preview",
      makerspaceId,
      selected.stream,
      selected.audience,
      selected.key,
      selected.machineType?.id ?? "space",
      debouncedDraft,
    ],
    queryFn: () =>
      staffRequest<TemplatePreview>(`/admin/makerspace/${makerspaceId}/email-templates/preview`, {
        method: "POST",
        body: JSON.stringify({
          stream: selected.stream,
          audience: selected.audience,
          key: selected.key,
          ...(selected.machineType ? { machine_type_id: selected.machineType.id } : {}),
          subject: debouncedDraft.subject,
          text_body: debouncedDraft.text_body,
          html_body: debouncedDraft.html_body,
        }),
      }),
    enabled: Boolean(detail.data),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["email-templates", makerspaceId] });
    queryClient.invalidateQueries({ queryKey: detailKey });
  };
  const applyUpdated = (updated: TemplateDetail) => {
    const next = detailToDraft(updated);
    setDraft(next);
    setDebouncedDraft(next);
    invalidate();
  };
  const save = useMutation({
    mutationFn: () =>
      staffRequest<TemplateDetail>(path, { method: "PATCH", body: JSON.stringify(draft) }),
    onSuccess: (updated) => {
      applyUpdated(updated);
      showToast("Template saved", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the template"), { tone: "error" }),
  });
  const reset = useMutation({
    mutationFn: () => staffRequest<TemplateDetail>(`${path}/reset`, { method: "POST" }),
    onSuccess: (updated) => {
      applyUpdated(updated);
      setResetDialogOpen(false);
      showToast(typeOverride ? "Now using the space default" : "Template reset to the built-in default", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't reset the template"), { tone: "error" }),
  });

  const insertField = (name: string) => {
    const token = `{{ ${name} }}`;
    const target = { subject: subjectRef, text_body: textRef, html_body: htmlRef }[lastFocused].current;
    const start = target?.selectionStart ?? draft[lastFocused].length;
    const end = target?.selectionEnd ?? start;
    setDraft((current) => ({
      ...current,
      [lastFocused]: `${current[lastFocused].slice(0, start)}${token}${current[lastFocused].slice(end)}`,
    }));
    window.requestAnimationFrame(() => {
      target?.focus();
      target?.setSelectionRange(start + token.length, start + token.length);
    });
  };

  if (detail.isLoading) {
    return (
      <Card aria-busy="true" aria-label="Loading template">
        <Skeleton className="mb-3 h-6 w-1/2" />
        <Skeleton className="mb-6 h-4 w-3/4" />
        <Skeleton className="h-48 w-full" />
      </Card>
    );
  }
  if (detail.error) return <Card><ErrorBlock error={detail.error} /></Card>;
  if (!detail.data) return <Card><p className="text-body-ui text-ink-muted">Select a template to edit.</p></Card>;
  const data = detail.data;

  return (
    <Card as="section" aria-labelledby="email-template-title" className="grid gap-5">
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id="email-template-title" className="text-h4 text-ink">{data.label}</h2>
          <Chip tone={draft.is_active ? "success" : "neutral"} size="sm">{draft.is_active ? "Custom" : "Default"}</Chip>
          {data.is_overridden ? <Chip tone="warning" size="sm">Edited</Chip> : null}
        </div>
        {data.description ? <p className="max-w-3xl text-body-ui text-ink-muted">{data.description}</p> : null}
      </div>
      <EmailTemplateTypeSelector
        canEditSpaceDefault={selected.canEditSpaceDefault}
        types={selected.overridableTypes}
        selectedTypeId={selected.machineType?.id ?? null}
        onSelect={onSelectMachineType}
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label="Template views">
          <TabsTrigger value="edit">Edit</TabsTrigger>
          <TabsTrigger value="preview">Preview</TabsTrigger>
          <TabsTrigger value="default">{typeOverride ? "Space default" : "Built-in default"}</TabsTrigger>
        </TabsList>
        <TabsContent value="edit">
          <form className="grid gap-5" onSubmit={(event) => {
            event.preventDefault();
            save.mutate();
          }}>
            <SwitchRow
              label="Use custom template"
              description={`When off, the ${typeOverride ? "space" : "built-in"} default is sent and your text is kept. The email always sends.`}
              checked={draft.is_active}
              onCheckedChange={(is_active) => setDraft({ ...draft, is_active })}
            />
            <Field label="Subject">
              <Input ref={subjectRef} value={draft.subject} onFocus={() => setLastFocused("subject")} onChange={(event) => setDraft({ ...draft, subject: event.target.value })} />
            </Field>
            <MergeFields fields={data.fields} onInsert={insertField} />
            <Field label="Plain text body">
              <Textarea ref={textRef} className="min-h-48 font-mono text-sm" value={draft.text_body} onFocus={() => setLastFocused("text_body")} onChange={(event) => setDraft({ ...draft, text_body: event.target.value })} />
            </Field>
            <Field label="HTML body">
              <Textarea ref={htmlRef} className="min-h-56 font-mono text-sm" value={draft.html_body} onFocus={() => setLastFocused("html_body")} onChange={(event) => setDraft({ ...draft, html_body: event.target.value })} />
            </Field>
            <div className="flex flex-wrap items-center gap-2.5">
              <Button variant="primary" type="submit" loading={save.isPending} loadingLabel="Saving…">Save template</Button>
              <Button variant="danger" disabled={reset.isPending} onClick={() => setResetDialogOpen(true)}>
                {typeOverride ? "Fall back to space default…" : "Reset to built-in default…"}
              </Button>
            </div>
            <ErrorBlock error={save.error} />
            <ErrorBlock error={reset.error} />
          </form>
        </TabsContent>
        <TabsContent value="preview">
          <PreviewPane preview={preview.data} loading={preview.isFetching} error={preview.error} />
        </TabsContent>
        <TabsContent value="default">
          <DefaultReference subject={data.default_subject} text={data.default_text} typeOverride={typeOverride} />
        </TabsContent>
      </Tabs>
      <ConfirmDialog
        open={resetDialogOpen}
        title="Reset email template?"
        message={typeOverride ? "This machine type will send the space default again. Your custom text is discarded." : "This template will go back to the built-in default. Your custom text is discarded."}
        confirmLabel="Reset template"
        tone="danger"
        pending={reset.isPending}
        onConfirm={() => reset.mutate()}
        onCancel={() => setResetDialogOpen(false)}
      />
    </Card>
  );
}

function MergeFields({ fields, onInsert }: { fields: TemplateDetail["fields"]; onInsert: (name: string) => void }) {
  if (!fields.length) return null;
  return (
    <div role="group" aria-labelledby="merge-fields-label" className="grid gap-2">
      <div>
        <p id="merge-fields-label" className="text-label text-ink">Merge fields</p>
        <p className="text-caption text-ink-muted">Inserted where the cursor was last in the subject or a body.</p>
      </div>
      <div className="flex flex-wrap gap-2">
        {fields.map((field) => (
          <Button key={field.name} size="sm" variant="secondary" className="font-mono text-xs" title={field.description} onClick={() => onInsert(field.name)}>
            {field.name}
          </Button>
        ))}
      </div>
    </div>
  );
}

function templatePath(makerspaceId: number, selected: SelectedTemplate) {
  const base = `/admin/makerspace/${makerspaceId}/email-templates/${[selected.stream, selected.audience, selected.key].map(encodeURIComponent).join("/")}`;
  return selected.machineType ? `${base}/types/${selected.machineType.id}` : base;
}

function detailToDraft(detail: TemplateDetail): Draft {
  return {
    subject: detail.subject,
    text_body: detail.text_body,
    html_body: detail.html_body,
    is_active: detail.is_active,
  };
}

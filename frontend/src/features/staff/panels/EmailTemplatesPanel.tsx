import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Card, Chip, EmptyState, ErrorBlock, Skeleton } from "../../../components/ui";
import { cn } from "../../../lib/cn";
import { staffRequest } from "../../../lib/api";
import { EmailTemplateEditor, type SelectedTemplate, type TemplateSummary } from "./EmailTemplateEditor";
import { Panel, type Makerspace } from "./shared";

type GroupedTemplates = {
  stream: string;
  audiences: { audience: string; templates: TemplateSummary[] }[];
}[];

export function EmailTemplatesPanel({ makerspace }: { makerspace: Makerspace }) {
  const [selected, setSelected] = useState<SelectedTemplate | null>(null);
  const list = useQuery({
    queryKey: ["email-templates", makerspace.id],
    queryFn: () =>
      staffRequest<TemplateSummary[]>(`/admin/makerspace/${makerspace.id}/email-templates`),
  });
  const rows = useMemo(() => list.data ?? [], [list.data]);

  useEffect(() => {
    if (!rows.length) {
      setSelected(null);
      return;
    }
    const current = selected
      ? rows.find(
          (row) =>
            row.stream === selected.stream &&
            row.audience === selected.audience &&
            row.key === selected.key,
        )
      : undefined;
    if (!current || !selected || !selectedAxisIsVisible(current, selected)) {
      const first = rows[0];
      setSelected(selectTemplate(first));
      return;
    }
    const currentType = selected.machineType
      ? current.overridable_types.find((item) => item.id === selected.machineType?.id) ?? null
      : null;
    if (
      selected.canEditSpaceDefault !== current.can_edit_space_default ||
      selected.overridableTypes !== current.overridable_types ||
      selected.machineType !== currentType
    ) {
      setSelected({
        ...selected,
        machineType: currentType,
        canEditSpaceDefault: current.can_edit_space_default,
        overridableTypes: current.overridable_types,
      });
    }
  }, [rows, selected]);

  const grouped = useMemo(() => groupTemplates(rows), [rows]);

  return (
    <Panel
      title="Email templates"
      description="Change what requesters and staff receive. Untouched templates keep sending the built-in wording."
    >
      {list.isLoading ? (
        <div className="grid gap-4 xl:grid-cols-[18rem_minmax(0,1fr)]" aria-busy="true" aria-label="Loading email templates">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
      ) : list.error ? (
        <ErrorBlock error={list.error} />
      ) : !rows.length ? (
        <EmptyState title="No templates to edit" description="Turn on a module that sends email to customise its messages." />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[18rem_minmax(0,1fr)]">
          <Card padding="sm" as="section" aria-label="Templates" className="self-start">
            <TemplateList groups={grouped} selected={selected} onSelect={setSelected} />
          </Card>
          {selected ? (
            <EmailTemplateEditor
              makerspaceId={makerspace.id}
              selected={selected}
              onSelectMachineType={(machineType) => setSelected({ ...selected, machineType })}
            />
          ) : null}
        </div>
      )}
    </Panel>
  );
}

function TemplateList({
  groups,
  selected,
  onSelect,
}: {
  groups: GroupedTemplates;
  selected: SelectedTemplate | null;
  onSelect: (template: SelectedTemplate) => void;
}) {
  return (
    <div className="grid gap-4">
      {groups.map((stream) => (
        <div key={stream.stream} className="grid gap-2">
          <h3 className="px-2 text-label text-ink">{formatLabel(stream.stream)}</h3>
          {stream.audiences.map((audience) => (
            <div key={audience.audience} className="grid gap-0.5">
              <p className="px-2 text-caption text-ink-muted">{formatLabel(audience.audience)}</p>
              {audience.templates.map((template) => (
                <TemplateButton
                  key={`${template.stream}:${template.audience}:${template.key}`}
                  selected={isSelected(selected, template)}
                  template={template}
                  onSelect={onSelect}
                />
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function TemplateButton({
  selected,
  template,
  onSelect,
}: {
  selected: boolean;
  template: TemplateSummary;
  onSelect: (template: SelectedTemplate) => void;
}) {
  const edited = template.is_overridden || template.overridable_types.some((item) => item.is_overridden);
  return (
    <button
      aria-pressed={selected}
      className={cn(
        "flex min-h-10 min-w-0 items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-body-ui transition-colors duration-180 ease-standard focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
        selected ? "bg-emphasis font-semibold text-ink" : "text-ink-secondary hover:bg-subtle hover:text-ink",
      )}
      type="button"
      onClick={() => onSelect(selectTemplate(template))}
    >
      <span className="min-w-0 truncate">{template.label}</span>
      {edited ? <Chip tone="warning" size="sm">Edited</Chip> : null}
    </button>
  );
}

function groupTemplates(rows: TemplateSummary[]): GroupedTemplates {
  const streams = new Map<string, Map<string, TemplateSummary[]>>();
  rows.forEach((row) => {
    if (!streams.has(row.stream)) streams.set(row.stream, new Map());
    const audiences = streams.get(row.stream)!;
    if (!audiences.has(row.audience)) audiences.set(row.audience, []);
    audiences.get(row.audience)!.push(row);
  });
  return Array.from(streams, ([stream, audiences]) => ({
    stream,
    audiences: Array.from(audiences, ([audience, templates]) => ({ audience, templates })),
  }));
}

function isSelected(selected: SelectedTemplate | null, template: TemplateSummary) {
  return (
    selected?.stream === template.stream &&
    selected.audience === template.audience &&
    selected.key === template.key
  );
}

function selectTemplate(template: TemplateSummary): SelectedTemplate {
  return {
    stream: template.stream,
    audience: template.audience,
    key: template.key,
    machineType: template.can_edit_space_default ? null : template.overridable_types[0] ?? null,
    canEditSpaceDefault: template.can_edit_space_default,
    overridableTypes: template.overridable_types,
  };
}

function selectedAxisIsVisible(template: TemplateSummary, selected: SelectedTemplate) {
  if (selected.machineType === null) return template.can_edit_space_default;
  return template.overridable_types.some((item) => item.id === selected.machineType?.id);
}

function formatLabel(value: string) {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

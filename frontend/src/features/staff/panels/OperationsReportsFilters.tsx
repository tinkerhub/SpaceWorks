import { X } from "lucide-react";

import { Button, Card, Dropdown, ErrorText, Field, FilterChip, IconButton, Input, SegmentedControl, SwitchRow } from "../../../components/ui";
import type { ReportCatalogItem, ReportKey, SavedReportView } from "./operationsReportsConfig";

type Grain = "day" | "month";

const GRAINS = [
  { value: "day", label: "Day" },
  { value: "month", label: "Month" },
] as const;

/** Date range, report, grain and scope for the whole Reports page, plus saved views. */
export function OperationsReportsFilters(props: {
  startDate: string;
  endDate: string;
  onStartDate: (value: string) => void;
  onEndDate: (value: string) => void;
  selectedReport: ReportKey;
  onSelectReport: (value: ReportKey) => void;
  catalogEntries: ReportCatalogItem[];
  catalogLoading: boolean;
  catalogError: unknown;
  grain: string;
  onGrain: (value: string) => void;
  /** Superadmin on a multi-tenant site only: aggregate routes are refused when origin-locked. */
  showAllMakerspaces: boolean;
  allMakerspaces: boolean;
  onAllMakerspaces: (value: boolean) => void;
  presetName: string;
  onPresetName: (value: string) => void;
  presetPlaceholder: string;
  onSaveView: () => void;
  savedViews: SavedReportView[];
  isActiveView: (view: SavedReportView) => boolean;
  describeView: (view: SavedReportView) => string;
  onApplyView: (view: SavedReportView) => void;
  onRemoveView: (id: string) => void;
}) {
  const { catalogEntries, selectedReport } = props;
  return (
    <Card as="section" aria-label="Report filters">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)_auto] lg:items-start">
        <Field label="Start">
          <Input type="date" value={props.startDate} onChange={(event) => props.onStartDate(event.target.value)} />
        </Field>
        <Field label="End">
          <Input type="date" value={props.endDate} onChange={(event) => props.onEndDate(event.target.value)} />
        </Field>
        <Field label="Report">
          <Dropdown value={selectedReport} onChange={(event) => props.onSelectReport(event.target.value as ReportKey)}>
            {!catalogEntries.length ? <option value={selectedReport}>{props.catalogLoading ? "Loading reports…" : "No reports available"}</option> : null}
            {catalogEntries.map((report) => (
              <option key={report.key} value={report.key} disabled={report.available === false}>
                {report.title}
              </option>
            ))}
          </Dropdown>
        </Field>
        <div className="grid gap-1.5">
          <span className="text-label text-ink" aria-hidden="true">Grain</span>
          <SegmentedControl<Grain>
            ariaLabel="Grain"
            value={props.grain === "month" ? "month" : "day"}
            onValueChange={props.onGrain}
            options={GRAINS}
          />
        </div>
      </div>
      {props.showAllMakerspaces ? (
        <SwitchRow
          className="mt-5 border-t border-line pt-5"
          label="All makerspaces"
          description="Combine every makerspace into one report. Costs and totals stay per makerspace."
          checked={props.allMakerspaces}
          onCheckedChange={props.onAllMakerspaces}
        />
      ) : null}
      {props.catalogError ? (
        <div className="mt-4">
          <ErrorText message={props.catalogError instanceof Error ? props.catalogError.message : "We couldn't load the report list."} />
        </div>
      ) : null}
      <div className="mt-5 grid gap-4 border-t border-line pt-5">
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            props.onSaveView();
          }}
        >
          <Field label="View name" optional className="min-w-56 flex-1 sm:max-w-sm">
            <Input value={props.presetName} onChange={(event) => props.onPresetName(event.target.value)} placeholder={props.presetPlaceholder} />
          </Field>
          <Button type="submit" variant="secondary">Save view</Button>
        </form>
        {props.savedViews.length ? (
          <ul className="flex flex-wrap gap-2" aria-label="Saved views">
            {props.savedViews.map((view) => (
              <li key={view.id} className="flex min-w-0 max-w-full items-center gap-0.5">
                <FilterChip selected={props.isActiveView(view)} onClick={() => props.onApplyView(view)} title={props.describeView(view)} className="min-w-0 max-w-full">
                  <span className="truncate">{view.name}</span>
                  <span className="hidden truncate font-normal opacity-75 sm:inline">· {props.describeView(view)}</span>
                </FilterChip>
                <IconButton variant="quiet" size="sm" label={`Remove ${view.name}`} onClick={() => props.onRemoveView(view.id)}>
                  <X />
                </IconButton>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-caption text-ink-muted">Save a date range and report as a view to come back to it in one click.</p>
        )}
      </div>
    </Card>
  );
}

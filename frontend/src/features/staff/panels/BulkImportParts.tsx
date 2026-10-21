import type React from "react";

import { Button, Dialog, Dropdown, Field, Metric, ProgressBar, Table, TBody, TD, TH, THead, TR } from "../../../components/ui";
import { fields, labelFor, messageFor, type BulkImportJob, type ImportResult, type Mapping } from "./BulkImportHelpers";
import { StatusWord } from "./shared";

export function MappingDialog({ open, headers, mapping, setMapping, onClose, onPreview }: {
  open: boolean;
  headers: string[];
  mapping: Mapping;
  setMapping: React.Dispatch<React.SetStateAction<Mapping>>;
  onClose: () => void;
  onPreview: () => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Map columns"
      description="Match each inventory field to a column in your data. Unmatched fields are left out."
      size="lg"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={onPreview}>Preview</Button>
        </div>
      )}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map((field) => (
          <Field key={field} label={sentence(labelFor(field))}>
            <Dropdown value={mapping[field] ?? ""} onChange={(event) => setMapping((current) => ({ ...current, [field]: event.target.value || undefined }))}>
              <option value="">Do not import</option>
              {headers.map((header) => <option key={header} value={header}>{header}</option>)}
            </Dropdown>
          </Field>
        ))}
      </div>
    </Dialog>
  );
}

export function ImportProgress({ job, loading }: { job?: BulkImportJob; loading: boolean }) {
  const total = job?.total_rows ?? 0;
  const processed = job?.processed_rows ?? 0;
  const label = job ? `${sentence(job.status)} · ${processed} of ${total || "…"} rows` : loading ? "Processing…" : "Ready";
  return (
    <div className="grid gap-1.5" role="status" aria-live="polite">
      {total ? <ProgressBar value={processed} max={total} label="Import progress" /> : (
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-emphasis" aria-hidden="true">
          <div className="h-full w-1/3 animate-pulse rounded-full bg-accent-ink motion-reduce:animate-none" />
        </div>
      )}
      <p className="text-caption text-ink-muted">{label}</p>
    </div>
  );
}

export function ImportSummary({ result }: { result: ImportResult }) {
  const errorRows = new Map((result.errors ?? []).map((item) => [item.row, item.errors]));
  const warningRows = new Map((result.warnings ?? []).map((item) => [item.row, item.warnings]));
  const rows = result.rows ?? [];
  return (
    <section className="grid gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <Metric label="Create" value={result.created ?? result.summary?.create ?? 0} />
        <Metric label="Update" value={result.updated ?? result.summary?.update ?? 0} />
        <Metric label="Errors" value={result.summary?.errors ?? result.errors?.length ?? 0} danger={Boolean(result.summary?.errors ?? result.errors?.length)} />
        <Metric label="Warnings" value={result.summary?.warnings ?? result.warnings?.length ?? 0} />
        <Metric label="Rows" value={result.summary?.total ?? rows.length} />
      </div>
      {rows.length ? (
        <Table label="Import rows" className="min-w-[640px]">
          <THead><tr><TH>Row</TH><TH>Status</TH><TH>Name</TH><TH>Message</TH></tr></THead>
          <TBody>
            {rows.map((row) => {
              const errors = errorRows.get(row.row) ?? row.errors;
              const warnings = warningRows.get(row.row) ?? row.warnings;
              const message = errors ? messageFor(errors) : warnings ? messageFor(warnings) : "";
              return (
                <TR key={row.row}>
                  <TD className="tabular-nums">{row.row}</TD>
                  <TD>{errors ? <StatusWord status="error" tone="danger" /> : <StatusWord status={row.action ?? "ready"} tone={warnings ? "warning" : "success"} />}</TD>
                  <TD>{String(row.data?.name ?? "")}</TD>
                  <TD className={errors ? "text-danger-fg" : "text-warning-fg"}>{message}</TD>
                </TR>
              );
            })}
          </TBody>
        </Table>
      ) : null}
    </section>
  );
}

function sentence(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

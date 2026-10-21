import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, ErrorText, Field, Input, Textarea, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { invalidateInventoryViews } from "../queryInvalidation";
import {
  mapRow,
  parseDelimited,
  parseFileSample,
  suggestMapping,
  type BulkImportJob,
  type ImportResult,
  type Mapping,
  type RawRow,
} from "./BulkImportHelpers";
import { ImportProgress, ImportSummary, MappingDialog } from "./BulkImportParts";
import { errorText, Panel, type Makerspace } from "./shared";

export function BulkImport({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [rawJson, setRawJson] = useState('[{"name":"New Kit","total_quantity":"1","available_quantity":"1"}]');
  const [tableText, setTableText] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [sourceRows, setSourceRows] = useState<RawRow[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Mapping>({});
  const [mappingOpen, setMappingOpen] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const settledJobs = useRef(new Set<number>());

  // An applied import changes inventory (and may add categories), so every inventory view is stale.
  const refreshInventory = () => {
    invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
    queryClient.invalidateQueries({ queryKey: ["categories", makerspace.id] });
  };
  const syncMutation = useMutation({
    mutationFn: ({ apply, rows }: { apply: boolean; rows: RawRow[] }) =>
      staffRequest<ImportResult>(`/admin/makerspace/${makerspace.id}/inventory/import/${apply ? "apply" : "preview"}`, {
        method: "POST",
        body: JSON.stringify({ rows }),
      }),
    onMutate: () => setJobId(null),
    onSuccess: (_result, { apply }) => {
      if (apply) refreshInventory();
      showToast(apply ? "Import applied" : "Preview ready", { tone: "success" });
    },
    onError: (failure, { apply }) => showToast(errorText(failure, apply ? "Could not apply the import" : "Could not preview the import"), { tone: "error" }),
  });
  const jobMutation = useMutation({
    mutationFn: ({ file, mode }: { file: File; mode: "preview" | "apply" }) => {
      const body = new FormData();
      body.append("mode", mode);
      body.append("file", file);
      body.append("mapping", JSON.stringify(mapping));
      return staffRequest<BulkImportJob>(`/admin/makerspace/${makerspace.id}/inventory/import/jobs`, { method: "POST", body });
    },
    onSuccess: (job) => setJobId(job.id),
    onError: (failure) => showToast(errorText(failure, "Could not start the import"), { tone: "error" }),
  });
  const jobQuery = useQuery({
    queryKey: ["bulk-import-job", makerspace.id, jobId],
    queryFn: () => staffRequest<BulkImportJob>(`/admin/makerspace/${makerspace.id}/inventory/import/jobs/${jobId}`),
    enabled: jobId !== null,
    refetchInterval: (query) => (isRunning(query.state.data as BulkImportJob | undefined) ? 1000 : false),
  });
  const activeJob = jobQuery.data ?? jobMutation.data;
  const pending = syncMutation.isPending || jobMutation.isPending || isRunning(activeJob);
  const result = activeJob?.result && Object.keys(activeJob.result).length ? activeJob.result : syncMutation.data;

  // A file job finishes on the server; react once when it settles.
  useEffect(() => {
    if (!activeJob || isRunning(activeJob) || settledJobs.current.has(activeJob.id)) return;
    settledJobs.current.add(activeJob.id);
    if (activeJob.status === "failed") {
      showToast(activeJob.error || "Import job failed", { tone: "error" });
      return;
    }
    if (activeJob.mode === "apply") refreshInventory();
    showToast(activeJob.mode === "apply" ? "Import applied" : "Preview ready", { tone: "success" });
    // Keyed on the job only: the settled-id set makes this fire once per job.
  }, [activeJob]);

  const mappedRows = () => sourceRows.map((row) => mapRow(row, mapping));
  const submitRows = (apply: boolean, rows: RawRow[]) => {
    setError("");
    syncMutation.mutate({ apply, rows });
  };
  const startFileJob = (mode: "preview" | "apply") => {
    if (!selectedFile) {
      setError("Select a CSV, TSV, or XLSX file first.");
      return;
    }
    setError("");
    jobMutation.mutate({ file: selectedFile, mode });
  };
  // A chosen file is only SAMPLED for the mapping (first 256 KB of a CSV), so preview and
  // apply must run as a file job over the whole file; pasted rows go through the sync path.
  const run = (apply: boolean) => (selectedFile ? startFileJob(apply ? "apply" : "preview") : submitRows(apply, mappedRows()));
  const submitJson = (apply: boolean) => {
    try {
      const parsed = JSON.parse(rawJson);
      if (!Array.isArray(parsed) || parsed.some((row) => !row || typeof row !== "object" || Array.isArray(row))) {
        setError("Advanced JSON must be an array of row objects.");
        return;
      }
      submitRows(apply, parsed as RawRow[]);
    } catch {
      setError("Advanced JSON could not be parsed. Check commas, quotes, and brackets.");
    }
  };
  const loadRows = (rows: RawRow[]) => {
    if (!rows.length) {
      setError("No rows were found.");
      return;
    }
    const nextHeaders = Object.keys(rows[0]);
    setSourceRows(rows);
    setHeaders(nextHeaders);
    setMapping(suggestMapping(nextHeaders));
    setMappingOpen(true);
    setError("");
  };
  const hasData = Boolean(sourceRows.length || selectedFile);

  return (
    <Panel title="Bulk import" description="Add or update many inventory items at once from a spreadsheet or pasted table.">
      <div className="grid gap-5">
        <Card as="section">
          <CardHeader title="Choose your data" description="Upload a file or paste a table, then match its columns to inventory fields." />
          <div className="grid gap-4">
            <Field label="Upload CSV or XLSX" helperText={selectedFile ? `Selected: ${selectedFile.name}` : "CSV, TSV or XLSX. The first row holds the column names."}>
              <Input
                type="file"
                accept=".csv,.tsv,.xlsx"
                disabled={pending}
                className="file:mr-3 file:rounded-full file:border-0 file:bg-emphasis file:px-3 file:py-1 file:text-sm file:font-semibold file:text-ink"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) { setSelectedFile(file); parseFileSample(file).then(loadRows).catch((exc: Error) => setError(exc.message)); }
                }}
              />
            </Field>
            <Field label="Or paste a table">
              <Textarea rows={5} value={tableText} onChange={(event) => { setSelectedFile(null); setTableText(event.target.value); }} />
            </Field>
            <div className="flex flex-wrap gap-2.5">
              <Button disabled={pending || !tableText.trim()} onClick={() => { setSelectedFile(null); loadRows(parseDelimited(tableText)); }}>Map pasted table</Button>
              <Button disabled={pending || !sourceRows.length} onClick={() => setMappingOpen(true)}>Edit mapping</Button>
              <Button disabled={pending || !hasData} onClick={() => run(false)}>Preview</Button>
              <Button variant="primary" disabled={pending || !hasData} onClick={() => run(true)}>Apply import</Button>
            </div>
          </div>
        </Card>

        <details className="rounded-lg border border-line bg-canvas p-4" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
          <summary className="cursor-pointer text-label text-ink">Advanced JSON</summary>
          <div className="mt-4 grid gap-3">
            <Field label="JSON rows"><Textarea rows={6} className="font-mono text-sm" value={rawJson} onChange={(event) => setRawJson(event.target.value)} /></Field>
            <div className="flex flex-wrap gap-2.5">
              <Button disabled={pending} onClick={() => submitJson(false)}>Preview JSON</Button>
              <Button disabled={pending} onClick={() => submitJson(true)}>Apply JSON</Button>
            </div>
          </div>
        </details>

        {pending || activeJob ? <ImportProgress job={activeJob} loading={jobMutation.isPending || syncMutation.isPending} /> : null}
        <ErrorText message={error} />
        {syncMutation.error ? <ErrorText message={syncMutation.error.message} /> : null}
        {jobMutation.error ? <ErrorText message={jobMutation.error.message} /> : null}
        {jobQuery.error ? <ErrorText message={jobQuery.error.message} /> : null}
        {activeJob?.status === "failed" ? <ErrorText message={activeJob.error || "Import job failed."} /> : null}
        {result ? <ImportSummary result={result} /> : null}
      </div>
      <MappingDialog
        open={mappingOpen}
        headers={headers}
        mapping={mapping}
        setMapping={setMapping}
        onClose={() => setMappingOpen(false)}
        onPreview={() => { setMappingOpen(false); run(false); }}
      />
    </Panel>
  );
}

function isRunning(job?: BulkImportJob) {
  return job?.status === "pending" || job?.status === "running";
}

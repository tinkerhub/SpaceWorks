import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Callout,
  Card,
  CardHeader,
  EmptyState,
  ErrorBlock,
  SkeletonRows,
  StatusChip,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  useToast,
  type StatusTone,
} from "../../components/ui";
import {
  issueDataExportDownload,
  listDataExports,
  requestDataExport,
  type DataExportJob,
} from "./dataExportsApi";
import { errorText, Panel } from "./panels/shared";

export function DataExportsPanel({ makerspaceId }: { makerspaceId: number }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const queryKey = ["data-exports", makerspaceId];
  const jobs = useQuery({
    queryKey,
    queryFn: () => listDataExports(makerspaceId),
    refetchInterval: (query) =>
      (query.state.data as DataExportJob[] | undefined)?.some(isRunning) ? 1500 : false,
  });
  const requestExport = useMutation({
    mutationFn: () => requestDataExport(makerspaceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey });
      showToast("Export requested", { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't request the export"), { tone: "error" }),
  });
  const download = useMutation({
    mutationFn: (jobId: string) => issueDataExportDownload(makerspaceId, jobId),
    onSuccess: ({ url }) => {
      const link = document.createElement("a");
      link.href = url;
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
      showToast("Download starting", { tone: "info" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't prepare the download"), { tone: "error" }),
  });
  const rows = jobs.data ?? [];

  return (
    <Panel
      title="Makerspace data export"
      description="A readable, redacted copy of this makerspace's records."
      actions={(
        <Button
          variant="primary"
          disabled={rows.some(isRunning)}
          loading={requestExport.isPending}
          loadingLabel="Requesting…"
          onClick={() => requestExport.mutate()}
        >
          Request redacted export
        </Button>
      )}
    >
      <div className="grid gap-6">
        <Callout tone="warning" title="Read this disclosure before requesting an export">
          <p className="mt-1">
            The readable archive includes makerspace-owned records, but omits credentials,
            bearer tokens, platform configuration, selected JSON configuration, audit metadata,
            and free-text form answers. It is not a migration backup.
          </p>
          <p className="mt-2">
            <span className="font-semibold">It does contain member contact details.</span>{" "}
            Names, email addresses and phone numbers that members supplied on your records are
            included in readable form. &ldquo;Redacted&rdquo; refers to audit metadata and form
            answers, not to personal data — handle the file accordingly.
          </p>
          <p className="mt-2">
            The referenced-users file contains only id and username for people referenced by
            exported rows. This is a new intentional disclosure: the staff audit API exposes
            only a numeric actor id and the current console omits the actor. Usernames are
            identifying and can correlate a person across exports.
          </p>
        </Callout>
        <ErrorBlock error={requestExport.error} />

        <Card as="section">
          <CardHeader title="Exports" description="Each download link works once and expires." />
          <ErrorBlock error={jobs.error} className="mb-3" />
          {!jobs.isLoading && rows.length === 0 ? (
            <EmptyState title="No exports have been requested" description="Request a redacted export above; it appears here while it builds." />
          ) : (
            <Table label="Data exports">
              <THead><TR><TH>Export</TH><TH>Requested</TH><TH>Rows</TH><TH>Status</TH><TH><span className="sr-only">Actions</span></TH></TR></THead>
              <TBody>
                {jobs.isLoading ? <SkeletonRows rows={2} cols={5} /> : null}
                {rows.map((job) => (
                  <ExportJobRow
                    key={job.id}
                    job={job}
                    downloading={download.isPending && download.variables === job.id}
                    onDownload={() => download.mutate(job.id)}
                  />
                ))}
              </TBody>
            </Table>
          )}
          <ErrorBlock error={download.error} className="mt-3" />
        </Card>
      </div>
    </Panel>
  );
}

function ExportJobRow({ job, downloading, onDownload }: {
  job: DataExportJob;
  downloading: boolean;
  onDownload: () => void;
}) {
  const total = job.manifest.total_rows;
  return (
    <TR>
      <TD>
        <span className="font-semibold">Redacted export</span>
        {job.status === "failed" ? (
          <span className="mt-0.5 block text-caption text-danger-fg" role="alert">{job.failure_detail || "The export failed."}</span>
        ) : null}
      </TD>
      <TD className="whitespace-nowrap text-ink-secondary">
        {new Date(job.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
      </TD>
      <TD className="text-ink-secondary">{typeof total === "number" ? total : "—"}</TD>
      <TD><StatusChip tone={statusTone(job)} size="sm">{statusLabel(job)}</StatusChip></TD>
      <TD className="text-right">
        {job.status === "available" ? (
          <Button size="sm" variant="secondary" loading={downloading} loadingLabel="Preparing link…" onClick={onDownload}>
            Download archive
          </Button>
        ) : null}
      </TD>
    </TR>
  );
}

function isRunning(job: DataExportJob) {
  return job.status === "pending" || job.status === "running";
}

function statusTone(job: DataExportJob): StatusTone {
  if (job.status === "available") return "success";
  if (job.status === "failed") return "danger";
  return "info";
}

function statusLabel(job: DataExportJob) {
  if (job.status === "available") return "Ready to download";
  if (job.status === "failed") return job.failure_code === "deadline_exceeded" ? "Deadline exceeded" : "Failed";
  return job.status === "pending" ? "Queued" : "Building snapshot";
}

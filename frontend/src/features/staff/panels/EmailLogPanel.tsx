import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Dropdown,
  EmptyState,
  ErrorBlock,
  Field,
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
} from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { absoluteTime, formatLogTime, LogPager } from "./StaffLogParts";
import { errorText, Panel, useStaffGet, type Makerspace } from "./shared";

type EmailLogStatus = "" | "sent" | "failed" | "pending" | "sending";

type EmailLogEntry = {
  id: number;
  to_email: string;
  subject: string;
  stream: string;
  event: string;
  audience: string;
  status: Exclude<EmailLogStatus, "">;
  error: string;
  attempts: number;
  created_at: string;
  sent_at: string | null;
};

type EmailLogResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: EmailLogEntry[];
};

const STATUS: Record<EmailLogEntry["status"], { label: string; tone: StatusTone }> = {
  sent: { label: "Sent", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  pending: { label: "Pending", tone: "warning" },
  sending: { label: "Sending", tone: "info" },
};

export function EmailLogPanel({ makerspace }: { makerspace: Makerspace }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [status, setStatus] = useState<EmailLogStatus>("");
  const [page, setPage] = useState(1);
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  params.set("page", String(page));
  const query = params.toString();
  const logs = useStaffGet<EmailLogResponse>(
    ["email-logs", makerspace.id, query],
    `/admin/makerspace/${makerspace.id}/email-logs?${query}`,
  );
  const retry = useMutation({
    mutationFn: (id: number) =>
      staffRequest<EmailLogEntry>(`/admin/makerspace/${makerspace.id}/email-logs/${id}/retry`, {
        method: "POST",
      }),
    onSuccess: () => {
      showToast("Email queued to send again", { tone: "success" });
      queryClient.invalidateQueries({ queryKey: ["email-logs", makerspace.id] });
    },
    onError: (error) => showToast(errorText(error, "Couldn't retry this email"), { tone: "error" }),
  });

  const updateStatus = (value: EmailLogStatus) => {
    setStatus(value);
    setPage(1);
  };
  const rows = logs.data?.results ?? [];

  return (
    <Panel title="Email log" description="Every email this makerspace sent or tried to send. Retry a failed one once the problem is fixed.">
      <div className="grid gap-4">
        <div className="w-full sm:w-56">
          <Field label="Status">
            <Dropdown
              aria-label="Email log status"
              value={status}
              onChange={(event) => updateStatus(event.target.value as EmailLogStatus)}
            >
              <option value="">All</option>
              <option value="sent">Sent</option>
              <option value="failed">Failed</option>
              <option value="pending">Pending</option>
              <option value="sending">Sending</option>
            </Dropdown>
          </Field>
        </div>
        <ErrorBlock error={logs.error} />
        <ErrorBlock error={retry.error} />
        {!logs.isLoading && logs.data && rows.length === 0 ? (
          <EmptyState
            title={status ? "No emails with this status" : "No emails yet"}
            description={status ? "Pick All to see every email." : "Emails appear here as soon as the makerspace sends one."}
          />
        ) : (
          <Table label="Email log entries">
            <THead>
              <tr>
                <TH>When</TH>
                <TH>To</TH>
                <TH>Event</TH>
                <TH>Status</TH>
                <TH>Error</TH>
                <TH><span className="sr-only">Action</span></TH>
              </tr>
            </THead>
            <TBody>
              {logs.isLoading ? <SkeletonRows rows={6} cols={6} /> : null}
              {rows.map((log) => (
                <TR key={log.id} className="align-top">
                  <TD className="whitespace-nowrap text-ink-secondary">
                    <time dateTime={log.created_at} title={absoluteTime(log.created_at)}>{formatLogTime(log.created_at)}</time>
                  </TD>
                  <TD className="max-w-56 break-words">{log.to_email}</TD>
                  <TD>
                    <span className="block font-semibold">{humanize(log.event || "email")}</span>
                    <span className="block text-caption text-ink-muted">{humanize(log.stream || "general")}</span>
                  </TD>
                  <TD>
                    <StatusChip tone={STATUS[log.status]?.tone ?? "neutral"} size="sm">
                      {STATUS[log.status]?.label ?? log.status}
                    </StatusChip>
                  </TD>
                  <TD className="max-w-72 break-words text-caption text-ink-muted">
                    {log.status === "failed" ? truncate(log.error) : ""}
                  </TD>
                  <TD className="whitespace-nowrap text-right">
                    {log.status === "failed" || log.status === "sending" ? (
                      <Button size="sm" variant="secondary" disabled={retry.isPending} onClick={() => retry.mutate(log.id)}>
                        Retry
                      </Button>
                    ) : null}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
        <LogPager
          page={page}
          count={logs.data?.count ?? 0}
          hasPrevious={Boolean(logs.data?.previous)}
          hasNext={Boolean(logs.data?.next)}
          onPage={setPage}
          disabled={logs.isFetching}
        />
      </div>
    </Panel>
  );
}

function humanize(value: string) {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function truncate(value: string) {
  return value.length > 140 ? `${value.slice(0, 137)}…` : value;
}

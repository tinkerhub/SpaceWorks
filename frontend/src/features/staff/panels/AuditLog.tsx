import { useState } from "react";

import { EmptyState, ErrorBlock, Field, Input, SearchInput, SkeletonRows, Table, TBody, TD, TH, THead, TR } from "../../../components/ui";
import { absoluteTime, formatLogTime, LogPager } from "./StaffLogParts";
import { Panel, useStaffGet } from "./shared";

type AuditLogEntry = {
  id: number;
  actor?: number | null;
  action: string;
  target_type: string;
  target_id: string | number | null;
  created_at: string;
};

type AuditLogResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: AuditLogEntry[];
};

export function AuditLog() {
  const [targetType, setTargetType] = useState("");
  const [targetId, setTargetId] = useState("");
  const [page, setPage] = useState(1);
  const params = new URLSearchParams();
  if (targetType) params.set("target_type", targetType);
  if (targetId) params.set("target_id", targetId);
  params.set("page", String(page));
  const query = params.toString();
  const logs = useStaffGet<AuditLogResponse>(
    ["audit", query],
    `/admin/audit-logs?${query}`,
  );

  const updateTargetType = (value: string) => {
    setTargetType(value);
    setPage(1);
  };
  const updateTargetId = (value: string) => {
    setTargetId(value);
    setPage(1);
  };
  const rows = logs.data?.results ?? [];
  const filtered = Boolean(targetType || targetId);

  return (
    <Panel title="Audit log" description="Every state change in this makerspace, newest first. Entries can't be edited or removed.">
      <div className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Field label="Target type">
            <SearchInput
              placeholder="e.g. inventory.inventoryproduct"
              value={targetType}
              onChange={(event) => updateTargetType(event.target.value)}
              onClear={() => updateTargetType("")}
              clearLabel="Clear target type"
            />
          </Field>
          <Field label="Target ID" optional>
            <Input className="font-mono" value={targetId} onChange={(event) => updateTargetId(event.target.value)} />
          </Field>
        </div>
        <ErrorBlock error={logs.error} />
        {!logs.isLoading && logs.data && rows.length === 0 ? (
          <EmptyState
            title={filtered ? "No entries match" : "No audit entries yet"}
            description={filtered ? "Try a broader target type or clear the target ID." : "Actions staff take will be recorded here."}
          />
        ) : (
          <Table label="Audit log entries">
            <THead>
              <tr>
                <TH>When</TH>
                <TH>Action</TH>
                <TH>Target</TH>
                <TH>Actor</TH>
              </tr>
            </THead>
            <TBody>
              {logs.isLoading ? <SkeletonRows rows={6} cols={4} /> : null}
              {rows.map((log) => (
                <TR key={log.id}>
                  <TD className="whitespace-nowrap text-ink-secondary">
                    <time dateTime={log.created_at} title={absoluteTime(log.created_at)}>{formatLogTime(log.created_at)}</time>
                  </TD>
                  <TD className="font-semibold">{log.action}</TD>
                  <TD className="text-ink-secondary">
                    <span>{log.target_type}</span>
                    {log.target_id !== null && log.target_id !== "" ? (
                      <span className="ml-1.5 font-mono text-caption text-ink-muted">#{log.target_id}</span>
                    ) : null}
                  </TD>
                  <TD className="whitespace-nowrap text-ink-secondary">
                    {log.actor ? <span className="font-mono text-caption">User #{log.actor}</span> : "System"}
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

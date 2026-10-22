import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, EmptyState, Dropdown, Field, SectionHeading, Skeleton, StatusChip, Textarea, type StatusTone } from "../../../../components/ui";
import { addMachineErrorLog, collectionResults, getMachineErrorLogs, machineKeys } from "../../machinesApi";
import { humanize, useNotify, When } from "./machineUi";

// Mirrors backend `MachineErrorLog.Severity`; the server refuses anything else, which the old
// free-text field let operators type and then failed on submit.
const SEVERITIES: { value: string; tone: StatusTone }[] = [
  { value: "info", tone: "info" },
  { value: "warning", tone: "warning" },
  { value: "error", tone: "danger" },
  { value: "critical", tone: "danger" },
];

export function ErrorsTab({ machineId, canOperate, retired = false }: { machineId: number; canOperate: boolean; retired?: boolean }) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [severity, setSeverity] = useState("error");
  const [message, setMessage] = useState("");
  const logs = useQuery({
    queryKey: machineKeys.errors(machineId),
    queryFn: () => getMachineErrorLogs(machineId),
  });
  const items = collectionResults(logs.data);
  const add = useMutation({
    mutationFn: () => addMachineErrorLog(machineId, {
      severity: severity.trim(),
      message: message.trim(),
    }),
    onSuccess: async () => {
      notify.success("Error logged");
      setMessage("");
      await queryClient.invalidateQueries({ queryKey: machineKeys.errors(machineId) });
    },
    onError: (error) => notify.failure("Couldn't log the error.", error),
  });

  return (
    <section className="grid gap-4">
      <SectionHeading as="h3" title="Error logs" description="Faults and warnings, newest first." />
      {canOperate && !retired ? (
        <form className="grid gap-3 rounded-lg border border-line bg-subtle p-4" onSubmit={(event) => { event.preventDefault(); add.mutate(); }}>
          <Field label="Severity" className="sm:max-w-56">
            <Dropdown value={severity} onChange={(event) => setSeverity(event.target.value)} required>
              {SEVERITIES.map((entry) => <option key={entry.value} value={entry.value}>{humanize(entry.value)}</option>)}
            </Dropdown>
          </Field>
          <Field label="Message">
            <Textarea rows={3} value={message} onChange={(event) => setMessage(event.target.value)} required />
          </Field>
          {add.error instanceof Error ? <p className="text-caption text-danger-fg">{add.error.message}</p> : null}
          <Button className="justify-self-start" variant="primary" type="submit" loading={add.isPending} loadingLabel="Logging…" disabled={!severity.trim() || !message.trim()}>
            Add error log
          </Button>
        </form>
      ) : null}
      {canOperate && retired ? <p className="text-caption text-ink-muted">Retired machines don't take new error logs.</p> : null}
      {logs.isLoading ? (
        <div className="grid gap-2" role="status" aria-label="Loading error logs">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : null}
      {logs.error instanceof Error ? <EmptyState tone="error" title="Couldn't load error logs" description={logs.error.message} /> : null}
      {!logs.isLoading && !logs.error && !items.length ? (
        <EmptyState title="No errors logged" description="Nothing has gone wrong with this machine yet." />
      ) : null}
      {items.length ? (
        <ul className="grid gap-2">
          {items.map((entry) => (
            <li key={entry.id} className="grid gap-1.5 rounded-lg border border-line bg-canvas p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <StatusChip size="sm" tone={SEVERITIES.find((item) => item.value === entry.severity)?.tone ?? "neutral"}>
                  {humanize(entry.severity)}
                </StatusChip>
                <span className="text-caption text-ink-muted"><When value={entry.created_at} /></span>
              </div>
              <p className="whitespace-pre-wrap break-words text-body-ui text-ink">{entry.message}</p>
              {entry.logged_by_username ? <p className="text-caption text-ink-muted">Logged by {entry.logged_by_username}</p> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

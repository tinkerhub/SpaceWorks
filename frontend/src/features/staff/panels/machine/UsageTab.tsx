import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, EmptyState, Field, Input, SectionHeading, SkeletonRows, Table, TBody, TD, TH, THead, TR } from "../../../../components/ui";
import { addMachineUsage, collectionResults, getMachineUsage, machineKeys } from "../../machinesApi";
import { humanize, useNotify, When } from "./machineUi";

export function UsageTab({ machineId, makerspaceId, canOperate, retired = false }: {
  machineId: number;
  makerspaceId: number;
  canOperate: boolean;
  retired?: boolean;
}) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [hours, setHours] = useState("");
  const [note, setNote] = useState("");
  const usage = useQuery({
    queryKey: machineKeys.usage(machineId),
    queryFn: () => getMachineUsage(machineId),
  });
  const items = collectionResults(usage.data);
  const add = useMutation({
    mutationFn: () => addMachineUsage(machineId, { hours, note: note.trim() }),
    onSuccess: async () => {
      notify.success(`${hours} h logged`);
      setHours("");
      setNote("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: machineKeys.usage(machineId) }),
        queryClient.invalidateQueries({ queryKey: machineKeys.detail(machineId) }),
        queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
      ]);
    },
    onError: (error) => notify.failure("Couldn't log usage.", error),
  });

  return (
    <section className="grid gap-4">
      <SectionHeading as="h3" title="Usage" description="Hours logged by hand, including prints logged outside the queue." />
      {canOperate && !retired ? (
        <form className="grid gap-3 rounded-lg border border-line bg-subtle p-4 sm:grid-cols-[8rem_minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(event) => { event.preventDefault(); add.mutate(); }}>
          <Field label="Hours">
            <Input type="number" min="0.01" step="0.01" inputMode="decimal" value={hours} onChange={(event) => setHours(event.target.value)} required />
          </Field>
          <Field label="Note">
            <Input maxLength={255} value={note} onChange={(event) => setNote(event.target.value)} />
          </Field>
          <Button variant="primary" type="submit" loading={add.isPending} loadingLabel="Logging…" disabled={!hours}>Add usage</Button>
          {add.error instanceof Error ? <p className="text-caption text-danger-fg sm:col-span-full">{add.error.message}</p> : null}
        </form>
      ) : null}
      {canOperate && retired ? <p className="text-caption text-ink-muted">Retired machines don't take new usage. Reactivate it on the Overview tab first.</p> : null}
      {usage.error instanceof Error ? <EmptyState tone="error" title="Couldn't load usage" description={usage.error.message} /> : null}
      {!usage.isLoading && !usage.error && !items.length ? (
        <EmptyState title="No usage logged yet" description={canOperate ? "Log the first hours above." : "Usage appears here once someone logs it."} />
      ) : null}
      {usage.isLoading || items.length ? (
        <Table label="Usage history">
          <THead>
            <tr><TH>Hours</TH><TH>When</TH><TH>Source</TH><TH>Note</TH></tr>
          </THead>
          <TBody>
            {usage.isLoading ? <SkeletonRows rows={3} cols={4} /> : null}
            {items.map((entry) => (
              <TR key={entry.id}>
                <TD className="whitespace-nowrap font-semibold tabular-nums">{entry.hours} h</TD>
                <TD className="whitespace-nowrap text-ink-secondary"><When value={entry.created_at} /></TD>
                <TD className="text-ink-secondary">
                  <span>{humanize(entry.source)}</span>
                  {entry.logged_by_username ? <span className="block text-caption text-ink-muted">{entry.logged_by_username}</span> : null}
                </TD>
                <TD className="min-w-40 break-words text-ink-secondary">{entry.note || "—"}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
      ) : null}
    </section>
  );
}

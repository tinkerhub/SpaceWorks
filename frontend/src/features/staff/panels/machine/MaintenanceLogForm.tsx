import { useState } from "react";

import { Button, CheckboxField, Field, Input, Textarea } from "../../../../components/ui";
import { useLogMaintenance, type MaintenanceSchedule } from "./maintenanceApi";
import { useMakerspaceCurrency, withCurrency } from "../../paymentsApi";
import { formatDay, useNotify } from "./machineUi";

/**
 * One form for both ways maintenance gets logged: ad hoc, or completing a schedule (which
 * pre-fills the summary and sends `schedule_id`, so the backend rolls that schedule forward).
 */
export function MaintenanceLogForm({ makerspaceId, machineId, schedule, onCancel, onLogged }: {
  makerspaceId: number;
  machineId: number;
  schedule?: MaintenanceSchedule;
  onCancel?: () => void;
  onLogged?: () => void;
}) {
  const notify = useNotify();
  const [summary, setSummary] = useState(schedule?.description ?? "");
  const [performedAt, setPerformedAt] = useState("");
  const [cost, setCost] = useState("");
  const [partsNote, setPartsNote] = useState("");
  const [setIdle, setSetIdle] = useState(false);
  const log = useLogMaintenance(makerspaceId, machineId);
  const currency = useMakerspaceCurrency(makerspaceId);
  const headingId = schedule ? `complete-maintenance-${schedule.id}` : "log-maintenance-title";

  const reset = () => {
    setSummary("");
    setPerformedAt("");
    setCost("");
    setPartsNote("");
    setSetIdle(false);
  };

  return (
    <section aria-labelledby={headingId} className="grid gap-3 rounded-lg border border-line bg-subtle p-4">
      <div>
        <h3 id={headingId} className="text-title text-ink">{schedule ? "Complete scheduled maintenance" : "Log maintenance"}</h3>
        {schedule ? (
          <p className="mt-0.5 text-caption text-ink-muted">
            {schedule.description} · due {formatDay(schedule.next_due)}. Completing it moves the next due date on by {schedule.interval_days} days.
          </p>
        ) : null}
      </div>
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          log.mutate({
            summary: summary.trim(),
            performed_at: performedAt ? new Date(performedAt).toISOString() : undefined,
            cost: cost.trim() || null,
            parts_note: partsNote.trim(),
            set_idle: setIdle,
            ...(schedule ? { schedule_id: schedule.id } : {}),
          }, {
            onSuccess: () => {
              notify.success(schedule ? "Scheduled maintenance completed" : "Maintenance logged");
              if (!schedule) reset();
              onLogged?.();
            },
            onError: (error) => notify.failure(schedule ? "Couldn't complete the maintenance." : "Couldn't log maintenance.", error),
          });
        }}
      >
        <Field label="Summary" className="sm:col-span-2">
          <Input value={summary} onChange={(event) => setSummary(event.target.value)} required />
        </Field>
        <Field label="Performed at" helperText="Leave empty for now.">
          <Input type="datetime-local" value={performedAt} onChange={(event) => setPerformedAt(event.target.value)} />
        </Field>
        <Field label={withCurrency("Cost", currency)} helperText="Optional.">
          <Input type="number" min="0" step="0.01" inputMode="decimal" value={cost} onChange={(event) => setCost(event.target.value)} />
        </Field>
        <Field label="Parts and notes" helperText="Optional." className="sm:col-span-2">
          <Textarea rows={3} value={partsNote} onChange={(event) => setPartsNote(event.target.value)} />
        </Field>
        <CheckboxField
          className="sm:col-span-2"
          label="Set machine status to idle"
          description="Use this when the machine is ready for work again."
          checked={setIdle}
          onCheckedChange={(checked) => setSetIdle(checked === true)}
        />
        {log.error instanceof Error ? <p className="text-caption text-danger-fg sm:col-span-2" role="alert">{log.error.message}</p> : null}
        <div className="flex flex-wrap gap-2 sm:col-span-2">
          <Button variant="primary" type="submit" loading={log.isPending} loadingLabel={schedule ? "Completing…" : "Logging…"} disabled={!summary.trim()}>
            {schedule ? "Complete maintenance" : "Log maintenance"}
          </Button>
          {onCancel ? <Button onClick={onCancel} disabled={log.isPending}>Cancel</Button> : null}
        </div>
      </form>
    </section>
  );
}

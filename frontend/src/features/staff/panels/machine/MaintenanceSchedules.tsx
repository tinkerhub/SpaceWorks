import { useState } from "react";
import { Plus } from "lucide-react";

import { Button, ConfirmDialog, EmptyState, Field, Input, SectionHeading, StatusChip } from "../../../../components/ui";
import {
  useCreateMaintenanceSchedule,
  useDeactivateMaintenanceSchedule,
  useUpdateMaintenanceSchedule,
  type MaintenanceSchedule,
  type ScheduleInput,
} from "./maintenanceApi";
import { formatDay, useNotify } from "./machineUi";

const emptySchedule = (): ScheduleInput => ({
  description: "",
  interval_days: 30,
  next_due: new Date().toISOString().slice(0, 10),
});

function ScheduleFields({ value, onChange, prefix }: {
  value: ScheduleInput;
  onChange: (value: ScheduleInput) => void;
  prefix: string;
}) {
  return (
    <>
      <Field label="Description" className="sm:col-span-2">
        <Input aria-label={`${prefix} description`} value={value.description} onChange={(event) => onChange({ ...value, description: event.target.value })} required />
      </Field>
      <Field label="Every (days)">
        <Input type="number" min={1} value={value.interval_days} onChange={(event) => onChange({ ...value, interval_days: Number(event.target.value) })} required />
      </Field>
      <Field label="Next due">
        <Input type="date" value={value.next_due} onChange={(event) => onChange({ ...value, next_due: event.target.value })} required />
      </Field>
    </>
  );
}

export function MaintenanceSchedules({
  makerspaceId, machineId, schedules, canEdit, retired, onComplete,
}: {
  makerspaceId: number;
  machineId: number;
  schedules: MaintenanceSchedule[];
  canEdit: boolean;
  retired: boolean;
  onComplete: (schedule: MaintenanceSchedule) => void;
}) {
  const notify = useNotify();
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<ScheduleInput>(emptySchedule);
  const [editing, setEditing] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<ScheduleInput>(emptySchedule);
  const [deactivateId, setDeactivateId] = useState<number | null>(null);
  const create = useCreateMaintenanceSchedule(makerspaceId, machineId);
  const update = useUpdateMaintenanceSchedule(makerspaceId, machineId);
  const deactivate = useDeactivateMaintenanceSchedule(makerspaceId, machineId);
  const active = schedules.filter((row) => row.is_active);
  const inactive = schedules.filter((row) => !row.is_active);
  const canChange = canEdit && !retired;

  return (
    <section className="grid gap-3" aria-labelledby="maintenance-schedules-title">
      <SectionHeading
        as="h3"
        title={<span id="maintenance-schedules-title">Maintenance schedules</span>}
        description="Recurring jobs and when each is next due."
        action={canChange && !adding ? <Button size="sm" startIcon={<Plus />} onClick={() => setAdding(true)}>Add schedule</Button> : null}
      />
      {canChange && adding ? (
        <form
          className="grid gap-3 rounded-lg border border-line bg-subtle p-4 sm:grid-cols-2"
          onSubmit={(event) => {
            event.preventDefault();
            create.mutate(draft, {
              onSuccess: () => { notify.success("Schedule created"); setDraft(emptySchedule()); setAdding(false); },
              onError: (error) => notify.failure("Couldn't create the schedule.", error),
            });
          }}
        >
          <h4 className="text-title text-ink sm:col-span-2">New schedule</h4>
          <ScheduleFields value={draft} onChange={setDraft} prefix="New schedule" />
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button type="submit" variant="primary" loading={create.isPending} loadingLabel="Creating…">Create schedule</Button>
            <Button onClick={() => { setAdding(false); create.reset(); }} disabled={create.isPending}>Cancel</Button>
          </div>
        </form>
      ) : null}
      {!schedules.length ? (
        <EmptyState
          title="No maintenance schedules"
          description={canChange ? "Add a recurring schedule to track upcoming maintenance." : "No recurring maintenance is set up for this machine."}
        />
      ) : null}
      {schedules.length ? (
        <ul className="grid gap-2">
          {[...active, ...inactive].map((schedule) => (
            <li key={schedule.id} className="rounded-lg border border-line bg-canvas p-4">
              {editing === schedule.id ? (
                <form
                  className="grid gap-3 sm:grid-cols-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    update.mutate({ id: schedule.id, input: editDraft }, {
                      onSuccess: () => { notify.success("Schedule saved"); setEditing(null); },
                      onError: (error) => notify.failure("Couldn't save the schedule.", error),
                    });
                  }}
                >
                  <ScheduleFields value={editDraft} onChange={setEditDraft} prefix="Edit schedule" />
                  <div className="flex flex-wrap gap-2 sm:col-span-2">
                    <Button type="submit" loading={update.isPending} loadingLabel="Saving…">Save schedule</Button>
                    <Button variant="quiet" onClick={() => setEditing(null)}>Cancel</Button>
                  </div>
                </form>
              ) : (
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <strong className="block text-body-ui font-semibold text-ink">{schedule.description}</strong>
                    <span className="text-caption text-ink-muted">
                      Every {schedule.interval_days} {schedule.interval_days === 1 ? "day" : "days"} · next due {formatDay(schedule.next_due)}
                    </span>
                  </div>
                  <StatusChip size="sm" tone={schedule.overdue ? "danger" : schedule.is_active ? "info" : "neutral"}>
                    {schedule.overdue ? "Overdue" : schedule.is_active ? "Scheduled" : "Inactive"}
                  </StatusChip>
                  {canChange && schedule.is_active ? (
                    <div className="flex w-full flex-wrap gap-2 sm:w-auto">
                      <Button size="sm" onClick={() => onComplete(schedule)}>Complete</Button>
                      <Button
                        size="sm"
                        variant="quiet"
                        onClick={() => {
                          setEditDraft({ description: schedule.description, interval_days: schedule.interval_days, next_due: schedule.next_due });
                          setEditing(schedule.id);
                        }}
                      >
                        Edit
                      </Button>
                      <Button size="sm" variant="danger-quiet" disabled={deactivate.isPending} onClick={() => setDeactivateId(schedule.id)}>
                        Deactivate…
                      </Button>
                    </div>
                  ) : null}
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {[create.error, update.error, deactivate.error].map((error, index) =>
        error instanceof Error ? <p key={index} className="text-caption text-danger-fg">{error.message}</p> : null,
      )}
      <ConfirmDialog
        open={deactivateId !== null}
        title="Deactivate maintenance schedule?"
        message="It stops coming due. Past maintenance records stay."
        confirmLabel="Deactivate schedule"
        tone="danger"
        pending={deactivate.isPending}
        onConfirm={() => {
          if (deactivateId !== null) {
            deactivate.mutate(deactivateId, {
              onSuccess: () => { notify.success("Schedule deactivated"); setDeactivateId(null); },
              onError: (error) => notify.failure("Couldn't deactivate the schedule.", error),
            });
          }
        }}
        onCancel={() => setDeactivateId(null)}
      />
    </section>
  );
}

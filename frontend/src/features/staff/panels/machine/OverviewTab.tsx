import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, ConfirmDialog, DangerZone, Dropdown, Field, Input, SectionHeading, Textarea } from "../../../../components/ui";
import {
  machineKeys,
  machineImageEndpoint,
  retireMachine,
  setMachineStatus,
  unretireMachine,
  updateMachine,
  type Machine,
  type MachineStatus,
} from "../../machinesApi";
import { ImageUploader } from "../../ImageUploader";
import { MachinePublicSettings } from "../MachinePublicSettings";
import { MACHINE_STATUSES, machineStatusLabel, useNotify } from "./machineUi";

type MachineForm = Pick<Machine, "name" | "location" | "notes" | "firmware_version" | "camera_feed_url">;

export function OverviewTab({ machine, makerspaceId, canManageMachines, canEdit, canOperate, canRetire, canUnretire }: {
  machine: Machine;
  makerspaceId: number;
  canManageMachines: boolean;
  canEdit: boolean;
  canOperate: boolean;
  canRetire: boolean;
  canUnretire: boolean;
}) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [form, setForm] = useState<MachineForm>({
    name: "", location: "", notes: "", firmware_version: "", camera_feed_url: "",
  });
  const [status, setStatus] = useState<MachineStatus>(machine.status);
  const [confirmRetire, setConfirmRetire] = useState(false);

  useEffect(() => {
    setForm({
      name: machine.name,
      location: machine.location,
      notes: machine.notes,
      firmware_version: machine.firmware_version,
      camera_feed_url: machine.camera_feed_url,
    });
    setStatus(machine.status);
  }, [machine]);

  const refreshMachine = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: machineKeys.detail(machine.id) }),
      queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
    ]);
  };
  const save = useMutation({
    mutationFn: () => updateMachine(machine.id, {
      name: form.name.trim(),
      location: form.location.trim(),
      notes: form.notes.trim(),
      firmware_version: form.firmware_version.trim(),
      camera_feed_url: form.camera_feed_url.trim(),
    }),
    onSuccess: async () => { notify.success("Machine details saved"); await refreshMachine(); },
    onError: (error) => notify.failure("Couldn't save the machine.", error),
  });
  const setStatusMutation = useMutation({
    mutationFn: () => setMachineStatus(machine.id, status),
    onSuccess: async () => { notify.success(`Status set to ${machineStatusLabel(status).toLowerCase()}`); await refreshMachine(); },
    onError: (error) => notify.failure("Couldn't change the status.", error),
  });
  const lifecycle = useMutation({
    mutationFn: (action: "retire" | "unretire") =>
      action === "retire" ? retireMachine(machine.id) : unretireMachine(machine.id),
    onSuccess: async (_machine, action) => {
      setConfirmRetire(false);
      notify.success(action === "retire" ? `${machine.name} retired` : `${machine.name} reactivated`);
      await refreshMachine();
    },
    onError: (error, action) => notify.failure(action === "retire" ? "Couldn't retire the machine." : "Couldn't reactivate the machine.", error),
  });
  const updateField = (field: keyof MachineForm, value: string) =>
    setForm((current) => ({ ...current, [field]: value }));
  const canChangeLifecycle = machine.is_active ? canRetire : canUnretire;
  // The server refuses status changes on a retired machine, so the control says why instead.
  const canSetStatus = canOperate && machine.is_active;

  return (
    <div className="grid gap-8">
      <section className="grid gap-3">
        <SectionHeading as="h3" title="Status" description={machine.is_active ? "What the machine is doing right now." : "Reactivate this machine to change its status."} />
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
          <Field label="Machine status" hideLabel className="flex-1">
            <Dropdown value={status} disabled={!canSetStatus} onChange={(event) => setStatus(event.target.value as MachineStatus)}>
              {MACHINE_STATUSES.map((value) => <option key={value} value={value}>{machineStatusLabel(value)}</option>)}
            </Dropdown>
          </Field>
          <Button disabled={!canSetStatus || status === machine.status} loading={setStatusMutation.isPending} loadingLabel="Setting…" onClick={() => setStatusMutation.mutate()}>
            Set status
          </Button>
        </div>
        {setStatusMutation.error instanceof Error ? <p className="text-caption text-danger-fg">{setStatusMutation.error.message}</p> : null}
      </section>

      <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
        <SectionHeading as="h3" title="Machine details" />
        <Field label="Name">
          <Input value={form.name} disabled={!canEdit} onChange={(event) => updateField("name", event.target.value)} required />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Location">
            <Input value={form.location} disabled={!canEdit} onChange={(event) => updateField("location", event.target.value)} />
          </Field>
          <Field label="Firmware version">
            <Input value={form.firmware_version} disabled={!canEdit} onChange={(event) => updateField("firmware_version", event.target.value)} />
          </Field>
        </div>
        <Field label="Camera feed URL">
          <Input type="url" value={form.camera_feed_url} disabled={!canEdit} onChange={(event) => updateField("camera_feed_url", event.target.value)} />
        </Field>
        <Field label="Notes">
          <Textarea value={form.notes} disabled={!canEdit} onChange={(event) => updateField("notes", event.target.value)} />
        </Field>
        {save.error instanceof Error ? <p className="text-caption text-danger-fg">{save.error.message}</p> : null}
        {canEdit ? (
          <Button className="justify-self-start" variant="primary" type="submit" loading={save.isPending} loadingLabel="Saving…" disabled={!form.name.trim()}>
            Save changes
          </Button>
        ) : null}
      </form>

      {canEdit ? (
        <section className="grid gap-3">
          <SectionHeading as="h3" title="Machine photo" />
          <ImageUploader
            endpoint={machineImageEndpoint(machine.id)}
            currentUrl={machine.image_url}
            label="Machine photo"
            onChanged={() => { void refreshMachine(); }}
          />
        </section>
      ) : null}

      {canManageMachines ? (
        <MachinePublicSettings machine={machine} makerspaceId={makerspaceId} />
      ) : null}

      {canChangeLifecycle ? (
        machine.is_active ? (
          <DangerZone
            title="Retire this machine"
            description="A retired machine goes offline, is hidden from the public listing and stops taking usage, operators and error logs. You can reactivate it later."
            action={<Button variant="danger" onClick={() => setConfirmRetire(true)}>Retire…</Button>}
          />
        ) : (
          <section className="flex flex-col gap-3 rounded-lg border border-line bg-subtle p-5 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <h3 className="text-label text-ink">This machine is retired</h3>
              <p className="mt-1 text-body-ui text-ink-secondary">Reactivate it to take work again.</p>
            </div>
            <Button loading={lifecycle.isPending} loadingLabel="Reactivating…" onClick={() => lifecycle.mutate("unretire")}>Reactivate</Button>
          </section>
        )
      ) : null}
      {lifecycle.error instanceof Error ? <p className="text-caption text-danger-fg">{lifecycle.error.message}</p> : null}

      <ConfirmDialog
        open={confirmRetire}
        title={`Retire ${machine.name}?`}
        message="It goes offline and is hidden from the public listing. Its history, documents and usage stay."
        confirmLabel="Retire machine"
        tone="danger"
        pending={lifecycle.isPending}
        onConfirm={() => lifecycle.mutate("retire")}
        onCancel={() => setConfirmRetire(false)}
      />
    </div>
  );
}

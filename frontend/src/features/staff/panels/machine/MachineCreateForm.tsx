import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Field, Input, SectionHeading } from "../../../../components/ui";
import { staffRequest } from "../../../../lib/api";
import { ImageUploader } from "../../ImageUploader";
import {
  createMachine,
  isBuiltinPrinterType,
  machineImageEndpoint,
  machineKeys,
  type Machine,
  type MachineType,
} from "../../machinesApi";
import { useNotify } from "./machineUi";

type Props = {
  makerspaceId: number;
  machineType: MachineType;
  onCreated: (machineId: number) => void;
  /** Leave before anything was created. */
  onCancel?: () => void;
  /** Finish after the optional photo / warranty step. */
  onDone?: () => void;
};

type WarrantyForm = {
  purchased_on: string;
  warranty_expires_on: string;
  vendor_name: string;
  vendor_contact: string;
};

const emptyWarranty: WarrantyForm = {
  purchased_on: "",
  warranty_expires_on: "",
  vendor_name: "",
  vendor_contact: "",
};

/** Two steps: name the machine (creates it), then optionally add a photo and warranty. */
export function MachineCreateForm({ makerspaceId, machineType, onCreated, onCancel, onDone }: Props) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const confirmationRef = useRef<HTMLParagraphElement>(null);
  const [name, setName] = useState("");
  const [model, setModel] = useState("");
  const [location, setLocation] = useState("");
  const [createdMachine, setCreatedMachine] = useState<Machine | null>(null);
  const [warrantyForm, setWarrantyForm] = useState<WarrantyForm>(emptyWarranty);
  const wantsModel = isBuiltinPrinterType(machineType);

  const refreshMachine = async (machineId: number) => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: machineKeys.detail(machineId) }),
      queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) }),
    ]);
  };

  const create = useMutation({
    mutationFn: () => createMachine(makerspaceId, {
      name: name.trim(),
      machine_type_id: machineType.id,
      location: location.trim(),
      notes: "",
      firmware_version: "",
      camera_feed_url: "",
      ...(wantsModel && model.trim() ? { type_payload: { model: model.trim() } } : {}),
    }),
    onSuccess: async (machine) => {
      setCreatedMachine(machine);
      onCreated(machine.id);
      notify.success(`${machine.name} added`);
      await queryClient.invalidateQueries({ queryKey: machineKeys.list(makerspaceId) });
    },
    onError: (error) => notify.failure("Couldn't add the machine.", error),
  });

  const warranty = useMutation({
    mutationFn: () => {
      if (!createdMachine) throw new Error("Create the machine before adding warranty details.");
      const payload = Object.fromEntries(
        Object.entries(warrantyForm).filter(([, value]) => value.trim()),
      );
      return staffRequest(`/admin/machines/${createdMachine.id}/warranty`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    },
    onSuccess: async () => {
      notify.success("Warranty saved");
      if (!createdMachine) return;
      // The list row carries `warranty_status`, and the drawer's Warranty tab caches the record.
      await Promise.all([
        refreshMachine(createdMachine.id),
        queryClient.invalidateQueries({ queryKey: ["warranty", "machine", createdMachine.id] }),
        queryClient.invalidateQueries({ queryKey: ["warranties"] }),
      ]);
    },
    onError: (error) => notify.failure("Couldn't save the warranty.", error),
  });

  useEffect(() => {
    if (createdMachine) confirmationRef.current?.focus();
  }, [createdMachine]);

  const updateWarranty = (field: keyof WarrantyForm, value: string) => {
    warranty.reset();
    setWarrantyForm((current) => ({ ...current, [field]: value }));
  };
  const hasWarrantyDetails = Object.values(warrantyForm).some((value) => value.trim());

  const finish = () => {
    setName("");
    setModel("");
    setLocation("");
    setWarrantyForm(emptyWarranty);
    setCreatedMachine(null);
    create.reset();
    warranty.reset();
    onDone?.();
  };

  return (
    <div className="grid gap-5">
      <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" className="sm:col-span-2">
            <Input aria-label="Machine name" value={name} onChange={(event) => setName(event.target.value)} required disabled={!!createdMachine} />
          </Field>
          {wantsModel ? (
            <Field label="Make and model">
              <Input aria-label="Printer model" value={model} onChange={(event) => setModel(event.target.value)} placeholder="e.g. Prusa MK4" disabled={!!createdMachine} />
            </Field>
          ) : null}
          <Field label="Location">
            <Input value={location} onChange={(event) => setLocation(event.target.value)} disabled={!!createdMachine} />
          </Field>
        </div>
        {create.error instanceof Error ? <p className="text-caption text-danger-fg" role="alert">{create.error.message}</p> : null}
        {createdMachine ? null : (
          <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
            {onCancel ? <Button onClick={onCancel} disabled={create.isPending}>Cancel</Button> : null}
            <Button variant="primary" type="submit" loading={create.isPending} loadingLabel="Adding…" disabled={!name.trim()}>
              {`Add ${machineType.name}`}
            </Button>
          </div>
        )}
      </form>

      {createdMachine ? (
        <div className="grid gap-5 border-t border-line pt-5">
          <Callout tone="success">
            <p ref={confirmationRef} tabIndex={-1} role="status" className="rounded-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus">
              {createdMachine.name} was created. Photo and warranty details are optional.
            </p>
          </Callout>

          <section className="grid gap-3">
            <SectionHeading as="h3" title="Machine photo" />
            <ImageUploader
              endpoint={machineImageEndpoint(createdMachine.id)}
              currentUrl={createdMachine.image_url}
              label="Machine photo"
              onChanged={() => { void refreshMachine(createdMachine.id); }}
            />
          </section>

          <form
            className="grid gap-3"
            aria-labelledby={`machine-warranty-${createdMachine.id}`}
            onSubmit={(event) => { event.preventDefault(); warranty.mutate(); }}
          >
            <h3 className="text-h4 text-ink" id={`machine-warranty-${createdMachine.id}`}>Warranty</h3>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Purchased on">
                <Input type="date" value={warrantyForm.purchased_on} onChange={(event) => updateWarranty("purchased_on", event.target.value)} />
              </Field>
              <Field label="Warranty expires on">
                <Input type="date" value={warrantyForm.warranty_expires_on} onChange={(event) => updateWarranty("warranty_expires_on", event.target.value)} />
              </Field>
              <Field label="Vendor name">
                <Input maxLength={200} value={warrantyForm.vendor_name} onChange={(event) => updateWarranty("vendor_name", event.target.value)} />
              </Field>
              <Field label="Vendor contact">
                <Input maxLength={200} value={warrantyForm.vendor_contact} onChange={(event) => updateWarranty("vendor_contact", event.target.value)} />
              </Field>
            </div>
            <Button className="justify-self-start" type="submit" loading={warranty.isPending} loadingLabel="Saving…" disabled={!hasWarrantyDetails}>
              Save warranty
            </Button>
            {warranty.isSuccess ? <p className="text-caption text-success-fg" role="status">Warranty details saved.</p> : null}
            {warranty.error instanceof Error ? (
              <p className="text-caption text-danger-fg" role="alert">
                {createdMachine.name} is still created. Warranty details were not saved: {warranty.error.message}
              </p>
            ) : null}
          </form>

          <div className="flex justify-end">
            <Button variant="primary" onClick={finish}>Done</Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

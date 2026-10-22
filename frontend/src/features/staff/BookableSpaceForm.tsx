import { useState, type FormEvent } from "react";

import { Button, Dropdown, ErrorText, Field, Input, SwitchRow, Textarea } from "../../components/ui";
import { CustomFormBuilder } from "../forms/CustomFormBuilder";
import type { CustomFormSchema } from "../forms/customFormTypes";
import type { BookableSpace, BookableSpacePayload } from "./bookingsApi";

type FormValues = BookableSpacePayload;

export const EMPTY_SPACE_FORM: FormValues = {
  name: "",
  kind: "other",
  description: "",
  capacity: 0,
  location: "",
  is_public: false,
  show_public_availability: false,
  show_public_booker_names: false,
  approval_mode: "instant",
  payment_amount: "0.00",
  custom_form: null,
  requester_notifications_enabled: null,
};

export function valuesForSpace(space: BookableSpace): FormValues {
  return {
    name: space.name,
    kind: space.kind,
    description: space.description,
    capacity: space.capacity,
    location: space.location,
    is_public: space.is_public,
    show_public_availability: space.show_public_availability,
    show_public_booker_names: space.show_public_booker_names,
    approval_mode: space.approval_mode,
    payment_amount: space.payment_amount,
    custom_form: space.custom_form,
    requester_notifications_enabled: space.requester_notifications_enabled,
  };
}

export function BookableSpaceForm({ initialValues = EMPTY_SPACE_FORM, onSubmit, pending, error, submitLabel, disabled = false }: {
  initialValues?: FormValues;
  onSubmit: (payload: BookableSpacePayload) => void;
  pending: boolean;
  error?: string;
  submitLabel: string;
  disabled?: boolean;
}) {
  const [values, setValues] = useState<FormValues>(initialValues);
  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => setValues((current) => ({ ...current, [key]: value }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({
      ...values,
      name: values.name.trim(),
      description: values.description.trim(),
      location: values.location.trim(),
      custom_form: values.custom_form?.length ? values.custom_form : null,
    });
  };
  const changeAvailability = (checked: boolean) => setValues((current) => ({
    ...current,
    show_public_availability: checked,
    show_public_booker_names: checked ? current.show_public_booker_names : false,
  }));
  const notificationsValue = values.requester_notifications_enabled === null
    ? "inherit"
    : values.requester_notifications_enabled ? "on" : "off";

  return (
    <form className="grid gap-5" onSubmit={submit}>
      <fieldset className="grid gap-4 sm:grid-cols-2" disabled={disabled || pending}>
        <Field label="Name" className="sm:col-span-2">
          <Input required maxLength={200} value={values.name} onChange={(event) => set("name", event.target.value)} />
        </Field>
        <Field label="Space type">
          <Dropdown required value={values.kind} disabled={disabled || pending} onChange={(event) => set("kind", event.target.value as FormValues["kind"])}>
            <option value="dev_room">Development room</option>
            <option value="bench">Bench</option>
            <option value="meeting">Meeting room</option>
            <option value="other">Other</option>
          </Dropdown>
        </Field>
        <Field label="Capacity" helperText="Use 0 when no capacity is published.">
          <Input type="number" min={0} value={values.capacity} onChange={(event) => set("capacity", Number(event.target.value))} />
        </Field>
        <Field label="Location" optional className="sm:col-span-2">
          <Input maxLength={255} value={values.location} onChange={(event) => set("location", event.target.value)} />
        </Field>
        <Field label="Description" optional className="sm:col-span-2">
          <Textarea rows={3} value={values.description} onChange={(event) => set("description", event.target.value)} />
        </Field>
        <Field label="Approval mode">
          <Dropdown value={values.approval_mode} disabled={disabled || pending} onChange={(event) => set("approval_mode", event.target.value as FormValues["approval_mode"])}>
            <option value="instant">Instant confirmation</option>
            <option value="approve">Staff approval required</option>
          </Dropdown>
        </Field>
        <Field label="Booking price" helperText="Use 0 for no charge.">
          <Input type="number" min="0" step="0.01" value={values.payment_amount} onChange={(event) => set("payment_amount", event.target.value)} />
        </Field>
        <Field label="Requester email">
          <Dropdown value={notificationsValue} disabled={disabled || pending} onChange={(event) => set("requester_notifications_enabled", event.target.value === "inherit" ? null : event.target.value === "on")}>
            <option value="inherit">Inherit makerspace setting</option>
            <option value="on">On</option>
            <option value="off">Off</option>
          </Dropdown>
        </Field>
        <div className="grid gap-4 rounded-lg border border-line p-4 sm:col-span-2">
          <SwitchRow
            label="Show on the public Bookings page"
            description="People can find this space and send a booking request."
            checked={values.is_public}
            disabled={disabled || pending}
            onCheckedChange={(checked) => set("is_public", checked)}
          />
          <SwitchRow
            label="Publish confirmed booking intervals"
            description="Visitors see when the space is already taken."
            checked={values.show_public_availability}
            disabled={disabled || pending}
            onCheckedChange={changeAvailability}
          />
          <SwitchRow
            label="Show booker names with published intervals"
            description="Needs published intervals."
            checked={values.show_public_booker_names}
            disabled={disabled || pending || !values.show_public_availability}
            onCheckedChange={(checked) => set("show_public_booker_names", checked)}
          />
        </div>
      </fieldset>
      <CustomFormBuilder value={values.custom_form as CustomFormSchema} onChange={(schema) => set("custom_form", schema)} disabled={disabled || pending} />
      <ErrorText message={error} />
      {!disabled ? (
        <Button variant="primary" type="submit" className="w-fit" loading={pending} loadingLabel="Saving…">
          {submitLabel}
        </Button>
      ) : null}
    </form>
  );
}

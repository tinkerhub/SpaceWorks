import type { Dispatch, SetStateAction } from "react";

import { CheckboxField, Dropdown, Field, Input, Textarea } from "../../components/ui";
import type { EventPayload, StaffEvent } from "./eventsApi";
import { withCurrency } from "./paymentsApi";
import { CustomFormBuilder } from "../forms/CustomFormBuilder";

export type EventFormValues = Omit<EventPayload, "starts_at" | "ends_at" | "registration_cutoff_at"> & {
  starts_at: string;
  ends_at: string;
  registration_cutoff_at: string | null;
};

export const emptyEventForm: EventFormValues = {
  title: "", description: "", starts_at: "", ends_at: "", location: "",
  timezone_name: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  capacity: 0, payment_amount: "0.00", registration_requires_approval: false,
  registration_cutoff_at: null, registration_cutoff_lead_minutes: null,
  is_public: false,
  custom_form: null,
};

function localDate(value: string) {
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function valuesFor(event: StaffEvent): EventFormValues {
  return {
    title: event.title, description: event.description,
    starts_at: localDate(event.starts_at), ends_at: localDate(event.ends_at),
    timezone_name: event.timezone_name,
    location: event.location, capacity: event.capacity,
    payment_amount: event.payment_amount,
    registration_requires_approval: event.registration_requires_approval,
    registration_cutoff_at: event.registration_cutoff_at ? localDate(event.registration_cutoff_at) : null,
    registration_cutoff_lead_minutes: event.registration_cutoff_lead_minutes,
    is_public: event.is_public,
    custom_form: event.custom_form,
  };
}

export function payloadFor(values: EventFormValues): EventPayload {
  return {
    ...values, title: values.title.trim(), description: values.description.trim(),
    location: values.location.trim(), starts_at: new Date(values.starts_at).toISOString(),
    ends_at: new Date(values.ends_at).toISOString(),
    registration_cutoff_at: values.registration_cutoff_at ? new Date(values.registration_cutoff_at).toISOString() : null,
  };
}

export function EventFields({ values, setValues, disabled = false, approvalLocked = false, currency = "" }: {
  values: EventFormValues; setValues: Dispatch<SetStateAction<EventFormValues>>;
  disabled?: boolean; approvalLocked?: boolean;
  /** Upper-case code shown beside the price, e.g. "INR"; omitted when unknown. */
  currency?: string;
}) {
  // Functional updates keep edits before the drawer's load effect re-renders from dropping required fields via a stale empty copy.
  const set = <K extends keyof EventFormValues>(key: K, value: EventFormValues[K]) => setValues((current) => ({ ...current, [key]: value }));
  const cutoffMode = values.registration_cutoff_at !== null ? "absolute" : values.registration_cutoff_lead_minutes !== null ? "lead" : "none";
  const setCutoffMode = (mode: string) => setValues((current) => ({
    ...current,
    registration_cutoff_at: mode === "absolute" ? (current.starts_at || "") : null,
    registration_cutoff_lead_minutes: mode === "lead" ? 0 : null,
  }));
  return <div className="grid gap-4 sm:grid-cols-2">
    <Field label="Title" className="sm:col-span-2"><Input value={values.title} onChange={(e) => set("title", e.target.value)} required disabled={disabled} maxLength={200} /></Field>
    <Field label="Starts"><Input type="datetime-local" value={values.starts_at} onChange={(e) => set("starts_at", e.target.value)} required disabled={disabled} /></Field>
    <Field label="Ends"><Input type="datetime-local" value={values.ends_at} onChange={(e) => set("ends_at", e.target.value)} required disabled={disabled} /></Field>
    <Field label="Event time zone" className="sm:col-span-2" helperText="Use an IANA name such as Asia/Kolkata. Review migrated events because their original zone was not recorded.">
      <Input className="font-mono" value={values.timezone_name} onChange={(e) => set("timezone_name", e.target.value)} required disabled={disabled} maxLength={64} />
    </Field>
    <Field label="Location" optional><Input value={values.location} onChange={(e) => set("location", e.target.value)} disabled={disabled} maxLength={255} /></Field>
    <Field label="Capacity" helperText="Use 0 for unlimited."><Input type="number" min="0" value={values.capacity} onChange={(e) => set("capacity", Number(e.target.value))} disabled={disabled} /></Field>
    <Field label={withCurrency("Registration price", currency)} helperText="Charged only when a place is confirmed."><Input type="number" min="0" step="0.01" value={values.payment_amount} onChange={(e) => set("payment_amount", e.target.value)} disabled={disabled} /></Field>
    <Field label="Registration cutoff">
      <Dropdown value={cutoffMode} disabled={disabled} onChange={(e) => setCutoffMode(e.target.value)}>
        <option value="none">No cutoff</option>
        <option value="absolute">At a date and time</option>
        <option value="lead">Before the event starts</option>
      </Dropdown>
    </Field>
    {cutoffMode === "absolute" ? <Field label="Cutoff time"><Input type="datetime-local" value={values.registration_cutoff_at ?? ""} onChange={(e) => set("registration_cutoff_at", e.target.value)} disabled={disabled} required /></Field> : null}
    {cutoffMode === "lead" ? <Field label="Minutes before start"><Input type="number" min="0" value={values.registration_cutoff_lead_minutes ?? 0} onChange={(e) => set("registration_cutoff_lead_minutes", Number(e.target.value))} disabled={disabled} /></Field> : null}
    <Field label="Description" optional className="sm:col-span-2"><Textarea value={values.description} onChange={(e) => set("description", e.target.value)} disabled={disabled} /></Field>
    <CheckboxField
      className="sm:col-span-2"
      label="Require staff approval for registrations"
      checked={values.registration_requires_approval}
      onCheckedChange={(checked) => set("registration_requires_approval", checked === true)}
      disabled={disabled || approvalLocked}
    />
    <CheckboxField
      className="sm:col-span-2"
      label="Show this event on the public Events page"
      checked={values.is_public}
      onCheckedChange={(checked) => set("is_public", checked === true)}
      disabled={disabled}
    />
    <div className="sm:col-span-2"><CustomFormBuilder value={values.custom_form} onChange={(value) => set("custom_form", value)} disabled={disabled} /></div>
  </div>;
}

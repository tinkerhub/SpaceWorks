import { CheckboxField, Dropdown, Field, Input, Textarea } from "../../components/ui";
import { CustomFormBuilder } from "../forms/CustomFormBuilder";
import type { EventSeries, EventSeriesPayload } from "./eventSeriesApi";

export type SeriesFormValues = EventSeriesPayload & {
  frequency: "DAILY" | "WEEKLY" | "MONTHLY";
  interval: number;
  byday: string;
};

const zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
export const emptySeriesForm: SeriesFormValues = {
  title: "", description: "", location: "", location_kind: "other", custom_form: null,
  capacity: 0, payment_amount: "0.00", registration_requires_approval: false,
  registration_cutoff_lead_minutes: null, is_public: false,
  recurrence_timezone: zone, dtstart_local_date: "", dtstart_local_time: "",
  recurrence_rule: "FREQ=WEEKLY;INTERVAL=1", duration_minutes: 60,
  frequency: "WEEKLY", interval: 1, byday: "",
};

export function valuesForSeries(series: EventSeries): SeriesFormValues {
  const parts = Object.fromEntries(series.recurrence_rule.split(";").map((part) => part.split("=", 2)));
  return {
    ...series,
    frequency: (parts.FREQ as SeriesFormValues["frequency"]) || "WEEKLY",
    interval: Number(parts.INTERVAL || 1),
    byday: parts.BYDAY || "",
  };
}

export function seriesPayload(values: SeriesFormValues): EventSeriesPayload {
  const rule = [`FREQ=${values.frequency}`, `INTERVAL=${Math.max(1, values.interval)}`];
  if (values.frequency === "WEEKLY" && values.byday.trim()) rule.push(`BYDAY=${values.byday.trim().toUpperCase()}`);
  const { frequency: _frequency, interval: _interval, byday: _byday, ...payload } = values;
  return { ...payload, recurrence_rule: rule.join(";"), title: payload.title.trim(), location: payload.location.trim() };
}

export function EventSeriesFields({ values, setValues, disabled = false }: {
  values: SeriesFormValues; setValues: (values: SeriesFormValues) => void; disabled?: boolean;
}) {
  const set = <K extends keyof SeriesFormValues>(key: K, value: SeriesFormValues[K]) => setValues({ ...values, [key]: value });
  const unit = { DAILY: "day", WEEKLY: "week", MONTHLY: "month" }[values.frequency];
  const cadence = `Every ${values.interval > 1 ? values.interval + " " : ""}${unit}${values.interval > 1 ? "s" : ""} at ${values.dtstart_local_time || "the selected time"} (${values.recurrence_timezone}).`;
  return <div className="grid gap-4 sm:grid-cols-2">
    <Field label="Series title" className="sm:col-span-2"><Input required maxLength={200} disabled={disabled} value={values.title} onChange={(e) => set("title", e.target.value)} /></Field>
    <Field label="First local date"><Input type="date" required disabled={disabled} value={values.dtstart_local_date} onChange={(e) => set("dtstart_local_date", e.target.value)} /></Field>
    <Field label="Local start time"><Input type="time" required disabled={disabled} value={values.dtstart_local_time} onChange={(e) => set("dtstart_local_time", e.target.value)} /></Field>
    <Field label="IANA timezone" helperText="Wall-clock time stays fixed across daylight-saving changes."><Input className="font-mono" required disabled={disabled} value={values.recurrence_timezone} onChange={(e) => set("recurrence_timezone", e.target.value)} /></Field>
    <Field label="Duration (minutes)"><Input type="number" min="1" required disabled={disabled} value={values.duration_minutes} onChange={(e) => set("duration_minutes", Number(e.target.value))} /></Field>
    <Field label="Repeats">
      <Dropdown disabled={disabled} value={values.frequency} onChange={(e) => set("frequency", e.target.value as SeriesFormValues["frequency"])}>
        <option value="DAILY">Daily</option>
        <option value="WEEKLY">Weekly</option>
        <option value="MONTHLY">Monthly</option>
      </Dropdown>
    </Field>
    <Field label="Every"><Input type="number" min="1" disabled={disabled} value={values.interval} onChange={(e) => set("interval", Number(e.target.value))} /></Field>
    {values.frequency === "WEEKLY" ? <Field label="Weekdays" optional className="sm:col-span-2" helperText="Two-letter days separated by commas, e.g. MO,WE,FR."><Input className="font-mono" disabled={disabled} placeholder="MO,WE,FR" value={values.byday} onChange={(e) => set("byday", e.target.value)} /></Field> : null}
    <p className="rounded-md bg-subtle px-3.5 py-2.5 text-body-ui text-ink-secondary sm:col-span-2" role="status">{cadence}</p>
    <Field label="Location" optional><Input maxLength={255} disabled={disabled} value={values.location} onChange={(e) => set("location", e.target.value)} /></Field>
    <Field label="Capacity per occurrence" helperText="Use 0 for unlimited."><Input type="number" min="0" disabled={disabled} value={values.capacity} onChange={(e) => set("capacity", Number(e.target.value))} /></Field>
    <Field label="Price per occurrence"><Input type="number" min="0" step="0.01" disabled={disabled} value={values.payment_amount} onChange={(e) => set("payment_amount", e.target.value)} /></Field>
    <Field label="Registration closes minutes before" optional><Input type="number" min="0" disabled={disabled} value={values.registration_cutoff_lead_minutes ?? ""} onChange={(e) => set("registration_cutoff_lead_minutes", e.target.value === "" ? null : Number(e.target.value))} /></Field>
    <Field label="Description" optional className="sm:col-span-2"><Textarea disabled={disabled} value={values.description} onChange={(e) => set("description", e.target.value)} /></Field>
    <CheckboxField label="Require approval" disabled={disabled} checked={values.registration_requires_approval} onCheckedChange={(checked) => set("registration_requires_approval", checked === true)} />
    <CheckboxField label="Public occurrences" disabled={disabled} checked={values.is_public} onCheckedChange={(checked) => set("is_public", checked === true)} />
    <div className="sm:col-span-2"><CustomFormBuilder value={values.custom_form} onChange={(value) => set("custom_form", value)} disabled={disabled} /></div>
  </div>;
}

import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Card, CardHeader, Dropdown, EmptyState, Field, Input, SettingsRow, Skeleton, useToast } from "../../components/ui";
import { StructuredApiError, staffRequest } from "../../lib/api";
import { useStaffGet } from "./StaffPanels";
import type { Makerspace } from "./panels/shared";

type SpaceRules = {
  id: number;
  name: string;
  is_active: boolean;
  approval_mode: "instant" | "approve";
  min_booking_duration_minutes: number;
  max_booking_duration_minutes: number;
  booking_lead_time_minutes: number;
  max_booking_advance_days: number;
};

type RuleField =
  | "min_booking_duration_minutes"
  | "max_booking_duration_minutes"
  | "booking_lead_time_minutes"
  | "max_booking_advance_days"
  | "approval_mode";
type NumberRuleField = Exclude<RuleField, "approval_mode">;
type RuleDraft = Record<NumberRuleField, string> & {
  approval_mode: SpaceRules["approval_mode"];
};
type FieldErrors = Partial<Record<RuleField, string>>;

const NUMBER_FIELDS: Array<{ key: NumberRuleField; label: string; min: number }> = [
  { key: "min_booking_duration_minutes", label: "Minimum booking duration (minutes)", min: 1 },
  { key: "max_booking_duration_minutes", label: "Maximum booking duration (minutes)", min: 1 },
  { key: "booking_lead_time_minutes", label: "Booking lead time (minutes)", min: 0 },
  { key: "max_booking_advance_days", label: "Maximum booking advance (days)", min: 1 },
];
const RULE_FIELDS: RuleField[] = [...NUMBER_FIELDS.map(({ key }) => key), "approval_mode"];

export function MakerspaceBookingRulesSettings({ makerspace }: { makerspace: Makerspace }) {
  // page_size=200 is the backend max; a makerspace never has that many
  // bookable spaces, so one page always covers the whole editable set.
  const spaces = useStaffGet<{ count: number; results: SpaceRules[] }>(
    ["booking-rule-spaces", makerspace.id],
    `/admin/makerspaces/${makerspace.id}/spaces/?page_size=200`,
  );
  const activeSpaces = spaces.data?.results.filter((space) => space.is_active) ?? [];

  return (
    <Card as="section">
      <CardHeader title="Booking rules per space" description="How long, how far ahead and with whose approval each active space can be booked." />
      {spaces.isLoading ? (
        <div className="grid gap-3" aria-busy="true">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : null}
      {!spaces.isLoading && !spaces.error && activeSpaces.length === 0 ? (
        <EmptyState title="No active bookable spaces" description="Add or reactivate a space in Bookings, then set its rules here." />
      ) : null}
      {activeSpaces.map((space) => (
        <SpaceRuleRow key={space.id} makerspaceId={makerspace.id} space={space} />
      ))}
      {spaces.error ? <p role="alert" className="mt-3 text-caption text-danger-fg">{spaces.error.message}</p> : null}
    </Card>
  );
}

function SpaceRuleRow({ makerspaceId, space }: { makerspaceId: number; space: SpaceRules }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [draft, setDraft] = useState<RuleDraft>(() => draftFromSpace(space));
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [rowError, setRowError] = useState("");

  useEffect(() => {
    setDraft(draftFromSpace(space));
    setFieldErrors({});
    setRowError("");
  }, [
    space.id,
    space.min_booking_duration_minutes,
    space.max_booking_duration_minutes,
    space.booking_lead_time_minutes,
    space.max_booking_advance_days,
    space.approval_mode,
  ]);

  const updateRules = useMutation({
    mutationFn: () =>
      staffRequest<SpaceRules>(`/admin/spaces/${space.id}/booking-rules/`, {
        method: "PATCH",
        body: JSON.stringify({
          min_booking_duration_minutes: Number(draft.min_booking_duration_minutes),
          max_booking_duration_minutes: Number(draft.max_booking_duration_minutes),
          booking_lead_time_minutes: Number(draft.booking_lead_time_minutes),
          max_booking_advance_days: Number(draft.max_booking_advance_days),
          approval_mode: draft.approval_mode,
        }),
      }),
    onMutate: () => {
      setFieldErrors({});
      setRowError("");
    },
    onError: (error) => {
      const parsed = parseRuleErrors(error);
      setFieldErrors(parsed.fieldErrors);
      setRowError(parsed.rowError);
      showToast(`Couldn't save the rules for ${space.name}`, { tone: "error" });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["booking-rule-spaces", makerspaceId] });
      showToast(`Rules for ${space.name} saved`, { tone: "success" });
    },
  });

  return (
    <SettingsRow title={space.name} description={draft.approval_mode === "approve" ? "Staff approve each booking." : "Bookings confirm instantly."}>
      <form
        className="grid min-w-0 gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          updateRules.mutate();
        }}
      >
        <div className="grid min-w-0 gap-4 sm:grid-cols-2">
          {NUMBER_FIELDS.map(({ key, label, min }) => (
            <Field key={key} label={label} error={fieldErrors[key]}>
              <Input
                aria-label={`${label} for ${space.name}`}
                type="number"
                min={min}
                value={draft[key]}
                disabled={updateRules.isPending}
                onChange={(event) => setDraft((current) => ({ ...current, [key]: event.target.value }))}
              />
            </Field>
          ))}
          <Field label="Approval mode" error={fieldErrors.approval_mode}>
            <Dropdown
              aria-label={`Approval mode for ${space.name}`}
              value={draft.approval_mode}
              disabled={updateRules.isPending}
              onChange={(event) => setDraft((current) => ({
                ...current,
                approval_mode: event.target.value as SpaceRules["approval_mode"],
              }))}
            >
              <option value="instant">Instant confirmation</option>
              <option value="approve">Staff approval required</option>
            </Dropdown>
          </Field>
        </div>
        {rowError ? <p role="alert" className="text-caption text-danger-fg">{rowError}</p> : null}
        <div>
          <Button type="submit" loading={updateRules.isPending} loadingLabel="Saving…">
            Save rules
          </Button>
        </div>
      </form>
    </SettingsRow>
  );
}

function draftFromSpace(space: SpaceRules): RuleDraft {
  return {
    min_booking_duration_minutes: String(space.min_booking_duration_minutes),
    max_booking_duration_minutes: String(space.max_booking_duration_minutes),
    booking_lead_time_minutes: String(space.booking_lead_time_minutes),
    max_booking_advance_days: String(space.max_booking_advance_days),
    approval_mode: space.approval_mode,
  };
}

function parseRuleErrors(error: unknown): { fieldErrors: FieldErrors; rowError: string } {
  if (!(error instanceof StructuredApiError) || error.status !== 400) {
    return {
      fieldErrors: {},
      rowError: error instanceof Error ? error.message : "Unable to save booking rules.",
    };
  }

  const fieldErrors: FieldErrors = {};
  RULE_FIELDS.forEach((field) => {
    const message = errorMessage(error.body[field]);
    if (message) fieldErrors[field] = message;
  });
  const rowError = [errorMessage(error.body.detail), errorMessage(error.body.non_field_errors)]
    .filter(Boolean)
    .join(" ");

  return {
    fieldErrors,
    rowError: rowError || (Object.keys(fieldErrors).length === 0 ? error.message : ""),
  };
}

function errorMessage(value: unknown) {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.filter((item) => typeof item === "string").join(" ");
  return "";
}

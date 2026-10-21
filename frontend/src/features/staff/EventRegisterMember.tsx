import { useState } from "react";

import { Button, Card, Dropdown, ErrorText, Field, Input, useToast } from "../../components/ui";
import { CustomFormFields } from "../forms/CustomFormFields";
import {
  customAnswerErrors,
  validateCustomAnswers,
  type CustomAnswers,
} from "../forms/customFormTypes";
import { StructuredApiError } from "../../lib/api";
import { useEventEligibleMembers, useRegisterMemberForEvent, type StaffEvent } from "./eventsApi";

/**
 * Register a member for an event from the roster — the desk counterpart to public
 * self-registration.
 *
 * Only members of this makerspace appear, and only ones not already registered: a
 * picker entry whose every use returns "already registered" is an error the interface
 * should not have offered.
 *
 * The phone and email fields appear only after the server asks for one. A registration
 * needs both a contact number and an address, and a staff-created walk-in may carry
 * neither, so rather than demanding them every time, the form asks exactly when one
 * turns out to be missing. Without these the backend's fallbacks would be unreachable
 * from the console, which is the same as not having them: the members this program made
 * registrable are precisely the ones whose accounts are empty.
 */
export function EventRegisterMember({
  makerspaceId,
  eventId,
  customForm,
  disabled,
}: {
  makerspaceId: number;
  eventId: number;
  customForm: StaffEvent["custom_form"];
  disabled: boolean;
}) {
  const [memberId, setMemberId] = useState("");
  const [phone, setPhone] = useState("");
  const [needsPhone, setNeedsPhone] = useState(false);
  const [email, setEmail] = useState("");
  const [needsEmail, setNeedsEmail] = useState(false);
  // Without this the console could never register anyone for an event whose form has a
  // required question: the backend validates answers on this path exactly as it does for
  // public self-registration, so a form with no way to answer it is a permanent 400.
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [answerErrors, setAnswerErrors] = useState<Record<string, string>>({});
  const members = useEventEligibleMembers(eventId, !disabled);
  const register = useRegisterMemberForEvent(makerspaceId, eventId);
  const { showToast } = useToast();

  if (disabled) return null;

  const serverAnswerErrors = customAnswerErrors(
    register.error instanceof StructuredApiError
      ? register.error.body.custom_answers
      : undefined,
  );
  const submit = () => {
    // Validated here as well as on the server, so a missing required answer is shown
    // beside the question rather than returned as a whole-form 400.
    const nextErrors = validateCustomAnswers(customForm ?? [], answers);
    setAnswerErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    register.mutate(
      {
        member_id: Number(memberId),
        ...(phone.trim() ? { phone: phone.trim() } : {}),
        ...(email.trim() ? { email: email.trim() } : {}),
        ...(customForm?.length ? { custom_answers: answers } : {}),
      },
      {
        onSuccess: () => {
          showToast("Member registered", { tone: "success" });
          setMemberId("");
          setPhone("");
          setNeedsPhone(false);
          setEmail("");
          setNeedsEmail(false);
          setAnswers({});
          setAnswerErrors({});
        },
        onError: (error) => {
          // Read the FIELD-KEYED body, never the message. `StructuredApiError` builds
          // its message from `Object.values(body)` alone, so a DRF field error arrives
          // as the bare string "This field cannot be blank." — it contains neither
          // "phone" nor "email", and matching on it never fires. That is why the phone
          // prompt this mirrors had never once appeared.
          //
          // A record missing both fields is refused on one of them at a time, so these
          // accumulate rather than replace each other — clearing the phone prompt when
          // the next attempt fails on email would hide the answer just given.
          showToast(error instanceof Error ? error.message : "Could not register.", { tone: "error" });
          if (!(error instanceof StructuredApiError)) return;
          if (error.body.phone) setNeedsPhone(true);
          if (error.body.email) setNeedsEmail(true);
        },
      },
    );
  };

  return (
    <Card padding="sm" className="grid gap-3 bg-subtle">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <Field label="Register a member" className="min-w-0 flex-1">
          <Dropdown
            id="event-register-member"
            value={memberId}
            disabled={members.isLoading}
            onChange={(event) => {
              setMemberId(event.target.value);
              // A fallback contact belongs to one specific person and must never carry
              // across to another.
              setPhone("");
              setNeedsPhone(false);
              setEmail("");
              setNeedsEmail(false);
            }}
          >
            <option value="">
              {members.isLoading ? "Loading members…" : "Select a member"}
            </option>
            {(members.data ?? []).map((row) => (
              <option key={row.member_id} value={String(row.member_id)}>
                {row.display_name}
              </option>
            ))}
          </Dropdown>
        </Field>
        <Button
          variant="primary"
          className="shrink-0"
          disabled={!memberId}
          loading={register.isPending}
          loadingLabel="Registering…"
          onClick={submit}
        >
          Register
        </Button>
      </div>
      {customForm?.length ? (
        <CustomFormFields
          schema={customForm}
          answers={answers}
          onChange={setAnswers}
          errors={{ ...answerErrors, ...serverAnswerErrors }}
          disabled={register.isPending}
        />
      ) : null}
      {needsPhone ? (
        <Field label="Contact number" helperText="This member's account has no number on file.">
          <Input id="event-register-phone" type="tel" value={phone} onChange={(event) => setPhone(event.target.value)} />
        </Field>
      ) : null}
      {needsEmail ? (
        <Field label="Contact email" helperText="This member's account has no address on file.">
          <Input id="event-register-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </Field>
      ) : null}
      {register.error ? (
        <ErrorText message={register.error instanceof Error ? register.error.message : "Could not register."} />
      ) : null}
      {members.data && !members.data.length ? (
        <p className="text-body-ui text-ink-muted">Every member is already registered.</p>
      ) : null}
    </Card>
  );
}

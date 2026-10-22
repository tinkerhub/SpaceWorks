import { useEffect, useRef, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, ErrorText, useToast } from "../../components/ui";
import type { ApiPath } from "../../generated/api";
import { StructuredApiError, tenantPublicRequest } from "../../lib/api";
import { CustomFormFields } from "../forms/CustomFormFields";
import {
  customAnswerErrors,
  validateCustomAnswers,
  type CustomAnswers,
  type CustomFormSchema,
} from "../forms/customFormTypes";

type RegistrationResult = { status: "pending_approval" | "registered" | "waitlisted" };

const REGISTER_PATH: ApiPath = "/api/v1/public/{makerspace_slug}/events/{public_token}/register/";

function registerPath(slug: string, token: string) {
  return REGISTER_PATH.replace("/api/v1", "")
    .replace("{makerspace_slug}", encodeURIComponent(slug))
    .replace("{public_token}", encodeURIComponent(token));
}

function failureMessage(error: StructuredApiError | null) {
  if (!error) return "The registration could not be submitted.";
  if (error.status === 401) return "Sign in to register for this event.";
  if (error.status === 403 && error.code === "membership_required") return "Join this makerspace before registering.";
  if (error.status === 403 && error.code === "waiver_acceptance_required") return "Accept the current waiver before registering.";
  if (error.status === 403 && error.code === "presence_required") return "Start a presence session before registering.";
  if (error.status === 429) return "Too many registration attempts. Please wait and try again.";
  if (error.status === 409 && error.code === "registration_closed") return "Registration for this event is closed.";
  if (error.status === 409 && error.code === "registration_rejected") return "Your application was not approved and cannot be resubmitted.";
  return error.detail ?? error.message;
}

export function EventRegistrationForm({ makerspaceSlug, publicToken, waitlist, approvalRequired, customForm }: {
  makerspaceSlug: string; publicToken: string; waitlist: boolean; approvalRequired: boolean;
  customForm: CustomFormSchema;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [website, setWebsite] = useState("");
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});
  const successRef = useRef<HTMLDivElement>(null);
  const registration = useMutation({
    mutationFn: async () => {
      const rawTransportBody = { website, custom_answers: answers };
      return tenantPublicRequest<RegistrationResult>(makerspaceSlug, registerPath(makerspaceSlug, publicToken), {
        method: "POST", body: JSON.stringify(rawTransportBody),
      });
    },
    onSuccess: async (result) => {
      showToast(result.status === "pending_approval" ? "Application sent" : result.status === "waitlisted" ? "Added to the waitlist" : "You're registered", { tone: "success" });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["public-events", makerspaceSlug] }),
        queryClient.invalidateQueries({ queryKey: ["member", makerspaceSlug, "activity"] }),
      ]);
    },
    onError: () => showToast("Registration didn't go through", { tone: "error" }),
  });
  useEffect(() => { if (registration.data) successRef.current?.focus(); }, [registration.data]);

  if (registration.data) {
    const status = registration.data.status;
    return (
      <div ref={successRef} className="rounded-lg outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus" role="status" tabIndex={-1}>
        <Callout
          tone={status === "registered" ? "success" : "info"}
          title={status === "pending_approval" ? "Application awaiting approval" : status === "waitlisted" ? "You’re on the waitlist" : "Registration received"}
        >
          {status === "pending_approval" ? "You will only be charged if a place is confirmed." : status === "waitlisted" ? "The makerspace has recorded your waitlist request." : "The makerspace has recorded your registration."}
        </Callout>
      </div>
    );
  }

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const errors = validateCustomAnswers(customForm, answers);
    setClientErrors(errors);
    if (Object.keys(errors).length) return;
    if (!registration.isPending) registration.mutate();
  };
  const apiError = registration.error instanceof StructuredApiError ? registration.error : null;
  const serverErrors = customAnswerErrors(apiError?.body.custom_answers);

  return <form className="grid gap-4 rounded-lg border border-line bg-subtle p-4 sm:p-5" onSubmit={submit} noValidate>
    <h3 className="text-title text-ink">{approvalRequired ? "Apply" : waitlist ? "Join the waitlist" : "Register"}</h3>
    <label className="absolute left-[-10000px] top-auto h-px w-px overflow-hidden" aria-hidden="true">Website
      <input name="website" tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} />
    </label>
    <CustomFormFields schema={customForm} answers={answers} onChange={setAnswers} errors={{ ...serverErrors, ...clientErrors }} />
    {registration.error ? <ErrorText message={failureMessage(apiError)} /> : null}
    <Button variant="primary" type="submit" className="justify-self-start" loading={registration.isPending} loadingLabel="Submitting…">
      {approvalRequired ? "Apply" : waitlist ? "Join waitlist" : "Register"}
    </Button>
  </form>;
}

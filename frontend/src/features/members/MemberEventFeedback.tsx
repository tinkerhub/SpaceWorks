import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, ErrorText, Field, Input, Spinner, StatusChip, useToast } from "../../components/ui";
import { memberRequest } from "../../lib/api";
import { CustomFormFields } from "../forms/CustomFormFields";
import { validateCustomAnswers, type CustomAnswers, type CustomFormQuestion } from "../forms/customFormTypes";

type Form = {
  survey: { title: string; questions: CustomFormQuestion[] };
  requires_auth: boolean;
  certificate: { id: number; status: string; revision: number } | null;
};

export function MemberEventFeedback({ makerspaceId, makerspaceSlug, registrationId, feedbackPath, certificate }: {
  makerspaceId: number;
  makerspaceSlug: string;
  registrationId: number;
  feedbackPath: string | null;
  certificate: { id: number; status: string; revision: number } | null;
}) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [email, setEmail] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const form = useQuery({
    queryKey: ["member", makerspaceSlug, "event-feedback", registrationId],
    queryFn: () => memberRequest<Form>(feedbackPath!),
    enabled: open && Boolean(feedbackPath),
  });
  const submit = useMutation({
    mutationFn: () => memberRequest(feedbackPath!, {
      method: "POST", body: JSON.stringify({ answers, ...(form.data?.requires_auth ? { email } : {}) }),
    }),
    onSuccess: async () => {
      showToast("Feedback sent", { tone: "success" });
      setAnswers({});
      setEmail("");
      setErrors({});
      await client.invalidateQueries({ queryKey: ["member"] });
      await form.refetch();
    },
    onError: () => showToast("Feedback not sent", { tone: "error" }),
  });
  const download = useMutation({
    mutationFn: (certificateId: number) => memberRequest<{ url: string }>(`/member/makerspaces/${makerspaceId}/event-certificates/${certificateId}/download/`),
    onSuccess: async (result) => {
      await client.invalidateQueries({ queryKey: ["member", makerspaceSlug, "activity"] });
      window.location.assign(result.url);
    },
    onError: () => showToast("Certificate not ready", { tone: "error" }),
  });

  const certificateAction = certificate ? CERTIFICATE_ACTIONS[certificate.status] : undefined;
  const failure = form.error || submit.error || download.error;
  return <div className="flex flex-col gap-3">
    <div className="flex flex-wrap items-center gap-2">
      {feedbackPath ? <Button size="sm" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? "Close feedback" : "Leave feedback"}</Button> : null}
      {certificate && certificateAction ? <Button size="sm" loading={download.isPending} onClick={() => download.mutate(certificate.id)}>{certificateAction}</Button> : null}
      {certificate?.status === "revoked" ? <StatusChip size="sm" tone="danger">Certificate revoked</StatusChip> : null}
    </div>
    {open && form.isLoading ? <p className="inline-flex items-center gap-2 text-body-ui text-ink-muted"><Spinner decorative className="size-4" />Loading feedback form…</p> : null}
    {open && form.data ? <form className="flex flex-col gap-4 rounded-lg border border-line bg-canvas p-4" onSubmit={(event) => { event.preventDefault(); const next = validateCustomAnswers(form.data!.survey.questions, answers); setErrors(next); if (!Object.keys(next).length) submit.mutate(); }}>
      <h3 className="text-label text-ink">{form.data.survey.title}</h3>
      <CustomFormFields schema={form.data.survey.questions} answers={answers} onChange={setAnswers} errors={errors} yesNoAsCheckbox />
      {form.data.requires_auth ? <Field label="Registration email"><Input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></Field> : null}
      <Button variant="primary" type="submit" className="self-start" loading={submit.isPending} loadingLabel="Submitting…">Submit feedback</Button>
      {submit.isSuccess ? <Callout tone="success" role="status">Feedback recorded.</Callout> : null}
    </form> : null}
    <ErrorText message={failure?.message} />
  </div>;
}

const CERTIFICATE_ACTIONS: Record<string, string> = {
  active: "Download certificate",
  pending: "Prepare certificate",
  failed: "Retry certificate",
};

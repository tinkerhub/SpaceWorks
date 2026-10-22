import { useEffect, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { MakerspaceSiteHeader } from "../../components/chrome/PublicHeaders";
import { PublicContainer, PublicShell } from "../../components/chrome/PublicShell";
import { Button, Callout, Card, ErrorText, Field, Input, PageHeader, Skeleton, buttonClasses, useToast } from "../../components/ui";
import { getAccessToken, refreshAccessToken, StructuredApiError, tenantPublicRequest } from "../../lib/api";
import { useModules } from "../../lib/modules";
import { CustomFormFields } from "../forms/CustomFormFields";
import { customAnswerErrors, validateCustomAnswers, type CustomAnswers, type CustomFormQuestion } from "../forms/customFormTypes";
import { useMakerspacePublic } from "./useMakerspacePublic";

type FeedbackForm = {
  event: { title: string; starts_at: string; ends_at: string };
  survey: { title: string; thank_you_text: string; questions: CustomFormQuestion[] };
  mode: "anonymous" | "certificate";
  requires_auth: boolean;
  certificate: { id: number; status: string; revision: number } | null;
};

function feedbackPath(slug: string, token: string) {
  return `/public/${encodeURIComponent(slug)}/events/${encodeURIComponent(token)}/feedback/`;
}

export function PublicEventFeedbackPage() {
  const { publicToken = "" } = useParams();
  const space = useMakerspacePublic();
  const { makerspaceSlug, tenantPath } = space;
  const { moduleEnabled } = useModules();
  const { showToast } = useToast();
  const client = useQueryClient();
  const path = feedbackPath(makerspaceSlug, publicToken);
  const [answers, setAnswers] = useState<CustomAnswers>({});
  const [email, setEmail] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [restored, setRestored] = useState(Boolean(getAccessToken()));
  const form = useQuery({
    queryKey: ["public-event-feedback", makerspaceSlug, publicToken],
    queryFn: () => tenantPublicRequest<FeedbackForm>(makerspaceSlug, path),
  });
  useEffect(() => {
    if (form.data?.requires_auth && !restored) refreshAccessToken().then(setRestored);
  }, [form.data?.requires_auth, restored]);
  const submit = useMutation({
    mutationFn: () => tenantPublicRequest<{ thank_you_text: string; certificate: FeedbackForm["certificate"] }>(makerspaceSlug, path, {
      method: "POST", body: JSON.stringify({ answers, ...(form.data?.requires_auth ? { email } : {}) }),
    }),
    onSuccess: async () => {
      setAnswers({}); setEmail(""); setErrors({});
      showToast("Feedback sent", { tone: "success" });
      await client.invalidateQueries({ queryKey: ["public-event-feedback", makerspaceSlug, publicToken] });
    },
    onError: () => showToast("Feedback wasn't sent", { tone: "error" }),
  });
  const apiErrors = submit.error instanceof StructuredApiError ? submit.error.body.answers : undefined;

  const shell = (children: ReactNode) => (
    <PublicShell header={<MakerspaceSiteHeader {...space.header} moduleEnabled={moduleEnabled} page="Event feedback" />}>
      <PublicContainer width="sm">{children}</PublicContainer>
    </PublicShell>
  );

  if (form.isLoading) {
    return shell(
      <div className="space-y-4" aria-busy="true" aria-label="Loading feedback form">
        <Skeleton className="h-9 w-2/3" />
        <Skeleton className="h-64 w-full rounded-lg" />
      </div>,
    );
  }
  if (form.error || !form.data) {
    return shell(
      <PageHeader
        title="Feedback unavailable"
        description="This survey is closed, the event has not ended, or the link is invalid."
        actions={<Link className={buttonClasses({ variant: "secondary" })} to={tenantPath("events")}>Back to events</Link>}
      />,
    );
  }
  if (submit.data) {
    return shell(
      <Card padding="lg" className="text-center">
        <h1 className="text-h2 text-ink">Thank you</h1>
        <p className="mt-2 text-body-ui text-ink-secondary">{submit.data.thank_you_text || "Your response was recorded."}</p>
        {submit.data.certificate ? <p className="mt-3 text-body-ui text-ink">Your certificate is being prepared. Download it from Member activity.</p> : null}
        <Link className={buttonClasses({ variant: "primary", className: "mt-6" })} to={tenantPath("member")}>Open member area</Link>
      </Card>,
    );
  }

  const data = form.data;
  return shell(
    <>
      <PageHeader
        kicker={data.event.title}
        title={data.survey.title}
        description={data.mode === "anonymous" ? "No account or response identifier is stored with this response." : "Certificates are available only to members recorded as attended."}
      />
      {data.requires_auth && !restored ? (
        <Callout
          className="mt-6"
          tone="info"
          title="Sign in first"
          action={<Link className={buttonClasses({ variant: "primary", size: "sm" })} to={tenantPath("member")}>Member sign in</Link>}
        >
          Sign in through the member area before submitting certificate feedback.
        </Callout>
      ) : null}
      <Card as="section" className="mt-6">
        <form
          className="grid gap-5"
          onSubmit={(event) => { event.preventDefault(); const next = validateCustomAnswers(data.survey.questions, answers); setErrors(next); if (!Object.keys(next).length) submit.mutate(); }}
        >
          <CustomFormFields schema={data.survey.questions} answers={answers} onChange={setAnswers} errors={{ ...errors, ...customAnswerErrors(apiErrors) }} yesNoAsCheckbox />
          {data.requires_auth ? (
            <Field label="Registration email" helperText="The email you registered for this event with.">
              <Input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
            </Field>
          ) : null}
          {submit.error ? <ErrorText message={submit.error.message} /> : null}
          <Button variant="primary" type="submit" className="justify-self-start" disabled={data.requires_auth && !restored} loading={submit.isPending} loadingLabel="Submitting…">
            Submit feedback
          </Button>
        </form>
      </Card>
    </>,
  );
}

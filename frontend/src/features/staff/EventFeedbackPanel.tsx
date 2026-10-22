import { useEffect, useState } from "react";

import { Button, ErrorText, Field, Input, SectionHeading, Skeleton, StatTile, StatusChip, SwitchRow, Textarea, useToast } from "../../components/ui";
import { CustomFormBuilder } from "../forms/CustomFormBuilder";
import type { CustomFormQuestion } from "../forms/customFormTypes";
import {
  useCloseFeedbackSurvey,
  useConfigureFeedbackSurvey,
  useEventFeedbackSurvey,
  useOpenFeedbackSurvey,
} from "./eventFeedbackApi";
import { EventFeedbackResponses } from "./EventFeedbackResponses";
import { eventErrorText } from "./eventUi";

const FEEDBACK_TYPES = [
  "short_text", "paragraph", "number", "single_choice", "multi_choice", "dropdown", "yes_no",
] as const;

export function EventFeedbackPanel({ eventId, makerspaceId }: { eventId: number; makerspaceId: number }) {
  const surveyQuery = useEventFeedbackSurvey(eventId);
  const survey = surveyQuery.data?.survey;
  const [title, setTitle] = useState("");
  const [thankYou, setThankYou] = useState("");
  const [questions, setQuestions] = useState<CustomFormQuestion[]>([]);
  const [certificateEnabled, setCertificateEnabled] = useState(false);
  const configure = useConfigureFeedbackSurvey(eventId, makerspaceId);
  const open = useOpenFeedbackSurvey(eventId, makerspaceId);
  const close = useCloseFeedbackSurvey(eventId, makerspaceId);
  const { showToast } = useToast();

  useEffect(() => {
    if (!survey) return;
    setTitle(survey.title);
    setThankYou(survey.thank_you_text);
    setQuestions(survey.questions);
    setCertificateEnabled(survey.certificate_enabled);
  }, [survey?.id, survey?.is_open, survey?.answered_question_ids.join("|")]);

  const error = configure.error || open.error || close.error;
  const pending = configure.isPending || open.isPending || close.isPending;

  const saved = (message: string) => ({
    onSuccess: () => showToast(message, { tone: "success" }),
    onError: (cause: unknown) => showToast(eventErrorText(cause), { tone: "error" }),
  });

  return (
    <section className="grid gap-4 border-t border-line pt-5" aria-labelledby="feedback-title">
      <SectionHeading
        as="h3"
        title={<span id="feedback-title">Post-event feedback</span>}
        description="Answered questions stay fixed; questions nobody has answered stay editable."
        action={survey ? <StatusChip tone={survey.is_open ? "success" : "neutral"} size="sm">{survey.is_open ? "Open" : "Closed"}</StatusChip> : null}
      />
      {survey ? (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-3">
          <StatTile label="Responses" value={survey.response_count ?? 0} />
          <StatTile label="Questions" value={survey.questions.length} />
          <StatTile label="Certificates" value={survey.certificate_enabled ? "On" : "Off"} />
        </div>
      ) : null}
      {surveyQuery.isLoading ? <Skeleton className="h-32 w-full" /> : null}
      {surveyQuery.error ? <ErrorText message={eventErrorText(surveyQuery.error)} /> : null}
      {!surveyQuery.isLoading ? (
        <form className="grid gap-4" onSubmit={(event) => {
          event.preventDefault();
          configure.mutate({ title, thank_you_text: thankYou, questions, certificate_enabled: certificateEnabled }, saved("Survey saved"));
        }}>
          <Field label="Survey title">
            <Input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} />
          </Field>
          <Field label="Thank-you message" optional>
            <Textarea rows={3} maxLength={2000} value={thankYou} onChange={(event) => setThankYou(event.target.value)} />
          </Field>
          <SwitchRow
            label="Issue attendance certificates"
            description="Only attended members can answer, and each one gets a certificate."
            checked={certificateEnabled}
            onCheckedChange={setCertificateEnabled}
          />
          <CustomFormBuilder value={questions} onChange={(value) => setQuestions(value ?? [])} allowedTypes={FEEDBACK_TYPES} lockedQuestionIds={survey?.answered_question_ids} legend="Feedback questions" emptyMessage="Add at least one question before opening the survey." />
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" type="submit" disabled={pending} loading={configure.isPending} loadingLabel="Saving…">Save survey</Button>
            {survey && !survey.is_open ? <Button variant="success" disabled={pending} loading={open.isPending} onClick={() => open.mutate(undefined, saved("Responses open"))}>Open responses</Button> : null}
            {survey?.is_open ? <Button variant="danger" disabled={pending} loading={close.isPending} onClick={() => close.mutate(undefined, saved("Responses closed"))}>Close responses</Button> : null}
          </div>
        </form>
      ) : null}
      {error ? <ErrorText message={eventErrorText(error)} /> : null}
      {survey ? <EventFeedbackResponses eventId={eventId} makerspaceId={makerspaceId} responseCount={survey.response_count ?? 0} /> : null}
    </section>
  );
}

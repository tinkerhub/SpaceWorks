import { useId } from "react";
import { AlertCircle } from "lucide-react";

import { Dropdown, Field, Input, Textarea } from "../../components/ui";
import type { CustomAnswers, CustomFormQuestion, CustomFormSchema } from "./customFormTypes";

// Native radios and checkboxes keep `required` and form semantics; this styles them to
// the 20px control size in the brand colour.
const choiceInput = "size-5 shrink-0 cursor-pointer accent-[rgb(var(--color-accent-ink))] disabled:cursor-not-allowed";
const choiceRow = "flex min-h-11 min-w-0 cursor-pointer items-center gap-3 text-body-ui text-ink [overflow-wrap:anywhere]";

export function CustomFormFields({ schema, answers, onChange, errors = {}, disabled = false, yesNoAsCheckbox = false }: {
  schema: CustomFormSchema;
  answers: CustomAnswers;
  onChange: (answers: CustomAnswers) => void;
  errors?: Record<string, string>;
  disabled?: boolean;
  yesNoAsCheckbox?: boolean;
}) {
  const prefix = useId();
  if (!schema?.length) return null;

  const setAnswer = (id: string, value: CustomAnswers[string]) => onChange({ ...answers, [id]: value });
  return (
    <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5" disabled={disabled}>
      <legend className="mb-1 text-title text-ink">Additional questions</legend>
      {schema.map((question) => (
        <QuestionField
          key={question.id}
          question={question}
          inputId={prefix + "-" + question.id}
          value={answers[question.id]}
          error={errors[question.id]}
          yesNoAsCheckbox={yesNoAsCheckbox}
          onChange={(value) => setAnswer(question.id, value)}
        />
      ))}
    </fieldset>
  );
}

function Message({ id, error }: { id: string; error?: string }) {
  if (!error) return null;
  return (
    <span id={id} className="flex items-start gap-1.5 text-caption text-danger-fg">
      <AlertCircle aria-hidden="true" className="mt-px size-4 shrink-0" />
      <span className="min-w-0">{error}</span>
    </span>
  );
}

function GroupLabel({ question }: { question: CustomFormQuestion }) {
  return (
    <span className="text-label text-ink [overflow-wrap:anywhere]">
      {question.label}
      {question.required ? null : <span className="ml-1.5 font-normal text-ink-muted">Optional</span>}
    </span>
  );
}

function QuestionField({ question, inputId, value, error, yesNoAsCheckbox, onChange }: {
  question: CustomFormQuestion;
  inputId: string;
  value: CustomAnswers[string];
  error?: string;
  yesNoAsCheckbox: boolean;
  onChange: (value: CustomAnswers[string]) => void;
}) {
  const errorId = inputId + "-error";
  const fieldProps = { label: question.label, optional: !question.required, error, id: inputId };

  if (question.type === "yes_no" && yesNoAsCheckbox) {
    return (
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1">
        <label className={choiceRow}>
          <input id={inputId} className={choiceInput} type="checkbox" checked={value === true} required={question.required} aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} onChange={(event) => onChange(event.target.checked)} />
          <GroupLabel question={question} />
        </label>
        <Message id={errorId} error={error} />
      </div>
    );
  }

  if (question.type === "paragraph") {
    return (
      <Field {...fieldProps} required={question.required}>
        <Textarea maxLength={5000} value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)} />
      </Field>
    );
  }
  if (question.type === "dropdown") {
    return (
      <Field {...fieldProps} required={question.required}>
        <Dropdown value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)}>
          <option value="">Select an option</option>
          {question.options.map((option) => <option key={option} value={option}>{option}</option>)}
        </Dropdown>
      </Field>
    );
  }
  if (question.type === "single_choice" || question.type === "yes_no") {
    const choices: [string, string | boolean][] = question.type === "yes_no"
      ? [["Yes", true], ["No", false]]
      : question.options.map((option) => [option, option]);
    return (
      <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5" aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined}>
        <legend className="mb-1.5 max-w-full"><GroupLabel question={question} /></legend>
        <div className="flex flex-wrap gap-x-6">
          {choices.map(([text, answer]) => (
            <label className={choiceRow} key={text}>
              <input className={choiceInput} type="radio" name={inputId} value={text} checked={value === answer} required={question.required} onChange={() => onChange(answer)} />
              {text}
            </label>
          ))}
        </div>
        <Message id={errorId} error={error} />
      </fieldset>
    );
  }
  if (question.type === "multi_choice") {
    const selected = Array.isArray(value) ? value : [];
    return (
      <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5" aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined}>
        <legend className="mb-1.5 max-w-full"><GroupLabel question={question} /></legend>
        <div className="grid gap-x-6 sm:grid-cols-2">
          {question.options.map((option) => (
            <label className={choiceRow} key={option}>
              <input className={choiceInput} type="checkbox" checked={selected.includes(option)} onChange={(event) => onChange(event.target.checked ? [...selected, option] : selected.filter((item) => item !== option))} />
              {option}
            </label>
          ))}
        </div>
        <Message id={errorId} error={error} />
      </fieldset>
    );
  }
  const type = question.type === "number" ? "number" : question.type === "date" ? "date" : "text";
  return (
    <Field {...fieldProps} required={question.required}>
      <Input type={type} maxLength={question.type === "short_text" ? 500 : undefined} value={typeof value === "string" || typeof value === "number" ? value : ""} onChange={(event) => onChange(event.target.value)} />
    </Field>
  );
}

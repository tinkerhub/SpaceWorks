import { useState, type ChangeEvent } from "react";

import { ArrowDown, ArrowUp, Plus } from "lucide-react";

import { Button, CheckboxField, ConfirmDialog, Dropdown, Field, IconButton, Input } from "../../components/ui";

import {
  CHOICE_QUESTION_TYPES,
  CUSTOM_QUESTION_TYPES,
  QUESTION_TYPE_LABELS,
  type CustomFormQuestion,
  type CustomFormSchema,
  type CustomQuestionType,
} from "./customFormTypes";

function questionId() {
  return "q_" + crypto.randomUUID().replace(/-/g, "_");
}

function newQuestion(): CustomFormQuestion {
  return { id: questionId(), label: "", type: "short_text", options: [], required: false };
}

export function CustomFormBuilder({
  value,
  onChange,
  disabled = false,
  allowedTypes = CUSTOM_QUESTION_TYPES,
  lockedQuestionIds = [],
  legend = "Custom questions",
  emptyMessage = "No custom questions. The standard contact fields will still be collected.",
}: {
  value: CustomFormSchema;
  onChange: (schema: CustomFormSchema) => void;
  disabled?: boolean;
  allowedTypes?: readonly CustomQuestionType[];
  lockedQuestionIds?: readonly string[];
  legend?: string;
  emptyMessage?: string;
}) {
  const questions = value ?? [];
  const replace = (index: number, question: CustomFormQuestion) => {
    onChange(questions.map((item, itemIndex) => itemIndex === index ? question : item));
  };
  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= questions.length) return;
    const next = [...questions];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <fieldset className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3" disabled={disabled}>
      <div>
        <legend className="text-title text-ink">{legend}</legend>
        <p className="mt-1 text-caption text-ink-muted">Answers are visible only to authorized staff.</p>
      </div>
      {questions.map((question, index) => (
        <QuestionEditor
          key={question.id}
          question={question}
          index={index}
          count={questions.length}
          allowedTypes={allowedTypes}
          locked={lockedQuestionIds.includes(question.id)}
          onChange={(next) => replace(index, next)}
          onMove={(direction) => move(index, direction)}
          onRemove={() => onChange(questions.filter((item) => item.id !== question.id))}
        />
      ))}
      {!questions.length ? (
        <p className="rounded-lg border-[1.5px] border-dashed border-line-strong bg-canvas px-4 py-5 text-center text-body-ui text-ink-muted">
          {emptyMessage}
        </p>
      ) : null}
      <Button className="w-fit" size="sm" startIcon={<Plus />} disabled={questions.length >= 50} onClick={() => onChange([...questions, newQuestion()])}>
        Add question
      </Button>
    </fieldset>
  );
}

function QuestionEditor({ question, index, count, allowedTypes, locked, onChange, onMove, onRemove }: {
  question: CustomFormQuestion;
  index: number;
  count: number;
  allowedTypes: readonly CustomQuestionType[];
  locked: boolean;
  onChange: (question: CustomFormQuestion) => void;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
}) {
  const choice = CHOICE_QUESTION_TYPES.has(question.type);
  const [pendingType, setPendingType] = useState<CustomQuestionType | null>(null);
  const applyType = (type: CustomQuestionType) => onChange({
    ...question,
    type,
    options: CHOICE_QUESTION_TYPES.has(type)
      ? (question.options.length ? question.options : [""])
      : [],
  });
  const changeType = (event: ChangeEvent<HTMLSelectElement>) => {
    const type = event.target.value as CustomQuestionType;
    if (choice && !CHOICE_QUESTION_TYPES.has(type) && question.options.length > 0) {
      setPendingType(type);
      return;
    }
    applyType(type);
  };

  return (
    <div className="@container min-w-0 rounded-lg border border-line bg-canvas p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-label text-ink">Question <span className="tabular-nums">{index + 1}</span></span>
        <div className="ml-auto flex min-w-0 flex-wrap items-center gap-1">
          <IconButton label={"Move question " + (index + 1) + " up"} variant="quiet" size="sm" disabled={index === 0} onClick={() => onMove(-1)}><ArrowUp /></IconButton>
          <IconButton label={"Move question " + (index + 1) + " down"} variant="quiet" size="sm" disabled={index === count - 1} onClick={() => onMove(1)}><ArrowDown /></IconButton>
          <Button variant="danger-quiet" size="sm" disabled={locked} onClick={onRemove}>Remove</Button>
        </div>
      </div>
      <div className="grid min-w-0 gap-3 @min-[28rem]:grid-cols-[minmax(0,1fr)_200px]">
        <Field label="Label">
          <Input required disabled={locked} maxLength={200} value={question.label} onChange={(event) => onChange({ ...question, label: event.target.value })} />
        </Field>
        <Field label="Answer type">
          <Dropdown disabled={locked} value={question.type} onChange={changeType}>
            {allowedTypes.map((type) => <option key={type} value={type}>{QUESTION_TYPE_LABELS[type]}</option>)}
          </Dropdown>
        </Field>
      </div>
      <CheckboxField
        className="mt-3"
        label="Required question"
        disabled={locked}
        checked={question.required}
        onCheckedChange={(checked) => onChange({ ...question, required: checked === true })}
      />
      {choice ? <OptionsEditor question={question} disabled={locked} onChange={onChange} /> : null}
      <ConfirmDialog
        open={pendingType !== null}
        title="Change answer type?"
        message="Changing this type will remove its choices. Continue?"
        confirmLabel="Change type"
        tone="danger"
        onConfirm={() => {
          if (pendingType !== null) applyType(pendingType);
          setPendingType(null);
        }}
        onCancel={() => setPendingType(null)}
      />
    </div>
  );
}

function OptionsEditor({ question, disabled, onChange }: {
  question: CustomFormQuestion;
  disabled: boolean;
  onChange: (question: CustomFormQuestion) => void;
}) {
  return (
    <div className="mt-4 grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2">
      <h3 className="text-label text-ink">Choices</h3>
      {question.options.map((option, index) => (
        <div className="flex min-w-0 items-center gap-2" key={question.id + "-option-" + index}>
          <Input className="min-w-0 flex-1" aria-label={"Choice " + (index + 1)} required disabled={disabled} maxLength={200} value={option} onChange={(event) => onChange({ ...question, options: question.options.map((item, itemIndex) => itemIndex === index ? event.target.value : item) })} />
          <Button variant="danger-quiet" size="sm" disabled={disabled || question.options.length === 1} onClick={() => onChange({ ...question, options: question.options.filter((_, itemIndex) => itemIndex !== index) })}>Remove</Button>
        </div>
      ))}
      <Button className="w-fit" variant="quiet" size="sm" startIcon={<Plus />} disabled={disabled || question.options.length >= 50} onClick={() => onChange({ ...question, options: [...question.options, ""] })}>Add choice</Button>
    </div>
  );
}

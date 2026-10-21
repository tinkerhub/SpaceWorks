import type { CustomAnswerSnapshot, CustomAnswerValue } from "./customFormTypes";

function displayValue(value: CustomAnswerValue) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

export function CustomAnswersView({ snapshot }: { snapshot: CustomAnswerSnapshot | null | undefined }) {
  if (!snapshot?.answers.length) {
    return <p className="text-body-ui text-ink-muted">No custom answers were submitted.</p>;
  }

  return (
    <dl className="divide-y divide-line rounded-lg border border-line bg-canvas">
      {snapshot.answers.map((answer) => (
        <div key={answer.id} className="px-4 py-3">
          <dt className="text-caption text-ink-muted">{answer.label}</dt>
          <dd className="mt-0.5 whitespace-pre-wrap break-words text-body-ui text-ink">{displayValue(answer.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

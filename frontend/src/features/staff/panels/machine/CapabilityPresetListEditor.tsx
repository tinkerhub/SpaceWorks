import { useId, useState } from "react";
import { X } from "lucide-react";

import { Button, Field, IconButton, Input } from "../../../../components/ui";

type Props = {
  label: string;
  singularLabel: string;
  values: string[];
  disabled?: boolean;
  onChange: (values: string[]) => void;
};

export function CapabilityPresetListEditor({ label, singularLabel, values, disabled = false, onChange }: Props) {
  const errorId = useId();
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const noun = singularLabel.toLocaleLowerCase();

  const addValue = () => {
    const value = draft.trim();
    if (!value) {
      setError(`${singularLabel} cannot be blank.`);
      return;
    }
    if (values.some((existing) => existing.toLocaleLowerCase() === value.toLocaleLowerCase())) {
      setError(`${singularLabel} already exists.`);
      return;
    }
    onChange([...values, value]);
    setDraft("");
    setError("");
  };

  return (
    <fieldset className="grid min-w-0 gap-3 rounded-lg border border-line p-4" disabled={disabled}>
      <legend className="px-1 text-label text-ink">{label}</legend>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
        <Field label={`New ${noun}`}>
          <Input
            value={draft}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            onChange={(event) => { setDraft(event.target.value); setError(""); }}
            onKeyDown={(event) => {
              // Enter adds the preset instead of submitting the surrounding type form.
              if (event.key === "Enter") { event.preventDefault(); addValue(); }
            }}
          />
        </Field>
        <Button onClick={addValue}>Add {noun}</Button>
      </div>
      {error ? <p id={errorId} className="text-caption text-danger-fg" role="alert">{error}</p> : null}
      {values.length ? (
        <ul className="flex flex-wrap gap-2" aria-label={`${label} presets`}>
          {values.map((value) => (
            <li key={value} className="inline-flex items-center gap-1 rounded-full bg-fill py-0.5 pl-3 pr-0.5 text-sm font-semibold text-ink-secondary">
              <span>{value}</span>
              <IconButton
                label={`Remove ${noun} ${value}`}
                variant="quiet"
                size="sm"
                onClick={() => onChange(values.filter((existing) => existing !== value))}
              >
                <X />
              </IconButton>
            </li>
          ))}
        </ul>
      ) : <p className="text-caption text-ink-muted">No presets. The consumable form will use free text.</p>}
    </fieldset>
  );
}

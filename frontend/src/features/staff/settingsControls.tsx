import { useId, type ReactNode } from "react";

import { StatusChip, Switch } from "../../components/ui";

/**
 * The control column of an instant on/off SettingsRow: a switch with its visible label,
 * the current state as a word, and the last save error underneath. Shared by the
 * Settings cards so every toggle reads and behaves the same way.
 */
export function SettingSwitch({ label, checked, disabled, onCheckedChange, error, onLabel = "On", offLabel = "Off", warnWhenOn = false }: {
  label: string;
  checked: boolean;
  disabled?: boolean;
  onCheckedChange: (checked: boolean) => void;
  error?: ReactNode;
  onLabel?: string;
  offLabel?: string;
  /** Marks "on" as the riskier state (e.g. publishing names), so it reads as a warning. */
  warnWhenOn?: boolean;
}) {
  const id = useId();
  return (
    <div className="grid min-w-0 gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} />
        <label htmlFor={id} className="cursor-pointer text-body-ui text-ink">{label}</label>
        <StatusChip tone={checked ? (warnWhenOn ? "warning" : "success") : "neutral"} size="sm">
          {checked ? onLabel : offLabel}
        </StatusChip>
      </div>
      {error ? <p role="alert" className="text-caption text-danger-fg">{error}</p> : null}
    </div>
  );
}

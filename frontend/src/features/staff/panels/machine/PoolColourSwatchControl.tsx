import { useId } from "react";

import { Button } from "../../../../components/ui";

type Props = {
  value: string;
  onChange: (value: string) => void;
  legend?: string;
};

function channelHex(value: number) {
  return Math.max(0, Math.min(255, value)).toString(16).padStart(2, "0");
}

function rgbFromHex(value: string) {
  const hex = /^#[0-9a-f]{6}$/i.test(value) ? value : "#000000";
  return {
    red: Number.parseInt(hex.slice(1, 3), 16),
    green: Number.parseInt(hex.slice(3, 5), 16),
    blue: Number.parseInt(hex.slice(5, 7), 16),
  };
}

export function PoolColourSwatchControl({ value, onChange, legend = "Display swatch (optional)" }: Props) {
  const id = useId();
  const activeHex = /^#[0-9a-f]{6}$/i.test(value) ? value.toLowerCase() : "";
  const pickerHex = activeHex || "#000000";
  const rgb = rgbFromHex(pickerHex);
  const updateChannel = (channel: keyof typeof rgb, next: number) => {
    const updated = { ...rgb, [channel]: next };
    onChange(`#${channelHex(updated.red)}${channelHex(updated.green)}${channelHex(updated.blue)}`);
  };

  return (
    <fieldset className="grid min-w-0 gap-3 rounded-lg border border-line p-4">
      <legend className="px-1 text-label text-ink">{legend}</legend>
      <div className="flex flex-wrap items-end gap-3">
        <label className="grid gap-1.5 text-label text-ink" htmlFor={`${id}-picker`}>
          Colour picker
          <input
            className="min-h-11 w-20 cursor-pointer rounded-md border border-line-strong bg-canvas p-1 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            id={`${id}-picker`}
            type="color"
            value={pickerHex}
            onChange={(event) => onChange(event.target.value.toLowerCase())}
          />
        </label>
        <output className="flex min-h-11 items-center gap-2 text-body-ui text-ink-secondary" htmlFor={`${id}-picker`}>
          Display hex: <span className="font-mono text-ink">{activeHex || "Not set"}</span>
        </output>
        {activeHex ? (
          <Button size="sm" variant="quiet" onClick={() => onChange("")}>Clear display colour</Button>
        ) : null}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {(["red", "green", "blue"] as const).map((channel) => (
          <label className="grid gap-1 text-caption font-semibold text-ink-secondary" htmlFor={`${id}-${channel}`} key={channel}>
            {channel.slice(0, 1).toUpperCase()}{channel.slice(1)} ({rgb[channel]})
            <input
              aria-label={`${channel} channel`}
              className="min-h-11 w-full cursor-pointer accent-accent-ink focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
              id={`${id}-${channel}`}
              max="255"
              min="0"
              type="range"
              value={rgb[channel]}
              onChange={(event) => updateChannel(channel, Number(event.target.value))}
            />
          </label>
        ))}
      </div>
    </fieldset>
  );
}

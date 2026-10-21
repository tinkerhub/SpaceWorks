import type { PropsWithChildren } from "react";

import { Chip, type ChipTone } from "./Chip";

// `accent` and `secondary` exist so a caller that distributes the palette across a
// repeating set (categories, machine types, sections) has the brand pastels here rather
// than hand-rolling a span. Status tones use the soft bg + strong fg pairs.
type BadgeTone = "success" | "warn" | "danger" | "accent" | "secondary" | "neutral";

type BadgeProps = PropsWithChildren<{
  tone: BadgeTone;
  className?: string;
}>;

const toneMap: Record<BadgeTone, ChipTone> = {
  success: "success",
  warn: "warning",
  danger: "danger",
  accent: "accent",
  secondary: "secondary",
  neutral: "neutral",
};

/** Older name for `Chip`; kept so existing call sites keep their API. */
export function Badge({ tone, className, children }: BadgeProps) {
  return (
    <Chip tone={toneMap[tone]} size="sm" className={className}>
      {children}
    </Chip>
  );
}

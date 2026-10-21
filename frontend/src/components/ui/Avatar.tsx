import { useState } from "react";

import { cn } from "../../lib/cn";

/** 1–2 letter initials: first and last word, or the first two letters of one word. */
export function initials(name: string | null | undefined, fallback = "?") {
  const words = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return fallback;
  const letters = words.length === 1 ? words[0].slice(0, 2) : `${words[0][0]}${words[words.length - 1][0]}`;
  return letters.toUpperCase();
}

const avatarSizes = {
  xs: "size-6 text-[10px]",
  sm: "size-8 text-xs",
  md: "size-10 text-sm",
  lg: "size-14 text-lg",
  xl: "size-20 text-2xl",
} as const;

export type AvatarSize = keyof typeof avatarSizes;
export type AvatarTone = "neutral" | "accent" | "secondary" | "success" | "warning";

const toneClasses: Record<AvatarTone, string> = {
  neutral: "bg-emphasis text-ink-secondary",
  accent: "bg-accent text-on-accent",
  secondary: "bg-secondary text-on-secondary",
  success: "bg-success-bg text-success-fg",
  warning: "bg-warning-bg text-warning-fg",
};

type AvatarProps = {
  name?: string | null;
  src?: string | null;
  size?: AvatarSize;
  tone?: AvatarTone;
  className?: string;
  /** Skip the screen-reader name when the same name is already visible beside the avatar. */
  decorative?: boolean;
};

/** Round photo, falling back to initials if there is none or it fails to load. */
export function Avatar({ name, src, size = "md", tone = "neutral", className, decorative = false }: AvatarProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = Boolean(src) && failedSrc !== src;
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full font-bold",
        avatarSizes[size],
        toneClasses[tone],
        className,
      )}
    >
      {showImage ? (
        <img src={src ?? undefined} alt="" className="size-full object-cover" onError={() => setFailedSrc(src ?? null)} />
      ) : (
        <span aria-hidden="true">{initials(name)}</span>
      )}
      {name && !decorative ? <span className="sr-only">{name}</span> : null}
    </span>
  );
}

import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * tailwind-merge only knows Tailwind's default scale. Without this, `text-h1` would be
 * read as a text COLOUR (so `cn("text-h1", "text-ink")` dropped the size) and
 * `shadow-float` as a shadow colour that never replaces `shadow-none`.
 */
const merge = extendTailwindMerge({
  extend: {
    theme: {
      text: [
        "display-xl", "display-l", "display-m", "h1", "h2", "h3", "h4", "title",
        "body-l", "body", "body-ui", "label", "caption", "overline", "mono",
      ],
      shadow: [
        "raised", "float", "segment", "soft", "soft-lg", "elev-1", "elev-2", "elev-3",
        "brutal", "brutal-sm", "brutal-lg",
      ],
      ease: ["standard", "ease-out-soft"],
    },
  },
});

/** Join class names (clsx) and let later Tailwind classes win conflicts (tailwind-merge). */
export function cn(...inputs: ClassValue[]) {
  return merge(clsx(inputs));
}

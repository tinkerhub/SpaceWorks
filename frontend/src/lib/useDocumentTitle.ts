import { useEffect } from "react";

const SITE_NAME = "Space Works";

/** "Inventory · Forge · Space Works": the page first, then its context, without repeats. */
export function documentTitle(...parts: (string | null | undefined)[]) {
  const unique = [...new Set([...parts, SITE_NAME].map((part) => part?.trim()).filter(Boolean))];
  return unique.join(" · ");
}

/** Sets `document.title` while mounted and restores the previous title afterwards. */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (!title) return undefined;
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);
}

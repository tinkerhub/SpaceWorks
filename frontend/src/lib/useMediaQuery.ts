import { useSyncExternalStore } from "react";

/**
 * Whether a CSS media query matches, kept in sync as the window changes. For layouts that
 * must render ONE structure per breakpoint (a table vs a card list), where hiding the other
 * with CSS would leave duplicate controls in the DOM. False where matchMedia is missing.
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const list = typeof window !== "undefined" ? window.matchMedia?.(query) : undefined;
      list?.addEventListener("change", onChange);
      return () => list?.removeEventListener("change", onChange);
    },
    () => (typeof window !== "undefined" ? Boolean(window.matchMedia?.(query).matches) : false),
    () => false,
  );
}

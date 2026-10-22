import { useCallback, useState } from "react";

import { readStorage, writeStorage } from "../../../lib/safeStorage";

export const SIDEBAR_COLLAPSED_KEY = "spaceworks.staff.sidebarCollapsed";

/**
 * Whether the desktop sidebar is folded to its icon rail. Remembered per browser;
 * `safeStorage` swallows the errors a private window or blocked storage throws, so the
 * sidebar simply opens expanded there.
 */
export function useSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState(() => readStorage(SIDEBAR_COLLAPSED_KEY) === "1");
  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      writeStorage(SIDEBAR_COLLAPSED_KEY, next ? "1" : "0");
      return next;
    });
  }, []);
  return { collapsed, toggle };
}

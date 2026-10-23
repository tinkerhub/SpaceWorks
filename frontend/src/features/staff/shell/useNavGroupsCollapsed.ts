import { useCallback, useState } from "react";

import { readStorage, writeStorage } from "../../../lib/safeStorage";

export const NAV_GROUPS_COLLAPSED_KEY = "spaceworks.staff.navGroupsCollapsed";

function readCollapsed(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(readStorage(NAV_GROUPS_COLLAPSED_KEY, "[]") || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((label): label is string => typeof label === "string") : []);
  } catch {
    return new Set();
  }
}

/**
 * Which sidebar groups (Inventory, Admin, ...) are folded shut. Remembered per browser by
 * group label; everything starts open, and storage errors simply leave every group open.
 */
export function useNavGroupsCollapsed() {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const setGroupOpen = useCallback((label: string, open: boolean) => {
    setCollapsed((current) => {
      if (open !== current.has(label)) return current;
      const next = new Set(current);
      if (open) next.delete(label);
      else next.add(label);
      writeStorage(NAV_GROUPS_COLLAPSED_KEY, JSON.stringify([...next]));
      return next;
    });
  }, []);
  return { collapsed, setGroupOpen };
}

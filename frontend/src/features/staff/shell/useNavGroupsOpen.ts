import { useCallback, useState } from "react";

import { readStorage, writeStorage } from "../../../lib/safeStorage";

// A new key rather than the old `navGroupsCollapsed` one: that stored the groups folded SHUT,
// and reading it under open-set semantics would open exactly what the operator had closed.
export const NAV_GROUPS_OPEN_KEY = "spaceworks.staff.navGroupsOpen";

function readOpen(): Set<string> {
  try {
    const parsed: unknown = JSON.parse(readStorage(NAV_GROUPS_OPEN_KEY, "[]") || "[]");
    return new Set(Array.isArray(parsed) ? parsed.filter((label): label is string => typeof label === "string") : []);
  } catch {
    return new Set();
  }
}

/**
 * Which sidebar groups (Inventory, Admin, ...) are unfolded. Remembered per browser by group
 * label; everything starts closed, and storage errors simply leave every group closed.
 */
export function useNavGroupsOpen() {
  const [open, setOpen] = useState(readOpen);
  const setGroupOpen = useCallback((label: string, next: boolean) => {
    setOpen((current) => {
      if (next === current.has(label)) return current;
      const updated = new Set(current);
      if (next) updated.add(label);
      else updated.delete(label);
      writeStorage(NAV_GROUPS_OPEN_KEY, JSON.stringify([...updated]));
      return updated;
    });
  }, []);
  return { open, setGroupOpen };
}

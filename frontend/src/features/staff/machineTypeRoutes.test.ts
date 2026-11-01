import { describe, expect, it } from "vitest";
import { machineTypeQueueSegment, machineTypeRoute } from "./machineTypeRoutes";
import { keptStaffSubPath, staffPathState, staffTabPath } from "./staffTabs";

describe("equipment and request deep links", () => {
  it.each(["/admin", "/m/forge/admin"])("preserves equipment and queue through %s canonicalization", (base) => {
    for (const suffix of ["12-laser", "12-laser/queue"]) {
      const pathname = `${base}/machines/${suffix}`;
      const state = staffPathState(pathname, false);
      expect(state.tab).toBe("machines");
      expect(staffTabPath("machines", false, state.makerspaceSlug, false,
        keptStaffSubPath(state.tab, "machines", state.subPath))).toBe(pathname);
      expect(machineTypeRoute(state.subPath)).toEqual({ typeId: 12, queue: suffix.endsWith("/queue") });
    }
  });

  it("keeps a queue when switching to the single-tenant canonical path", () => {
    const state = staffPathState("/m/forge/admin/machines/12-laser/queue", false);
    expect(staffTabPath("machines", false, "forge", true, keptStaffSubPath(state.tab, "machines", state.subPath)))
      .toBe("/admin/machines/12-laser/queue");
    expect(keptStaffSubPath("machines", "dashboard", state.subPath)).toBe("");
  });

  it("distinguishes IDs sharing a slug and rejects malformed queue selections", () => {
    expect(machineTypeQueueSegment({ id: 2, slug: "3d_printer" })).toBe("2-3d_printer/queue");
    expect(machineTypeRoute("13-3d_printer/queue")).toEqual({ typeId: 13, queue: true });
    expect(machineTypeRoute("2-3d_printer/queue")).toEqual({ typeId: 2, queue: true });
    for (const segment of ["", "laser/queue", "0-laser/queue", "-3/queue"]) {
      expect(machineTypeRoute(segment)).toEqual({ typeId: null, queue: false });
    }
    expect(machineTypeRoute("12-laser/queue/unrecognised").queue).toBe(false);
  });
});

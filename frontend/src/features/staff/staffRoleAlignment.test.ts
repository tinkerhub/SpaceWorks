import { describe, expect, it } from "vitest";

import { getStaffAccess } from "./staffAccess";

// Each tab must appear for exactly the actors its backend endpoints serve; a tab that renders
// and then 403s/404s on every request is the bug these pin. Actions are given EXPANDED, the
// way /auth/me sends them (MANAGE_MACHINES implies MANAGE_PRINTING and COLLECT_SERVICE_REQUEST).
const tabsFor = (actions: string[], isSuperadmin = false, isMachineOnly = false) =>
  getStaffAccess(actions, isSuperadmin, false, isMachineOnly).allowedTabs;

const MACHINE_MANAGER = ["manage_machines", "manage_printing", "collect_service_request"];
const FRONT_DESK = ["view_inventory", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence"];

describe("Notifications tab follows notifications.views._makerspace_for_manager", () => {
  it("is offered to view_inventory, manage_printing and manage_makerspace holders", () => {
    expect(tabsFor(["view_inventory"])).toContain("notifications");
    expect(tabsFor(["manage_printing"])).toContain("notifications");
    expect(tabsFor(["manage_makerspace"])).toContain("notifications");
    expect(tabsFor([], true)).toContain("notifications");
  });

  it("is withheld from roles the inbox refuses", () => {
    expect(tabsFor(["manage_events"])).not.toContain("notifications");
    expect(tabsFor(["manage_bookings"])).not.toContain("notifications");
    expect(tabsFor(FRONT_DESK)).not.toContain("notifications");
    expect(tabsFor(MACHINE_MANAGER, false, true)).not.toContain("notifications");
  });
});

describe("Reports tab follows the report catalog's VIEW_INVENTORY / VIEW_AUDIT scoping", () => {
  it("is offered to view_inventory or view_audit holders and superadmins", () => {
    expect(tabsFor(["view_inventory"])).toContain("reports");
    expect(tabsFor(["view_audit"])).toContain("reports");
    expect(tabsFor([], true)).toContain("reports");
  });

  it("is withheld from machine and printing roles, which would land on a 404", () => {
    expect(tabsFor(MACHINE_MANAGER)).not.toContain("reports");
    expect(tabsFor(["manage_printing"])).not.toContain("reports");
    expect(tabsFor(["manage_events"])).not.toContain("reports");
  });
});

describe("Machines tab follows machines.access.can_see_machines", () => {
  it("is offered to a manage_printing-only role (the 3D printer type's managing action)", () => {
    expect(tabsFor(["manage_printing"])).toContain("machines");
    expect(tabsFor(MACHINE_MANAGER)).toContain("machines");
  });

  it("is withheld from roles holding neither action", () => {
    expect(tabsFor(["view_inventory", "edit_inventory"])).not.toContain("machines");
  });
});

describe("request queue capabilities", () => {
  it("lets a handover role return loans without re-dating them", () => {
    const access = getStaffAccess(FRONT_DESK, false, false);
    expect(access.handoutOnly).toBe(true);
    expect(access.canReturnRequest).toBe(true);
    expect(access.canReviewRequests).toBe(false);
  });

  it("gives a reviewer every queue action", () => {
    const access = getStaffAccess(["view_inventory", "accept_request", "reject_request", "issue_request", "return_request"], false, false);
    expect(access.canReturnRequest).toBe(true);
    expect(access.canReviewRequests).toBe(true);
  });
});

describe("inventory edit capability", () => {
  it("separates viewing inventory from editing it", () => {
    expect(getStaffAccess(FRONT_DESK, false, false).canEditInventory).toBe(false);
    expect(getStaffAccess(["view_inventory", "edit_inventory"], false, false).canEditInventory).toBe(true);
  });
});

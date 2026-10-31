import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  authority, calicut, choose, kochi, leaves, membership, mountStaff, noPanel,
  panelIs, routeIs, saved, staff, stored, transport,
} from "../../test/staffSelectionHarness";

describe("staff workspace effective per-makerspace authority", () => {
  it.each([false, undefined])("global user with override flag %s keeps only explicit limited membership authority", async (flag) => {
    transport.spaces = [{ ...kochi, superadmin_access_enabled: flag }];
    transport.user = staff({ makerspaces: [membership(kochi)] });
    mountStaff("/m/kochi/admin/machines");
    await panelIs(kochi.id, "machines");
    expect(authority()).toMatchObject({ override: false, edit: false, machines: true, settings: false, configure: false });
    expect(screen.getAllByText("Laser operator").length).toBeGreaterThan(0);
    expect(screen.queryByText("Super Admin", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Settings" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Machines" })).toBeInTheDocument();
  });

  it("affirmative override grants full operational access to a global user without a membership", async () => {
    mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id, "settings");
    expect(authority()).toMatchObject({ override: true, edit: true, machines: true, settings: true, configure: true });
    expect(screen.getAllByText("Super Admin").length).toBeGreaterThan(0);
  });

  it("an explicit allowed inventory membership remains operable when global override is disabled", async () => {
    transport.spaces = [{ ...kochi, superadmin_access_enabled: false }];
    transport.user = staff({ makerspaces: [membership(kochi, ["view_inventory", "edit_inventory"])] });
    mountStaff("/m/kochi/admin/inventory");
    await panelIs(kochi.id, "inventory");
    expect(authority()).toMatchObject({ override: false, edit: true, machines: false, settings: false, configure: false });
  });

  it("no effective grants produce no operational leaf or default protected panel", async () => {
    transport.spaces = [{ ...kochi, superadmin_access_enabled: false, enabled_modules: [] }];
    transport.user = staff();
    mountStaff("/m/kochi/admin");
    await screen.findByRole("heading", { name: "No operational access" });
    noPanel();
    expect(leaves).toEqual([]);
    expect(screen.queryByRole("link", { name: "Dashboard" })).not.toBeInTheDocument();
  });

  it("choosing a target with narrower access replaces a forbidden settings tab with its allowed default", async () => {
    transport.spaces = [kochi, { ...calicut, superadmin_access_enabled: false }];
    transport.user = staff({ makerspaces: [membership(calicut)] });
    mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id, "settings");
    fireEvent.keyDown(screen.getByRole("button", { name: "global-admin, account menu" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Calicut" }));
    await panelIs(calicut.id, "dashboard");
    await routeIs("/m/calicut/admin/dashboard");
    expect(authority()).toMatchObject({ override: false, settings: false, machines: true });
  });
});

describe("staff chooser tenant and non-global selection rules", () => {
  it.each(["/admin/settings", "/m/calicut/admin/settings"])(
    "single-tenant restore fixes Kochi and hides every chooser even from route %s and a saved Calicut hint",
    async (path) => {
      window.__TENANT__ = { tenantToken: "KOCHI" };
      saved(calicut.id);
      mountStaff(path);
      await panelIs(kochi.id, "settings");
      await routeIs("/admin/settings");
      expect(leaves.every(({ id }) => id === kochi.id)).toBe(true);
      expect(screen.queryByRole("button", { name: "Switch makerspace" })).not.toBeInTheDocument();
      fireEvent.keyDown(screen.getByRole("button", { name: "global-admin, account menu" }), { key: "ArrowDown" });
      expect(screen.queryByRole("menuitem", { name: "Switch makerspace" })).not.toBeInTheDocument();
      expect(screen.queryByRole("menuitem", { name: "Calicut" })).not.toBeInTheDocument();
      expect(stored()).toBe(String(kochi.id));
    },
  );

  it("single-tenant missing fixed row fails closed instead of adopting another allowed space", async () => {
    window.__TENANT__ = { tenantToken: "KOCHI" };
    transport.spaces = [calicut];
    saved(calicut.id);
    mountStaff("/admin/settings");
    await screen.findByRole("heading", { name: "You do not have access to this makerspace." });
    noPanel();
    expect(leaves).toEqual([]);
    expect(screen.queryByRole("button", { name: /Calicut.*Operate/ })).not.toBeInTheDocument();
  });

  it("non-superadmin rejects a stored id absent from API rows and selects the allowed default", async () => {
    transport.spaces = [calicut];
    transport.user = staff({ role: "staff", is_superuser: false, makerspaces: [membership(calicut)] });
    saved(kochi.id);
    mountStaff("/admin/machines");
    await panelIs(calicut.id, "machines");
    await routeIs("/m/calicut/admin/machines");
    expect(stored()).toBe(String(calicut.id));
    expect(leaves.every(({ id }) => id === calicut.id)).toBe(true);
    expect(screen.queryByRole("button", { name: "Switch makerspace" })).not.toBeInTheDocument();
  });

  it("guest chooser preserves the guest-only route family after explicit choice", async () => {
    saved(kochi.id);
    mountStaff("/guest-admin", { guestOnly: true });
    await choose("Calicut");
    await panelIs(calicut.id);
    await routeIs("/guest-admin/dashboard");
    expect(stored()).toBe(String(calicut.id));
  });
});

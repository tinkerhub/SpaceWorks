import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { platformMounts } from "../../test/platformPanelMocks";
import {
  calicut, choose, deferred, json, kochi, listCalls, membership, mountStaff,
  navigateTo, noPanel, panelIs, platformStaff, routeIs, settle, staff, transport,
} from "../../test/staffSelectionHarness";

beforeEach(() => { platformMounts.length = 0; transport.user = platformStaff(); });

async function platformIsOpen() {
  expect(await screen.findByRole("region", { name: "Platform email leaf" })).toBeVisible();
  expect(await screen.findByRole("region", { name: "Platform social leaf" })).toBeVisible();
  noPanel();
}
function noGlobalControls() {
  expect(screen.queryByRole("region", { name: /Platform .* leaf/ })).not.toBeInTheDocument();
  expect(platformMounts).toEqual([]);
  expect(transport.calls.filter(({ path }) => path.startsWith("/admin/platform/"))).toEqual([]);
}

describe("global Platform route and makerspace discovery", () => {
  it.each(["pending", "empty", "error"])("opens before choosing a maker with a %s allowed list", async (state) => {
    const list = deferred<Response>();
    if (state === "pending") transport.routes.set("/admin/makerspaces", () => list.promise);
    if (state === "empty") transport.spaces = [];
    if (state === "error") transport.routes.set("/admin/makerspaces", () => json({}, 503));
    mountStaff("/admin/platform");
    await platformIsOpen();
    await routeIs("/admin/platform");
    expect(listCalls()).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Operate this makerspace/ })).not.toBeInTheDocument();
    if (state === "empty") expect(screen.getByText("No makerspaces available to this account from this site.")).toBeVisible();
    if (state === "error") expect(await screen.findByRole("button", { name: "Retry makerspaces" })).toBeVisible();
    if (state === "pending") {
      await settle(list, json([kochi]));
      expect(await screen.findByRole("button", { name: /Kochi.*Operate/ })).toBeVisible();
      expect(screen.queryByRole("button", { name: /Calicut.*Operate/ })).not.toBeInTheDocument();
    }
  });

  it("waits for verified identity before mounting global forms", async () => {
    const identity = deferred<Response>();
    transport.routes.set("/auth/me", () => identity.promise);
    mountStaff("/admin/platform");
    await waitFor(() => expect(transport.calls.some(({ path }) => path === "/auth/me")).toBe(true));
    noGlobalControls();
    await settle(identity, json(platformStaff()));
    await platformIsOpen();
  });

  it("offers the global link in the picker while the allowed list is unresolved", async () => {
    const list = deferred<Response>();
    transport.routes.set("/admin/makerspaces", () => list.promise);
    mountStaff("/admin");
    fireEvent.click(await screen.findByRole("link", { name: "Platform settings" }));
    await routeIs("/admin/platform");
    await platformIsOpen();
    await settle(list, json([]));
  });

  it("chooses an API-authorized narrower target's default without looping back to Platform", async () => {
    transport.spaces = [{ ...calicut, superadmin_access_enabled: false }];
    transport.user = platformStaff({ makerspaces: [membership(calicut)] });
    mountStaff("/admin/platform");
    await platformIsOpen();
    await choose("Calicut");
    await panelIs(calicut.id, "dashboard");
    await routeIs("/m/calicut/admin/dashboard");
    expect(screen.queryByRole("region", { name: "Platform email leaf" })).not.toBeInTheDocument();
  });

  it("canonicalizes a legacy scoped Platform URL without requiring that maker", async () => {
    transport.spaces = [];
    mountStaff("/m/unavailable/admin/platform");
    await routeIs("/admin/platform");
    await platformIsOpen();
  });
});

describe("global controls require current authoritative context", () => {
  it.each(["missing", "ordinary", "revoked", "makerspace", "locked"])("denies a %s session before any global leaf mounts", async (kind) => {
    if (kind === "missing") transport.user = staff();
    if (kind === "ordinary") transport.user = platformStaff({ role: "staff", is_superuser: false });
    if (kind === "revoked") transport.user = platformStaff({ staff_context: { ...platformStaff().staff_context!, can_manage_platform: false } });
    if (kind === "makerspace") transport.user = platformStaff({ staff_context: {
      ...platformStaff().staff_context!, scope_kind: "makerspace", makerspace_id: kochi.id, can_manage_platform: false,
    } });
    if (kind === "locked") window.__TENANT__ = { tenantToken: "KOCHI" };
    mountStaff("/admin/platform");
    await screen.findByRole("heading", { name: "Platform settings unavailable" });
    noGlobalControls();
    expect(screen.queryByRole("link", { name: "Platform settings" })).not.toBeInTheDocument();
  });

  it.each(["error", "revoked", "list-error"])("fences a stale global identity during refresh and handles %s independently", async (outcome) => {
    mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    const identity = deferred<Response>();
    transport.routes.set("/auth/me", () => identity.promise);
    if (outcome === "list-error") transport.routes.set("/admin/makerspaces", () => json({}, 503));
    fireEvent.click(screen.getByRole("button", { name: "Refresh identity and access" }));
    navigateTo("/admin/platform");
    await routeIs("/admin/platform");
    await waitFor(() => expect(transport.calls.filter(({ path }) => path === "/auth/me")).toHaveLength(2));
    noGlobalControls();
    noPanel();
    await settle(identity, outcome === "error" ? json({}, 503) : json(outcome === "revoked" ? staff() : platformStaff()));
    if (outcome === "list-error") {
      await platformIsOpen();
      await screen.findByRole("button", { name: "Retry makerspaces" });
      navigateTo("/m/kochi/admin/settings");
      await screen.findByRole("button", { name: "Retry makerspaces" });
      noPanel();
    } else {
      await screen.findByRole("heading", { name: outcome === "error" ? "Could not verify account access" : "Platform settings unavailable" });
      noGlobalControls();
      if (outcome === "error") {
        transport.routes.delete("/auth/me");
        fireEvent.click(screen.getByRole("button", { name: "Retry account access" }));
        await platformIsOpen();
      }
    }
  });
});

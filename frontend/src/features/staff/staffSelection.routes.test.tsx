import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  calicut, choose, deferred, json, kochi, leaves, listCalls, mountStaff,
  noPanel, panelIs, routeIs, saved, settle, stored, transport,
} from "../../test/staffSelectionHarness";

describe("staff chooser exact route authorization", () => {
  it("restores explicit Calicut settings despite a saved Kochi hint without ever mounting Kochi", async () => {
    saved(kochi.id);
    mountStaff("/m/calicut/admin/settings");
    await panelIs(calicut.id, "settings");
    await routeIs("/m/calicut/admin/settings");
    expect(stored()).toBe(String(calicut.id));
    expect(leaves.length).toBeGreaterThan(0);
    expect(leaves.every(({ id }) => id === calicut.id)).toBe(true);
  });

  it.each(["missing", "hidden", "archived", "cross-origin"])(
    "keeps an explicit %s Calicut URL unavailable when the allowed API list contains only Kochi",
    async () => {
      // The frontend cannot distinguish these server-side exclusion reasons. None
      // may cause a locally fabricated target or a fallback operational mount.
      transport.spaces = [kochi];
      saved(kochi.id);
      mountStaff("/m/calicut/admin/settings");
      await screen.findByRole("heading", { name: "Makerspace unavailable" });
      await routeIs("/m/calicut/admin/settings");
      noPanel();
      expect(leaves).toEqual([]);
      expect(screen.queryByRole("button", { name: /Calicut.*Operate/ })).not.toBeInTheDocument();
      await choose("Kochi");
      await panelIs(kochi.id, "settings");
      await routeIs("/m/kochi/admin/settings");
      expect(leaves.every(({ id }) => id === kochi.id)).toBe(true);
    },
  );

  it("mounts no protected panel while the allowed makerspace list is unresolved", async () => {
    const list = deferred<Response>();
    transport.routes.set("/admin/makerspaces", () => list.promise);
    mountStaff("/m/calicut/admin/settings");
    await waitFor(() => expect(listCalls()).toHaveLength(1));
    expect(screen.getAllByText("Checking makerspace access…").length).toBeGreaterThan(0);
    noPanel();
    expect(leaves).toEqual([]);
    await settle(list, json([kochi, calicut]));
    await panelIs(calicut.id, "settings");
  });

  it("fails closed on an allowed-list error and retries the exact explicit target", async () => {
    transport.routes.set("/admin/makerspaces", () => json({ detail: "Unavailable" }, 503));
    mountStaff("/m/calicut/admin/settings");
    await screen.findByText(/Could not check makerspace access\. Retry/);
    noPanel();
    expect(leaves).toEqual([]);
    await routeIs("/m/calicut/admin/settings");
    transport.routes.delete("/admin/makerspaces");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await panelIs(calicut.id, "settings");
    expect(listCalls()).toHaveLength(2);
  });

  it("describes an empty allowed list as account-and-site availability without claiming no makerspaces exist", async () => {
    transport.spaces = [];
    mountStaff("/admin");
    await screen.findByText("No makerspaces available to this account from this site.");
    noPanel();
    expect(screen.queryByText(/no makerspaces exist|no makerspaces configured/i)).not.toBeInTheDocument();
  });
});

describe("staff chooser stable picker and browser history", () => {
  it("keeps central admin at the picker with a saved id through remount and late list invalidation", async () => {
    saved(kochi.id);
    const { queryClient } = mountStaff("/admin");
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    expect(leaves).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Remount staff app" }));
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    const late = deferred<Response>();
    transport.routes.set("/admin/makerspaces", () => late.promise);
    act(() => { void queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] }); });
    await waitFor(() => expect(listCalls()).toHaveLength(2));
    await settle(late, json([kochi]));
    await routeIs("/admin");
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    expect(leaves).toEqual([]);
  });

  it.each([0, 1])("prominent switch control %i remains available with one allowed space and opens a stable base picker", async (index) => {
    transport.spaces = [kochi];
    mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    // The real mobile top bar and desktop context strip both expose the action.
    const switches = screen.getAllByRole("button", { name: "Switch makerspace" });
    expect(switches).toHaveLength(2);
    expect(switches[0].closest(".md\\:hidden")).not.toBeNull();
    expect(switches[1]).toHaveClass("md:inline-flex");
    leaves.length = 0;
    fireEvent.click(switches[index]);
    await routeIs("/admin");
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    expect(stored()).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Remount staff app" }));
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    expect(leaves).toEqual([]);
  });

  it("real account menu opens the base picker even with one allowed space", async () => {
    transport.spaces = [kochi];
    mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    fireEvent.keyDown(screen.getByRole("button", { name: "global-admin, account menu" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Switch makerspace" }));
    await routeIs("/admin");
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    noPanel();
  });

  it("switches a valid machine tab to Calicut without carrying Kochi machine type 12", async () => {
    mountStaff("/m/kochi/admin/machines/12-laser");
    await panelIs(kochi.id, "machines");
    fireEvent.keyDown(screen.getByRole("button", { name: "global-admin, account menu" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: "Calicut" }));
    await panelIs(calicut.id, "machines");
    await routeIs("/m/calicut/admin/machines");
    expect(stored()).toBe(String(calicut.id));
  });

  it("Back and Forward supersede chooser intent without stale workspace redirects or a permanent loader", async () => {
    mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    fireEvent.click(screen.getAllByRole("button", { name: "Switch makerspace" })[0]);
    await choose("Calicut");
    await panelIs(calicut.id);
    fireEvent.click(screen.getByRole("button", { name: "History back" }));
    await routeIs("/admin");
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    noPanel();
    fireEvent.click(screen.getByRole("button", { name: "History back" }));
    await routeIs("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    fireEvent.click(screen.getByRole("button", { name: "History forward" }));
    await routeIs("/admin");
    noPanel();
    fireEvent.click(screen.getByRole("button", { name: "History forward" }));
    await panelIs(calicut.id);
  });

  it("navigating to an explicit unavailable target never falls back to the current selected space", async () => {
    transport.spaces = [kochi];
    mountStaff("/m/kochi/admin/settings");
    await panelIs(kochi.id);
    fireEvent.change(screen.getByLabelText("Test destination"), { target: { value: "/m/calicut/admin/settings" } });
    leaves.length = 0;
    fireEvent.click(screen.getByRole("button", { name: "Navigate test route" }));
    await screen.findByRole("heading", { name: "Makerspace unavailable" });
    await routeIs("/m/calicut/admin/settings");
    noPanel();
    expect(leaves).toEqual([]);
  });
});

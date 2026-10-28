import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { machineKeys, type MachineType } from "../machinesApi";
import { StaffSidebarNav, type StaffNavProps } from "./StaffSidebarNav";
import { NAV_GROUPS_OPEN_KEY } from "./useNavGroupsOpen";

const baseProps: StaffNavProps = {
  activeMakerspaceSlug: "tinkerspace-kochi",
  activeTab: "dashboard",
  allowedTabs: ["dashboard", "requests", "inventory", "categories", "machines", "users", "settings"],
  collapsed: false,
  guestOnly: false,
  singleTenantLocked: false,
  unreadCount: 0,
  onNavigate: () => {},
};

const machineTypes = [
  { id: 12, slug: "laser", name: "Laser cutter" },
  { id: 3, slug: "3d_printer", name: "3D Printer" },
] as MachineType[];

function renderNav(props: Partial<StaffNavProps> = {}, { path = "/", types }: { path?: string; types?: MachineType[] } = {}) {
  // Seeded and never stale, so the sidebar reads the cache instead of the network.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  if (types) client.setQueryData(machineKeys.types(7), types);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <StaffSidebarNav {...baseProps} {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function storedOpen() {
  return JSON.parse(window.localStorage.getItem(NAV_GROUPS_OPEN_KEY) ?? "[]") as string[];
}

beforeEach(() => window.localStorage.clear());

describe("StaffSidebarNav groups", () => {
  it("starts every group folded, unfolds one from its heading and remembers it", () => {
    const { unmount } = renderNav();
    const heading = screen.getByRole("button", { name: "Inventory" });
    expect(heading).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Admin" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Categories" })).toBeNull();

    fireEvent.click(heading);
    expect(heading).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Categories" })).toBeVisible();
    expect(storedOpen()).toContain("Inventory");

    unmount();
    renderNav();
    expect(screen.getByRole("button", { name: "Inventory" })).toHaveAttribute("aria-expanded", "true");
  });

  it("opens the group holding the active tab", () => {
    renderNav({ activeTab: "settings" });
    expect(screen.getByRole("button", { name: "Admin" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Settings" })).toBeVisible();
  });

  it("keeps single-row groups and the icon rail without fold controls", () => {
    renderNav();
    expect(screen.queryByRole("button", { name: "Machines" })).toBeNull();
    expect(within(screen.getByRole("group", { name: "Machines" })).getByRole("link", { name: "Machines" })).toBeVisible();

    renderNav({ collapsed: true });
    expect(screen.getAllByRole("link", { name: "Categories" }).length).toBeGreaterThan(0);
  });
});

describe("StaffSidebarNav machine types", () => {
  it("unfolds Machines into one link per reachable type and marks the open one", () => {
    renderNav(
      { activeMakerspaceId: 7, activeTab: "machines" },
      { path: "/m/tinkerspace-kochi/admin/machines/12-laser", types: machineTypes },
    );
    expect(screen.getByRole("button", { name: "Machines" })).toHaveAttribute("aria-expanded", "true");
    const group = within(screen.getByRole("group", { name: "Machines" }));
    expect(group.getAllByRole("link").map((link) => link.textContent)).toEqual(["All machine types", "Laser cutter", "3D Printer"]);
    expect(group.getByRole("link", { name: "All machine types" })).toHaveAttribute("href", "/m/tinkerspace-kochi/admin/machines");
    expect(group.getByRole("link", { name: "3D Printer" })).toHaveAttribute("href", "/m/tinkerspace-kochi/admin/machines/3-3d_printer");
    expect(group.getByRole("link", { name: "Laser cutter" })).toHaveAttribute("aria-current", "page");
    expect(group.getByRole("link", { name: "All machine types" })).not.toHaveAttribute("aria-current");
  });

  it("marks the index when no type is open, and folds Machines like any group", () => {
    const { unmount } = renderNav(
      { activeMakerspaceId: 7, activeTab: "machines" },
      { path: "/m/tinkerspace-kochi/admin/machines", types: machineTypes },
    );
    expect(screen.getByRole("link", { name: "All machine types" })).toHaveAttribute("aria-current", "page");
    unmount();

    window.localStorage.clear();
    renderNav({ activeMakerspaceId: 7 }, { types: machineTypes });
    expect(screen.getByRole("button", { name: "Machines" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Laser cutter" })).toBeNull();
  });

  it("keeps a single Machines icon on the rail", () => {
    renderNav({ activeMakerspaceId: 7, collapsed: true }, { types: machineTypes });
    expect(screen.getByRole("link", { name: "Machines" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Laser cutter" })).toBeNull();
  });
});

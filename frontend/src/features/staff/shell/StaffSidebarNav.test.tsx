import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { StaffSidebarNav, type StaffNavProps } from "./StaffSidebarNav";
import { NAV_GROUPS_COLLAPSED_KEY } from "./useNavGroupsCollapsed";

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

function renderNav(props: Partial<StaffNavProps> = {}) {
  return render(
    <MemoryRouter>
      <StaffSidebarNav {...baseProps} {...props} />
    </MemoryRouter>,
  );
}

beforeEach(() => window.localStorage.clear());

describe("StaffSidebarNav groups", () => {
  it("folds a group from its heading and remembers it", () => {
    const { unmount } = renderNav();
    const heading = screen.getByRole("button", { name: "Inventory" });
    expect(heading).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Categories" })).toBeVisible();

    fireEvent.click(heading);
    expect(heading).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Categories" })).toBeNull();
    expect(JSON.parse(window.localStorage.getItem(NAV_GROUPS_COLLAPSED_KEY) ?? "[]")).toEqual(["Inventory"]);

    unmount();
    renderNav();
    expect(screen.getByRole("button", { name: "Inventory" })).toHaveAttribute("aria-expanded", "false");
  });

  it("opens a folded group when its tab is the active one", () => {
    window.localStorage.setItem(NAV_GROUPS_COLLAPSED_KEY, JSON.stringify(["Admin"]));
    renderNav({ activeTab: "settings" });
    expect(screen.getByRole("button", { name: "Admin" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Settings" })).toBeVisible();
  });

  it("keeps single-tab groups and the icon rail without fold controls", () => {
    renderNav();
    expect(screen.queryByRole("button", { name: "Machines" })).toBeNull();
    expect(within(screen.getByRole("group", { name: "Machines" })).getByRole("link", { name: "Machines" })).toBeVisible();

    window.localStorage.setItem(NAV_GROUPS_COLLAPSED_KEY, JSON.stringify(["Inventory"]));
    renderNav({ collapsed: true });
    expect(screen.getAllByRole("link", { name: "Categories" }).length).toBeGreaterThan(0);
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { machineKeys } from "../machinesApi";
import { serviceType } from "../../../test/staffServiceOwnershipHarness";
import { StaffSidebarNav, type StaffNavProps } from "./StaffSidebarNav";

const types = [{ ...serviceType("generic", 12), makerspace: 7 }, serviceType("printer"),
  { ...serviceType("printer", 13), makerspace: 7, is_builtin: false, name: "Tenant printer" }];
const path = "/m/forge/admin/machines/12-decorative/queue";
function Location() { return <output aria-label="Current path">{useLocation().pathname}</output>; }
function mount(props: Partial<StaffNavProps> = {}, route = path) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  client.setQueryData(machineKeys.types(7), types);
  // Foreign cached types must never become links for the current tenant.
  client.setQueryData(machineKeys.types(8), [{ ...serviceType("generic", 99), makerspace: 8, name: "Foreign router" }]);
  const onNavigate = vi.fn();
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}>
    <StaffSidebarNav activeMakerspaceId={7} activeMakerspaceSlug="forge" activeTab="machines"
      allowedTabs={["machines"]} collapsed={false} guestOnly={false} singleTenantLocked={false}
      unreadCount={0} onNavigate={onNavigate} canManageMachines machineServiceEnabled printingEnabled {...props} />
    <Location />
  </MemoryRouter></QueryClientProvider>);
  return onNavigate;
}
beforeEach(() => localStorage.clear());

describe("unified machine workspace navigation", () => {
  it.each(["/admin", "/m/forge/admin"])("uses one row per scoped server type and navigates by ID under %s", (base) => {
    const onNavigate = mount({ activeMakerspaceSlug: base === "/admin" ? undefined : "forge" }, `${base}/machines/12-decorative/queue`);
    const group = within(screen.getByRole("group", { name: "Machines" }));
    expect(group.getAllByRole("link").map((link) => link.textContent))
      .toEqual(["All machine types", "Presses", "Printers", "Tenant printer"]);
    expect(screen.queryByRole("link", { name: /Foreign router/ })).not.toBeInTheDocument();
    expect(group.getByRole("link", { name: "All machine types" })).toHaveAttribute("href", `${base}/machines`);
    expect(group.getByRole("link", { name: "Printers" })).toHaveAttribute("href", `${base}/machines/2-3d_printer`);
    expect(group.getByRole("link", { name: "Tenant printer" })).toHaveAttribute("href", `${base}/machines/13-3d_printer`);
    const link = group.getByRole("link", { name: "Presses" });
    expect(link).toHaveAttribute("href", `${base}/machines/12-press`);
    fireEvent.click(link);
    expect(screen.getByLabelText("Current path")).toHaveTextContent(`${base}/machines/12-press`);
    expect(onNavigate).toHaveBeenCalledWith("machines");
  });

  it.each([
    ...[false, true].flatMap((canManageMachines) => [false, true].flatMap((machineServiceEnabled) =>
      [false, true].map((printingEnabled) => ({ canManageMachines, machineServiceEnabled, printingEnabled })))),
    { canManageMachines: undefined, machineServiceEnabled: undefined, printingEnabled: undefined },
  ])("keeps one workspace row per type without requests duplicates for gates %j", (gates) => {
    mount(gates);
    const group = within(screen.getByRole("group", { name: "Machines" }));
    expect(group.getAllByRole("link").map((link) => link.textContent))
      .toEqual(["All machine types", "Presses", "Printers", "Tenant printer"]);
    expect(screen.queryByRole("link", { name: /requests$/ })).not.toBeInTheDocument();
    expect(group.getAllByRole("link").every((link) => !link.getAttribute("href")?.endsWith("/queue"))).toBe(true);
  });

  it("does not expose machine workspaces to a collect-only console", () => {
    mount({ allowedTabs: ["handover"], activeTab: "handover", canManageMachines: false });
    expect(screen.queryByRole("link", { name: /requests$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Presses" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Job handover" })).toBeVisible();
  });

  it.each([
    { segment: "12-wrong-slug", name: "Presses" },
    { segment: "12-wrong-slug/queue", name: "Presses" },
    { segment: "2-3d_printer/queue", name: "Printers" },
    { segment: "13-3d_printer/queue", name: "Tenant printer" },
  ])("marks exactly one type row by ID at $segment", ({ segment, name }) => {
    mount({}, `/m/forge/admin/machines/${segment}`);
    const group = within(screen.getByRole("group", { name: "Machines" }));
    const current = group.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]).toBe(group.getByRole("link", { name }));
  });

  it.each(["", "/12-press", "/12-press/queue"])("keeps one actionable, named Machines rail link current at machines%s", (suffix) => {
    const onNavigate = mount({ collapsed: true }, `/m/forge/admin/machines${suffix}`);
    const group = within(screen.getByRole("group", { name: "Machines" }));
    const link = group.getByRole("link", { name: "Machines" });
    expect(group.getAllByRole("link")).toEqual([link]);
    expect(link).toHaveAttribute("href", "/m/forge/admin/machines");
    expect(link).toHaveAttribute("aria-current", "page");
    expect(link.tabIndex).toBe(0);
    link.focus();
    expect(link).toHaveFocus();
    fireEvent.click(link);
    expect(screen.getByLabelText("Current path")).toHaveTextContent(/^\/m\/forge\/admin\/machines$/);
    expect(onNavigate).toHaveBeenCalledWith("machines");
    expect(screen.queryByRole("button", { name: "Machines" })).not.toBeInTheDocument();
  });
});

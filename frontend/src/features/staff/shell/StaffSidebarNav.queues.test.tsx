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

describe("type request navigation authority", () => {
  it("uses only scoped server types and navigates to the ID-specific queue", () => {
    const onNavigate = mount();
    expect(screen.queryByRole("link", { name: /Foreign router/ })).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Presses requests" });
    expect(link).toHaveAttribute("href", "/m/forge/admin/machines/12-press/queue");
    fireEvent.click(link);
    expect(screen.getByLabelText("Current path")).toHaveTextContent("/m/forge/admin/machines/12-press/queue");
    expect(onNavigate).toHaveBeenCalledWith("machines");
  });

  it.each([
    { canManageMachines: false }, { machineServiceEnabled: false },
    { canManageMachines: undefined, machineServiceEnabled: undefined, printingEnabled: undefined },
  ])("withholds queues while leaving operator equipment links usable: %j", (gates) => {
    mount(gates);
    expect(screen.queryByRole("link", { name: /requests$/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Presses" })).toHaveAttribute("href", "/m/forge/admin/machines/12-press");
  });

  it("does not grant queues to a collect-only console", () => {
    mount({ allowedTabs: ["handover"], activeTab: "handover", canManageMachines: false });
    expect(screen.queryByRole("link", { name: /requests$/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Presses" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Job handover" })).toBeVisible();
  });

  it("printing gates only the global printer even when tenant and global slugs match", () => {
    mount({ printingEnabled: false });
    expect(screen.queryByRole("link", { name: "Printers requests" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tenant printer requests" })).toHaveAttribute("href", "/m/forge/admin/machines/13-3d_printer/queue");
    expect(screen.getByRole("link", { name: "Presses requests" })).toBeVisible();
  });

  it.each([false, true])("marks exactly one current row for queue=%s", (queue) => {
    mount({}, `/m/forge/admin/machines/12-wrong-slug${queue ? "/queue" : ""}`);
    const group = within(screen.getByRole("group", { name: "Machines" }));
    const current = group.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent(queue ? "Presses requests" : "Presses");
    expect(group.getByRole("link", { name: queue ? "Presses" : "Presses requests" })).not.toHaveAttribute("aria-current");
  });

  it("keeps actionable, named queue links on the collapsed rail", () => {
    mount({ collapsed: true });
    const link = screen.getByRole("link", { name: "Presses requests" });
    expect(link).toHaveAttribute("aria-current", "page");
    link.focus();
    expect(link).toHaveFocus();
    fireEvent.click(link);
    expect(screen.getByLabelText("Current path")).toHaveTextContent("/m/forge/admin/machines/12-press/queue");
    expect(screen.queryByRole("button", { name: "Machines" })).not.toBeInTheDocument();
  });
});

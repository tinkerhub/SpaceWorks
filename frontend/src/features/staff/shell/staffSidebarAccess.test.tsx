import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import type { StaffAuthUser } from "../../../lib/api";
import { StaffWorkspace } from "../StaffWorkspace";
import type { Makerspace } from "../panels/shared";

const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"];

function space(modules: string[]): Makerspace {
  return {
    id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false, enabled_modules: modules, enabled_features: [],
  };
}

function renderWorkspace({ actions, superadmin = false, modules }: { actions: string[]; superadmin?: boolean; modules: string[] }) {
  const makerspace = space(modules);
  const user: StaffAuthUser = {
    username: "operator", email_verified: true, role: superadmin ? "superadmin" : "staff", is_superuser: superadmin,
    must_change_password: false,
    makerspaces: superadmin ? [] : [{ id: 7, slug: "forge", role_name: "Inventory Manager", actions } as unknown as StaffAuthUser["makerspaces"][number]],
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/m/forge/admin/inventory"]}>
        <Routes>
          <Route
            path="*"
            element={(
              <StaffWorkspace
                activeMakerspace={makerspace} actions={actions} isMachineOnly={false} canConfigureMachineTypes={false}
                guestOnly={false} isSuperadmin={superadmin} makerspaces={[makerspace]} onAuthRefresh={vi.fn()}
                selected={7} setSelected={vi.fn()} setTab={vi.fn()} signOut={vi.fn().mockResolvedValue(undefined)}
                singleTenantLocked={false} user={user}
              />
            )}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return within(screen.getByRole("navigation", { name: "Staff sections" }));
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue({ count: 0, results: [] });
});

describe("staff sidebar gating", () => {
  it("lists only what the role allows, even when the module is on", () => {
    const nav = renderWorkspace({ actions: ["view_inventory", "edit_inventory"], modules: [...CORE, "machines", "stocktake"] });

    for (const label of ["Dashboard", "Inventory", "Categories", "To-be-fixed", "Stocktake", "Ledger"]) {
      expect(nav.getByRole("link", { name: label, hidden: true })).toBeInTheDocument();
    }
    // `machines` is on, but the role holds neither manage_printing nor manage_machines.
    for (const label of ["Machines", "Settings", "Users", "Modules", "Audit log", "Platform settings"]) {
      expect(nav.queryByRole("link", { name: label, hidden: true })).not.toBeInTheDocument();
    }
  });

  it("lists only what the modules allow, even for a superadmin", () => {
    const nav = renderWorkspace({ actions: [], superadmin: true, modules: CORE });

    for (const label of ["Inventory", "Settings", "Modules", "Audit log"]) {
      expect(nav.getByRole("link", { name: label, hidden: true })).toBeInTheDocument();
    }
    for (const label of ["Machines", "Events", "Bookings", "Payments", "Stocktake", "To Buy", "Notifications"]) {
      expect(nav.queryByRole("link", { name: label, hidden: true })).not.toBeInTheDocument();
    }
  });

  it("never lists the removed organization pages", () => {
    const nav = renderWorkspace({ actions: [], superadmin: true, modules: [...CORE, "events", "machines"] });
    expect(nav.queryByRole("link", { name: /organi[sz]ation|organized events/i, hidden: true })).not.toBeInTheDocument();
    expect(nav.getByRole("link", { name: "Events" })).toBeInTheDocument();
    expect(nav.getByRole("link", { name: "Machines" })).toBeInTheDocument();
  });
});

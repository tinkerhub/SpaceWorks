import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

import type { StaffAuthUser } from "../../lib/api";
import { StaffWorkspace } from "./StaffWorkspace";
import type { Makerspace } from "./panels/shared";

// The six keys `_canonical_modules` always keeps: every optional module is off.
const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"];

const user: StaffAuthUser = {
  username: "root",
  email_verified: true,
  role: "superadmin",
  is_superuser: true,
  must_change_password: false,
  makerspaces: [],
};

function space(modules: string[]): Makerspace {
  return {
    id: 7,
    name: "Forge",
    public_code: "forge",
    slug: "forge",
    telegram_group_chat_id: "",
    frontend_domain: null,
    hidden_from_central_directory: false,
    enabled_modules: modules,
    enabled_features: [],
  };
}

function renderConsole(path: string, modules = CORE) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const makerspace = space(modules);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="*"
            element={(
              <StaffWorkspace
                activeMakerspace={makerspace}
                actions={[]}
                isMachineOnly={false}
                canConfigureMachineTypes
                guestOnly={false}
                isSuperadmin
                makerspaces={[makerspace]}
                onAuthRefresh={vi.fn()}
                selected={7}
                setSelected={vi.fn()}
                setTab={vi.fn()}
                signOut={vi.fn().mockResolvedValue(undefined)}
                singleTenantLocked={false}
                user={user}
              />
            )}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) => {
    if (path.endsWith("/dashboard")) return Promise.resolve({ scope_mode: "full" });
    if (path.includes("/payments")) return Promise.resolve([]);
    return Promise.resolve({ count: 0, results: [] });
  });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
});

afterEach(() => vi.unstubAllGlobals());

describe("staff console with only the core modules", () => {
  it.each([
    "machines", "events", "bookings", "payments", "to-buy", "transfers", "stocktake",
    "containers", "bulk-import", "qr-tools", "reports", "handover",
  ])("refuses the %s route", async (path) => {
    renderConsole(`/m/forge/admin/${path}`);
    expect(await screen.findByText("Access denied")).toBeInTheDocument();
  });

  it("treats a notifications bookmark as stale and lands on the dashboard", async () => {
    // StaffWorkspace normalizes, rather than denies, the two tabs it omits by design.
    renderConsole("/m/forge/admin/notifications");
    expect(await screen.findByText("Overdue loans")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Notifications" })).not.toBeInTheDocument();
  });

  it("drops navigation groups whose every tab belongs to a switched-off module", async () => {
    renderConsole("/m/forge/admin/dashboard");
    const nav = await screen.findByRole("navigation", { name: "Staff sections" });
    expect(within(nav).getByRole("group", { name: "Inventory" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Inventory", hidden: true })).toBeInTheDocument();
    for (const group of ["Machines", "Events", "Bookings"]) {
      expect(within(nav).queryByRole("group", { name: group })).not.toBeInTheDocument();
      expect(within(nav).queryByRole("link", { name: group })).not.toBeInTheDocument();
    }
  });

  it("renders only core dashboard tiles", async () => {
    renderConsole("/m/forge/admin/dashboard");
    expect(await screen.findByText("Overdue loans")).toBeInTheDocument();
    for (const label of ["Pending prints", "Stocktakes awaiting approval", "Maintenance overdue", "Pending payments"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("serves a gated tab once its module is on", async () => {
    renderConsole("/m/forge/admin/payments", [...CORE, "payments"]);
    expect(await screen.findByRole("heading", { name: "Payments" })).toBeInTheDocument();
    expect(screen.queryByText("Access denied")).not.toBeInTheDocument();
  });
});

describe("console scope", () => {
  it.each(["organizations", "organized-events", "organization-analytics"])(
    "has no %s page: the stale route lands on the dashboard",
    async (path) => {
      renderConsole(`/m/forge/admin/${path}`);
      expect(await screen.findByText("Overdue loans")).toBeInTheDocument();
      expect(screen.queryByText("Access denied")).not.toBeInTheDocument();
    },
  );
});

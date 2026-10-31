import type { ComponentProps } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./StaffTabContent", () => ({
  StaffTabContent: ({ activeTab, activeMakerspace }: ComponentProps<typeof import("./StaffTabContent").StaffTabContent>) => (
    <section
      aria-label="Operational content"
      data-tab={activeTab}
      data-makerspace-id={activeMakerspace?.id}
      data-makerspace-slug={activeMakerspace?.slug}
    >
      {activeTab} / {activeMakerspace?.name}
    </section>
  ),
}));

import type { StaffAuthUser } from "../../lib/api";
import { StaffWorkspace } from "./StaffWorkspace";
import type { Makerspace } from "./panels/shared";
import { persistStaffTab, STAFF_ACTIVE_TAB_KEY } from "./staffTabs";

const forge: Makerspace = {
  id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
  frontend_domain: null, hidden_from_central_directory: false, superadmin_access_enabled: true,
  enabled_modules: ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"],
  enabled_features: [],
};

const user: StaffAuthUser = {
  username: "operator", email_verified: true, role: "superadmin", is_superuser: true,
  must_change_password: false, makerspaces: [],
  staff_context: {
    scope_kind: "platform", makerspace_id: null, can_manage_platform: true,
    platform_hosting: false, platform_stripe_connect_available: false,
  },
};

let client: QueryClient | undefined;

function CurrentPath() {
  return <output data-testid="current-path">{useLocation().pathname}</output>;
}

function renderWorkspace(initialEntry = "/m/forge/admin") {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <CurrentPath />
        <Routes>
          <Route
            path="/admin/platform"
            element={(
              <>
                <h1>Global Platform endpoint</h1>
                <Link to="/m/forge/admin">Return to Forge</Link>
              </>
            )}
          />
          <Route
            path="/m/forge/admin/*"
            element={(
              <StaffWorkspace
                activeMakerspace={forge} actions={[]} isMachineOnly={false} canConfigureMachineTypes={false}
                guestOnly={false} isSuperadmin={true} makerspaces={[forge]} onAuthRefresh={vi.fn()}
                selected={7} setSelected={vi.fn()} setTab={persistStaffTab} signOut={vi.fn().mockResolvedValue(undefined)}
                singleTenantLocked={false} user={user}
              />
            )}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function expectForgeTab(tab: "dashboard" | "settings") {
  await waitFor(() => {
    expect(screen.getByTestId("current-path").textContent).toBe(`/m/forge/admin/${tab}`);
    const leaf = within(screen.getByRole("main")).getByRole("region", { name: "Operational content" });
    expect(leaf).toHaveAttribute("data-tab", tab);
    expect(leaf).toHaveAttribute("data-makerspace-id", "7");
    expect(leaf).toHaveAttribute("data-makerspace-slug", "forge");
    expect(leaf).toHaveTextContent(`${tab} / Forge`);
  });
  expect(screen.getByRole("link", { name: "Public inventory" })).toHaveAttribute("href", "/m/forge");
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
  client?.clear();
  client = undefined;
  localStorage.clear();
});

describe("maker workspace navigation after visiting global Platform settings", () => {
  it("ignores a legacy remembered Platform tab and opens Forge's allowed default", async () => {
    localStorage.setItem(STAFF_ACTIVE_TAB_KEY, "platform");

    renderWorkspace();

    await expectForgeTab("dashboard");
  });

  it("restores a valid remembered Settings tab inside Forge", async () => {
    localStorage.setItem(STAFF_ACTIVE_TAB_KEY, "settings");

    renderWorkspace();

    await expectForgeTab("settings");
    expect(localStorage.getItem(STAFF_ACTIVE_TAB_KEY)).toBe("settings");
  });

  it("keeps Settings remembered when the real sidebar opens Platform and returns to Forge", async () => {
    localStorage.setItem(STAFF_ACTIVE_TAB_KEY, "settings");
    renderWorkspace("/m/forge/admin/settings");
    await expectForgeTab("settings");

    const nav = within(screen.getByRole("navigation", { name: "Staff sections" }));
    const admin = nav.getByRole("button", { name: "Admin" });
    if (admin.getAttribute("aria-expanded") === "false") fireEvent.click(admin);
    const platformLink = nav.getByRole("link", { name: "Platform settings" });
    expect(platformLink).toHaveAttribute("href", "/admin/platform");
    fireEvent.click(platformLink);

    expect(await screen.findByRole("heading", { name: "Global Platform endpoint" })).toBeInTheDocument();
    expect(screen.getByTestId("current-path").textContent).toBe("/admin/platform");
    expect(screen.queryByRole("region", { name: "Operational content" })).not.toBeInTheDocument();
    expect(localStorage.getItem(STAFF_ACTIVE_TAB_KEY)).toBe("settings");

    fireEvent.click(screen.getByRole("link", { name: "Return to Forge" }));

    await expectForgeTab("settings");
    expect(localStorage.getItem(STAFF_ACTIVE_TAB_KEY)).toBe("settings");
  });
});

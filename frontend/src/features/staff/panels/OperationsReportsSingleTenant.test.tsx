import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { OperationsReports } from "./OperationsReports";
import { reportDefinitions, savedViewsStorageKey, type SavedReportView } from "./operationsReportsConfig";
import type { Makerspace } from "./shared";

const makerspace: Makerspace = {
  id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
  frontend_domain: null, hidden_from_central_directory: false, enabled_modules: ["reports"],
};

function renderReports(singleTenantLocked: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OperationsReports
        makerspace={makerspace}
        makerspaces={[makerspace]}
        isSuperadmin
        singleTenantLocked={singleTenantLocked}
        canViewAudit
        canManageMachines={false}
        canManageMakerspace={false}
      />
    </QueryClientProvider>,
  );
}

const requestedPaths = () => staffRequest.mock.calls.map(([path]) => String(path));

beforeEach(() => {
  window.localStorage.clear();
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) => {
    if (path.endsWith("/reports/catalog")) return Promise.resolve({ results: reportDefinitions.slice(0, 3) });
    return Promise.resolve({ rows: [], typed_rows: [] });
  });
});

describe("Reports on an origin-locked (single-tenant) site", () => {
  it("hides the all-makerspaces switch and only calls per-makerspace routes", async () => {
    renderReports(true);
    await waitFor(() => expect(requestedPaths()).toContain("/admin/makerspace/7/reports/catalog"));
    expect(screen.queryByRole("switch", { name: /All makerspaces/ })).not.toBeInTheDocument();
    expect(requestedPaths().some((path) => path.startsWith("/admin/reports") || path.startsWith("/admin/analytics"))).toBe(false);
  });

  it("does not switch to the aggregate when a saved all-makerspaces view is applied", async () => {
    const view: SavedReportView = {
      id: "v1", name: "Everything", startDate: "", endDate: "", scope: "all", scopeLabel: "all makerspaces", selectedReport: "most-lent",
    };
    window.localStorage.setItem(savedViewsStorageKey, JSON.stringify([view]));
    renderReports(true);
    fireEvent.click(await screen.findByRole("button", { name: /^Everything/ }));
    await waitFor(() => expect(requestedPaths()).toContain("/admin/makerspace/7/reports/catalog"));
    expect(requestedPaths().some((path) => path.startsWith("/admin/reports") || path.startsWith("/admin/analytics"))).toBe(false);
  });

  it("offers the all-makerspaces switch to a superadmin on a multi-tenant site", async () => {
    renderReports(false);
    const toggle = await screen.findByRole("switch", { name: /All makerspaces/ });
    fireEvent.click(toggle);
    await waitFor(() => expect(requestedPaths()).toContain("/admin/reports/catalog"));
  });
});

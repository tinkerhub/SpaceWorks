import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { OperationsReports } from "./OperationsReports";
import { reportDefinitions } from "./operationsReportsConfig";
import type { Makerspace } from "./shared";

// The production check-in module set: events, bookings, membership and payments are off.
const MODULES = [
  "public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads",
  "reports", "machines", "maintenance", "machine_service", "printing",
];

const entry = (key: string, title: string, extra: Record<string, unknown> = {}) => ({
  ...reportDefinitions.find((report) => report.key === key)!, title, ...extra,
});

const catalog = {
  results: [
    entry("most-lent", "Most lent"),
    entry("qr-scans", "QR scans"),
    // A stale or mixed server answer: an unavailable entry must never be offered.
    entry("community-engagement", "Community engagement", { available: false, unavailable_reason: "Required module disabled: membership" }),
  ],
};

function renderReports() {
  const makerspace: Makerspace = {
    id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false, enabled_modules: MODULES,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OperationsReports makerspace={makerspace} makerspaces={[makerspace]} isSuperadmin={false} canViewAudit canManageMachines canManageMakerspace />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) => {
    if (path.endsWith("/reports/catalog")) return Promise.resolve(catalog);
    return Promise.resolve({
      rows: [], typed_rows: [], status_totals: [], machines: [], consumption: [], failure_summary: [], printer_metrics: [],
    });
  });
});

describe("reports on a check-in site with events, bookings, membership and payments off", () => {
  it("describes the FabLab health card by the modules that are on", async () => {
    renderReports();
    expect(await screen.findByRole("heading", { name: "FabLab health" })).toBeInTheDocument();
    expect(screen.getByText("Machines and maintenance at a glance.")).toBeInTheDocument();
    expect(screen.queryByText(/^Events, bookings/)).not.toBeInTheDocument();
  });

  it("drops catalog entries the server marks unavailable instead of listing them disabled", async () => {
    renderReports();
    fireEvent.click(screen.getByRole("combobox", { name: "Report" }));
    expect(await screen.findByRole("option", { name: "QR scans" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Community engagement" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Community engagement" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Required module disabled/)).not.toBeInTheDocument();
    expect(staffRequest).not.toHaveBeenCalledWith(expect.stringContaining("community-engagement"));
  });
});

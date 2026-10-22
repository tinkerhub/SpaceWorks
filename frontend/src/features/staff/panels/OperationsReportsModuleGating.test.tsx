import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { OperationsReports } from "./OperationsReports";
import { reportDefinitions } from "./operationsReportsConfig";
import type { Makerspace } from "./shared";

const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"];

// Two coverage reports: one core, one owned by a module the space does not run.
const catalog = {
  results: [
    { ...reportDefinitions.find((report) => report.key === "loan-throughput")!, title: "Loan throughput", required_modules: [] },
    { ...reportDefinitions.find((report) => report.key === "community-engagement")!, title: "Community engagement", required_modules: ["membership"] },
  ],
};

function renderReports(modules: string[]) {
  const makerspace: Makerspace = {
    id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false, enabled_modules: modules,
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

describe("reports with only the core modules and reports", () => {
  it("renders no panel, health tile or catalog entry for a switched-off module", async () => {
    renderReports([...CORE, "reports"]);
    const coverage = screen.getByRole("region", { name: "Module coverage reports" });
    expect(await within(coverage).findByRole("heading", { name: "Loan throughput" })).toBeInTheDocument();
    for (const name of [
      "Community engagement", "Payment reconciliation", "Member activity", "FabLab health",
      "Machine usage", "Events attendance", "Machine service", "Printer service",
    ]) {
      expect(screen.queryByRole("heading", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByText("Module disabled")).not.toBeInTheDocument();
    // The Report picker lists only reports whose modules are on.
    fireEvent.click(screen.getByRole("combobox", { name: "Report" }));
    expect(await screen.findByRole("option", { name: "Loan throughput" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Community engagement" })).not.toBeInTheDocument();
    expect(staffRequest).not.toHaveBeenCalledWith(expect.stringContaining("payment-reconciliation"));
    expect(staffRequest).not.toHaveBeenCalledWith(expect.stringContaining("fablab-health"));
  });

  it("brings each panel back with its module", async () => {
    renderReports([...CORE, "reports", "membership", "payments", "events", "machine_service", "printing"]);
    const coverage = screen.getByRole("region", { name: "Module coverage reports" });
    expect(await within(coverage).findByRole("heading", { name: "Community engagement" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Payment reconciliation" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Member activity" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "FabLab health" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Machine service" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Printer service" })).toBeInTheDocument();
  });
});

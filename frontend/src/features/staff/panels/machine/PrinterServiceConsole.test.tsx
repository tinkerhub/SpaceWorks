import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PrinterServiceConsole } from "./PrinterServiceConsole";
import { blankServiceDraft } from "./serviceDrafts";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string) => {
    if (path.includes("machine-service-report")) {
      return {
        printer_metrics: [{
          machine_id: 12,
          machine_name: "Demo Printer",
          model: "MK4",
          completed_hours: 2,
          failed_partial_hours: 0.25,
          manual_hours: 1,
          consumed_grams: "125.00",
          payment_due: "0.00",
          payment_paid: "0.00",
        }],
      };
    }
    return [];
  });
});

describe("PrinterServiceConsole", () => {
  it("renders the printer-specific report response without crashing the staff console", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const machineType = { id: 1, slug: "3d_printer", name: "3D Printer", icon: "", is_builtin: true, managing_action: "", makerspace: null, capability_config: { metering_unit: "weight" as const, requires_booking: false } };
    render(
      <QueryClientProvider client={client}>
        <PrinterServiceConsole makerspaceId={1} canManage printingEnabled machineType={machineType} machines={[]} pools={[]} draft={blankServiceDraft()} setDraft={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Demo Printer")).toBeVisible();
    expect(screen.getByText(/2h complete.*125.00g used/)).toBeVisible();
    expect(screen.queryByText("Printers")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Printer name")).not.toBeInTheDocument();
  });

  // The report endpoint discriminates on the machine_type SLUG to decide whether to emit
  // `printer_metrics`. Sending the type ID instead returns the generic report, and the render
  // dereferences `printer_metrics` -- taking the whole Machines panel down with it. The mock
  // above answers regardless of query string, so only this assertion catches the regression.
  it("requests the printer report with the slug discriminator, not the type id", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const machineType = { id: 1, slug: "3d_printer", name: "3D Printer", icon: "", is_builtin: true, managing_action: "", makerspace: null, capability_config: { metering_unit: "weight" as const, requires_booking: false } };
    render(
      <QueryClientProvider client={client}>
        <PrinterServiceConsole makerspaceId={1} canManage printingEnabled machineType={machineType} machines={[]} pools={[]} draft={blankServiceDraft()} setDraft={vi.fn()} />
      </QueryClientProvider>,
    );

    await screen.findByText("Demo Printer");
    const reportCall = staffRequest.mock.calls
      .map(([path]) => String(path))
      .find((path) => path.includes("machine-service-report"));
    expect(reportCall).toContain("machine_type=3d_printer");
  });

  it("uses the nested online payment instead of the manual fallback fields", async () => {
    staffRequest.mockImplementation(async (path: string) => {
      if (path.includes("machine-service/requests")) return [{
        id: 9,
        title: "Paid print",
        status: "completed",
        planned_grams: "25.00",
        payment_status: "none",
        payment_amount: null,
        payment: { id: 52, status: "paid_online", amount: "25.00", currency: "inr" },
      }];
      if (path.includes("machine-service-report")) return { printer_metrics: [] };
      return [];
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const machineType = { id: 1, slug: "3d_printer", name: "3D Printer", icon: "", is_builtin: true, managing_action: "", makerspace: null, capability_config: { metering_unit: "weight" as const, requires_booking: false } };

    render(
      <QueryClientProvider client={client}>
        <PrinterServiceConsole makerspaceId={1} canManage printingEnabled machineType={machineType} machines={[]} pools={[]} draft={blankServiceDraft()} setDraft={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/payment paid INR 25.00/i)).toBeVisible();
  });

  it("offers settlement only for a completed request with a pending payment row", async () => {
    staffRequest.mockImplementation(async (path: string) => {
      if (path.includes("machine-service/requests")) return [
        {
          id: 10,
          title: "Paid print",
          status: "completed",
          planned_grams: "25.00",
          payment_status: "none",
          payment_amount: null,
          payment: { id: 53, status: "pending", amount: "25.00", currency: "inr" },
        },
        {
          id: 11,
          title: "Free print",
          status: "completed",
          planned_grams: "10.00",
          payment_status: "none",
          payment_amount: null,
          payment: null,
        },
      ];
      if (path.includes("machine-service-report")) return { printer_metrics: [] };
      return [];
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const machineType = { id: 1, slug: "3d_printer", name: "3D Printer", icon: "", is_builtin: true, managing_action: "", makerspace: null, capability_config: { metering_unit: "weight" as const, requires_booking: false } };

    render(
      <QueryClientProvider client={client}>
        <PrinterServiceConsole makerspaceId={1} canManage printingEnabled machineType={machineType} machines={[]} pools={[]} draft={blankServiceDraft()} setDraft={vi.fn()} />
      </QueryClientProvider>,
    );

    const payableRequest = (await screen.findByText("Paid print")).closest("article")!;
    const freeRequest = screen.getByText("Free print").closest("article")!;
    expect(within(payableRequest).getByRole("button", { name: /record payment.*INR 25.00/i })).toBeVisible();
    expect(within(freeRequest).queryByRole("button", { name: /record payment/i })).not.toBeInTheDocument();
    expect(within(freeRequest).getByRole("button", { name: "Collect" })).toBeVisible();
  });
});

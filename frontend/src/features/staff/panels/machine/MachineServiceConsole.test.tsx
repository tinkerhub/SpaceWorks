import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MachineType } from "../../machinesApi";
import { MachineServiceConsole } from "./MachineServiceConsole";
import { blankServiceDraft } from "./serviceDrafts";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

describe("MachineServiceConsole", () => {
  beforeEach(() => staffRequest.mockReset());

  it("uses its fixed machine type without rendering a type selector", async () => {
    const machineType: MachineType = {
      id: 7,
      slug: "laser",
      name: "Laser cutters",
      icon: "",
      is_builtin: false,
      managing_action: "manage_machines",
      makerspace: 1,
      capability_config: { metering_unit: "length", requires_booking: false },
    };
    staffRequest.mockImplementation(async (path?: string) => {
      if (path?.includes("machine-service/requests")) return [{
        id: 4,
        title: "Laser job",
        status: "pending",
        planned_quantity: "20",
        actual_consumed_quantity: "0",
        payment_status: "none",
        payment_amount: null,
        payment: { id: 41, status: "pending", amount: "14.50", currency: "usd" },
      }];
      return [];
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <MachineServiceConsole makerspaceId={1} canManage machineType={machineType} machines={[]} pools={[]} draft={blankServiceDraft()} setDraft={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("Laser job")).toBeVisible();
    expect(screen.getByText(/payment owed USD 14.50/i)).toBeVisible();
    expect(screen.queryByLabelText("Machine type")).not.toBeInTheDocument();
    await waitFor(() => expect(staffRequest.mock.calls.some(([path]) => String(path).includes("machine_type_id=7"))).toBe(true));
    expect(staffRequest.mock.calls.some(([path]) => String(path).includes("machine-types"))).toBe(false);
  });

  it("offers settlement only for a completed request with a pending payment row", async () => {
    const machineType: MachineType = {
      id: 7,
      slug: "laser",
      name: "Laser cutters",
      icon: "",
      is_builtin: false,
      managing_action: "manage_machines",
      makerspace: 1,
      capability_config: { metering_unit: "length", requires_booking: false },
    };
    staffRequest.mockImplementation(async (path?: string) => {
      if (path?.includes("machine-service/requests")) return [
        {
          id: 4,
          title: "Paid laser job",
          status: "completed",
          payment: { id: 41, status: "pending", amount: "14.50", currency: "usd" },
          payment_status: "none",
          payment_amount: null,
        },
        {
          id: 5,
          title: "Free laser job",
          status: "completed",
          payment: null,
          payment_status: "none",
          payment_amount: null,
        },
      ];
      return [];
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <MachineServiceConsole makerspaceId={1} canManage machineType={machineType} machines={[]} pools={[]} draft={blankServiceDraft()} setDraft={vi.fn()} />
      </QueryClientProvider>,
    );

    const payableRequest = (await screen.findByText("Paid laser job")).closest("article")!;
    const freeRequest = screen.getByText("Free laser job").closest("article")!;
    expect(within(payableRequest).getByRole("button", { name: /record payment.*USD 14.50/i })).toBeVisible();
    expect(within(freeRequest).queryByRole("button", { name: /record payment/i })).not.toBeInTheDocument();
    expect(within(freeRequest).getByRole("button", { name: "Collect" })).toBeVisible();
  });
});

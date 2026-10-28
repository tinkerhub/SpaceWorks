import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Machine, MachineType } from "../../machinesApi";
import { MachineServiceConsole } from "./MachineServiceConsole";
import { blankServiceDraft } from "./serviceDrafts";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../../lib/api", () => ({ staffRequest }));

describe("MachineServiceConsole", () => {
  beforeEach(() => {
    staffRequest.mockReset();
  });

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
    expect(screen.getByText(/payment owed \$14\.50/i)).toBeVisible();
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
    expect(within(payableRequest).getByRole("button", { name: "Record payment · $14.50" })).toBeVisible();
    expect(within(freeRequest).queryByRole("button", { name: /record payment/i })).not.toBeInTheDocument();
    expect(within(freeRequest).getByRole("button", { name: "Collect" })).toBeVisible();
  });

  it("measures a quantity in the type's unit for a type without consumables, with no pool picker", async () => {
    const machineType: MachineType = {
      id: 8,
      slug: "badge_press",
      name: "Badge press",
      icon: "",
      is_builtin: true,
      managing_action: "manage_machines",
      makerspace: null,
      capability_config: { metering_unit: "minutes", requires_booking: false },
      effective_config: { metering_unit: "count", requires_booking: false, uses_consumables: false, overridden: true },
    };
    staffRequest.mockImplementation(async (path?: string) => {
      if (path?.includes("machine-service/requests?")) return [{ id: 4, title: "Badges", status: "in_progress", payment: null, payment_status: "none", payment_amount: null }];
      return [];
    });
    const draft = blankServiceDraft();
    draft.action = { id: 4, name: "complete" };
    draft.actionValues.actual_quantity = "3";
    draft.manual = { ...draft.manual, machine_id: "11", duration_minutes: "10", quantity: "3" };
    const machines = [{ id: 11, name: "Press", makerspace: 1, machine_type: machineType }] as unknown as Machine[];
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <QueryClientProvider client={client}>
        <MachineServiceConsole makerspaceId={1} canManage machineType={machineType} machines={machines} pools={[]} draft={draft} setDraft={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByLabelText("Actual quantity (items)")).toHaveValue("3");
    expect(screen.getByLabelText("Manual usage quantity")).toHaveValue(3);
    expect(screen.queryByLabelText("Pool")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Manual usage pool")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Complete job" }));
    fireEvent.click(screen.getByRole("button", { name: "Log usage" }));
    const body = (suffix: string) => JSON.parse(String(staffRequest.mock.calls.find(([path, init]) => String(path).endsWith(suffix) && init?.method === "POST")?.[1]?.body));
    await waitFor(() => expect(body("/4/complete")).toEqual({ actual_minutes: 0, actual_quantity: "3" }));
    await waitFor(() => expect(body("/typed-manual-usage")).toMatchObject({ machine_id: 11, consumable_pool_id: null, quantity: "3", metering_unit: "count" }));
  });
});

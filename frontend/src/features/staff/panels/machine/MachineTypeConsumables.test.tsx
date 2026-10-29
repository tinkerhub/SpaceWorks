import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PrinterPool } from "../../../../generated/api";
import { MachineTypeConsumables } from "./MachineTypeConsumables";
import { testMachine } from "./machineTestFixtures";
import { poolPath, poolQueryKey } from "./servicePools";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../../lib/api", () => ({ staffRequest }));

function pool(id: number, material: string, overrides: Partial<PrinterPool> = {}): PrinterPool {
  return { id, material, machine_id: null, machine_type_id: 2, color: "", brand: "",
    unit: "grams", initial_grams: "100", remaining_grams: "75", is_active: true,
    created_at: "", updated_at: "", ...overrides };
}

function renderStock(client: QueryClient, canManageMachines = true, machineServiceEnabled = true) {
  return render(<QueryClientProvider client={client}>
    <MachineTypeConsumables machine={testMachine} makerspaceId={1}
      canManageMachines={canManageMachines} machineServiceEnabled={machineServiceEnabled} />
  </QueryClientProvider>);
}

beforeEach(() => { staffRequest.mockReset(); });

describe("Machine drawer type stock", () => {
  it("shows matching type, own-machine and legacy space stock using their existing balances", async () => {
    staffRequest.mockResolvedValue([
      pool(1, "Type PLA"),
      pool(2, "This printer PLA", { machine_id: 41, machine_type_id: null }),
      pool(3, "Other printer PLA", { machine_id: 42, machine_type_id: null }),
      pool(4, "Other type PLA", { machine_type_id: 3 }),
      pool(5, "Wrong units", { unit: "milliliters" }),
      pool(6, "Inactive stock", { is_active: false }),
      pool(7, "Legacy space PLA", { machine_type_id: null, unit: undefined }),
    ]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    renderStock(client);
    expect(await screen.findByText("Type PLA", { selector: "strong" })).toBeVisible();
    expect(screen.getByText("This printer PLA", { selector: "strong" })).toBeVisible();
    expect(screen.getByText("Legacy space PLA", { selector: "strong" })).toBeVisible();
    for (const label of ["Other printer PLA", "Other type PLA", "Wrong units", "Inactive stock"]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    expect(screen.getAllByRole("progressbar")).toHaveLength(3);
    expect(screen.getAllByRole("progressbar").every((bar) => bar.getAttribute("aria-valuenow") === "75")).toBe(true);
    expect(staffRequest).toHaveBeenCalledTimes(1);
    expect(staffRequest).toHaveBeenCalledWith(poolPath(1));
    expect(screen.queryByRole("button", { name: /link|add.*filament/i })).not.toBeInTheDocument();
  });

  it.each([[false, true], [true, false], [false, false]])(
    "gates both rendering and fetch with cached stock (manager=%s, module=%s)", async (manager, module) => {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      client.setQueryData(poolQueryKey(1), [pool(1, "Privileged cached PLA")]);
      const { container } = renderStock(client, manager, module);
      await waitFor(() => expect(container).toBeEmptyDOMElement());
      expect(staffRequest).not.toHaveBeenCalled();
      expect(client.getQueryData(poolQueryKey(1))).toHaveLength(1);
    },
  );

  it("hides previously visible stock when management permission is revoked", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    client.setQueryData(poolQueryKey(1), [pool(1, "Previously visible stock")]);
    const view = renderStock(client);
    expect(screen.getByText("Previously visible stock")).toBeVisible();
    view.rerender(<QueryClientProvider client={client}>
      <MachineTypeConsumables machine={testMachine} makerspaceId={1} canManageMachines={false} machineServiceEnabled />
    </QueryClientProvider>);
    await waitFor(() => expect(screen.queryByText("Previously visible stock")).not.toBeInTheDocument());
    expect(staffRequest).not.toHaveBeenCalled();
  });
});

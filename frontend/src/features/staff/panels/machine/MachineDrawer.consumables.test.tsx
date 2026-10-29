import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PrinterPool } from "../../../../generated/api";
import { machineKeys } from "../../machinesApi";
import { MachineDrawer } from "./MachineDrawer";
import { testMachine } from "./machineTestFixtures";
import { poolPath, poolQueryKey } from "./servicePools";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../../lib/api", () => ({ staffRequest }));
vi.mock("./OverviewTab", () => ({ OverviewTab: () => null }));

const stock: PrinterPool = {
  id: 1, machine_id: null, machine_type_id: 2, material: "Drawer PLA",
  unit: "grams", initial_grams: "100", remaining_grams: "75", is_active: true,
  created_at: "", updated_at: "",
};

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation(async (path: string) => path === poolPath(1) ? [stock] : []);
});

function openConsumables(manage: boolean, module: boolean) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(machineKeys.detail(41), { ...testMachine, can_edit: manage });
  client.setQueryDefaults(machineKeys.detail(41), { staleTime: Infinity });
  // Use the same populated cache as the machine-type page, even for denied actors.
  client.setQueryData(poolQueryKey(1), [stock]);
  render(<QueryClientProvider client={client}>
    <MachineDrawer machineId={41} makerspaceId={1} canManageMachines={manage}
      maintenanceEnabled={false} machineServiceEnabled={module} onClose={vi.fn()} />
  </QueryClientProvider>);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Consumables" }), { button: 0, ctrlKey: false });
}

describe("MachineDrawer consumable stock integration", () => {
  it("exposes type stock alongside the local ledger without creating a second stock balance", async () => {
    openConsumables(true, true);
    expect(await screen.findByText("Drawer PLA", { selector: "strong" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "3D printers consumables" })).toBeVisible();
    expect(await screen.findByText("No consumables linked")).toBeVisible();
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(poolPath(1)));
    expect(staffRequest.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
    expect(screen.queryByRole("button", { name: /link filament/i })).not.toBeInTheDocument();
  });

  it.each([[false, true], [true, false]])("keeps cached type stock out of the drawer (manage=%s, module=%s)", async (manage, module) => {
    openConsumables(manage, module);
    expect(await screen.findByText("No consumables linked")).toBeVisible();
    expect(screen.queryByText("Drawer PLA")).not.toBeInTheDocument();
    expect(staffRequest.mock.calls.some(([path]) => path === poolPath(1))).toBe(false);
  });
});

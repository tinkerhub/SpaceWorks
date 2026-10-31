import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router-dom";
import type { Mock } from "vitest";

import type { PrinterPool } from "../../../generated/api";
import { staffRequest as realStaffRequest } from "../../../lib/api";
import type { Machine, MachineStatus, MachineType } from "../machinesApi";
import { MachinesPanel } from "./MachinesPanel";
import { machineConsoleTestClient, machineTestMakerspaces } from "./machine/machineConsoleTestUtils";

/* Shared fixtures for the MachinesPanel test files. Each test file mocks `lib/api` itself
   (vi.mock is per file), so the import above resolves to that file's mock. */
const staffRequest = realStaffRequest as unknown as Mock;

export const laserType: MachineType = {
  id: 1, slug: "laser", name: "Laser cutters", icon: "✦", is_builtin: false,
  managing_action: "manage_machines", makerspace: 1, can_create_machine: true,
  capability_config: { metering_unit: "length", requires_booking: false },
};
export const printerType: MachineType = {
  id: 2, slug: "3d_printer", name: "3D printers", icon: "", is_builtin: true,
  managing_action: "manage_printing", makerspace: null, can_create_machine: false,
  capability_config: { metering_unit: "weight", requires_booking: false },
};

export function machine(id: number, name: string, type = laserType, status: MachineStatus = "idle"): Machine {
  return {
    id, makerspace: 1, machine_type: type, name, location: "Lab", notes: "", status,
    firmware_version: "", camera_feed_url: "", image_url: null, warranty_status: "unknown",
    is_public: true, is_active: true, usage_hours: "0", can_operate: true, can_edit: true,
    can_delegate: true, can_retire: true, can_unretire: false, can_manage: true,
    created_at: "", updated_at: "",
  };
}

export function pool(
  id: number,
  material: string,
  machineId: number | null,
  unit: PrinterPool["unit"] = "millimeters",
  machineTypeId: number | null = null,
): PrinterPool {
  return {
    id, machine_id: machineId, machine_type_id: machineTypeId, material, color: "", brand: "", unit,
    initial_grams: "100", remaining_grams: "80", is_active: true, created_at: "", updated_at: "",
  };
}

export type Setup = {
  types?: MachineType[];
  machines?: Machine[];
  pools?: PrinterPool[];
  requests?: Record<string, unknown[]>;
  /** Extra pages keyed by `?page=N`, for the paginated-fleet test. */
  machinePages?: Record<string, { count: number; next: string | null; results: Machine[] }>;
};

function mockApi(setup: Setup) {
  const types = setup.types ?? [laserType];
  const rows = setup.machines ?? [];
  const pools = setup.pools ?? [];
  const requests = setup.requests ?? {};
  staffRequest.mockImplementation(async (path: string, options?: RequestInit) => {
    if (!path) return [];
    if (path === "/admin/makerspaces") return machineTestMakerspaces();
    if (options?.method === "POST" && path.endsWith("/machines")) return { id: 99 };
    if (path.endsWith("/machine-types")) return types;
    if (path.includes("/machines?page=")) {
      const page = new URLSearchParams(path.split("?")[1]).get("page") ?? "";
      return setup.machinePages?.[page] ?? { count: rows.length, next: null, results: [] };
    }
    if (path.endsWith("/machines")) {
      return setup.machinePages?.["1"] ?? { count: rows.length, next: null, results: rows };
    }
    if (path.includes("machine-service-report")) return { printer_metrics: [] };
    if (path.includes("machine-service/requests")) {
      // The consoles filter by the stable machine-type ID (a slug is not unique across the
      // global/tenant split), so resolve it back to the slug the fixtures are keyed by.
      const params = new URLSearchParams(path.split("?")[1]);
      const typeId = Number(params.get("machine_type_id"));
      const slug = types.find((type) => type.id === typeId)?.slug
        ?? params.get("machine_type")
        ?? "";
      return requests[slug] ?? [];
    }
    if (path.includes("typed-manual-usage")) return [];
    if (path.endsWith("machine-service/consumable-pools")) return pools;
    return [];
  });
}

export function renderPanel(
  setup: Setup = {},
  props: Partial<ComponentProps<typeof MachinesPanel>> = {},
  route = "/admin/machines",
) {
  mockApi(setup);
  const client = machineConsoleTestClient();
  // A REAL router, not a location stub: the panel resolves its selected machine type from
  // the URL and navigates with `<Link>`/`<Navigate>`, and a stub that only fakes
  // `window.location` passes against code that never reads router context at all.
  return render(
    <MemoryRouter initialEntries={[route]}>
      <QueryClientProvider client={client}>
        <MachinesPanel makerspaceId={1} canManage canConfigureMachineTypes={false} maintenanceEnabled={false} machineServiceEnabled printingEnabled delegatedRecipientRulesEnabled={false} {...props} />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

/** Status, machine and pool pickers are listboxes (a trigger + options), not native selects. */
export function openOptions(combobox: string) {
  fireEvent.click(screen.getByRole("combobox", { name: combobox }));
  return within(screen.getByRole("listbox"));
}

export function closeOptions() {
  fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
}

export function pick(combobox: string, option: string | RegExp) {
  fireEvent.click(openOptions(combobox).getByRole("option", { name: option }));
}

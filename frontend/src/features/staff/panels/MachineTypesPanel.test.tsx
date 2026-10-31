import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MachineTypesPanel } from "./MachineTypesPanel";
import { isolateMachineTestSession } from "./machine/machineConsoleTestUtils";

isolateMachineTestSession();

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../../lib/api")>(),
  staffRequest,
}));

const customType = {
  id: 4,
  slug: "laser-cutter",
  name: "Laser cutter",
  icon: "",
  is_builtin: false,
  managing_action: "",
  makerspace: 7,
  capability_config: {
    metering_unit: "count",
    requires_booking: false,
    accepted_materials: ["Plywood"],
    accepted_colours: ["Clear"],
  },
};

function renderPanel(canConfigure = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MachineTypesPanel makerspaceId={7} canConfigureMachineTypes={canConfigure} />
    </QueryClientProvider>,
  );
}

let modules: string[] = [];

beforeEach(() => {
  modules = ["machines", "payments", "bookings"];
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) => {
    if (path === "/admin/makerspaces") return Promise.resolve([{ id: 7, name: "Lab", slug: "lab", enabled_modules: modules }]);
    if (path.endsWith("machine-type-pricing")) return Promise.resolve({ currency: "INR", results: [] });
    if (path.endsWith("machine-types")) return Promise.resolve([customType]);
    return Promise.resolve(customType);
  });
});

describe("MachineTypesPanel capability presets", () => {
  it("rejects blank and case-insensitive duplicate entries before creation", async () => {
    renderPanel();
    fireEvent.click(await screen.findByText("Machine types and pricing"));
    const createButton = await screen.findByRole("button", { name: "Create type" });
    const createForm = createButton.closest("form");
    expect(createForm).not.toBeNull();
    const form = within(createForm!);

    fireEvent.click(form.getByRole("button", { name: "Add material" }));
    expect(form.getByRole("alert")).toHaveTextContent("Material cannot be blank.");

    fireEvent.change(form.getByRole("textbox", { name: "New material" }), { target: { value: "Acrylic" } });
    fireEvent.click(form.getByRole("button", { name: "Add material" }));
    fireEvent.change(form.getByRole("textbox", { name: "New material" }), { target: { value: "acrylic" } });
    fireEvent.click(form.getByRole("button", { name: "Add material" }));

    expect(form.getByRole("alert")).toHaveTextContent("Material already exists.");
    expect(form.getByRole("button", { name: "Remove material Acrylic" })).toBeVisible();
  });

  it("omits a preset key when the custom type list is emptied", async () => {
    renderPanel();
    fireEvent.click(await screen.findByText("Machine types and pricing"));
    const saveButton = await screen.findByRole("button", { name: "Save type" });
    const editForm = saveButton.closest("form");
    expect(editForm).not.toBeNull();
    const form = within(editForm!);

    fireEvent.click(form.getByRole("button", { name: "Remove material Plywood" }));
    fireEvent.click(saveButton);

    await waitFor(() => {
      const updateCall = staffRequest.mock.calls.find(([, options]) => options?.method === "PATCH");
      expect(updateCall).toBeDefined();
      const body = JSON.parse(updateCall![1].body);
      expect(body.capability_config).not.toHaveProperty("accepted_materials");
      expect(body.capability_config.accepted_colours).toEqual(["Clear"]);
    });
  });
});

describe("MachineTypesPanel for machine staff", () => {
  it("lets them price the types they manage but not switch online payment", async () => {
    staffRequest.mockImplementation((path: string) => {
      if (path === "/admin/makerspaces") return Promise.resolve([{ id: 7, name: "Lab", slug: "lab", enabled_modules: modules }]);
      if (path.endsWith("machine-type-pricing")) {
        return Promise.resolve({ currency: "INR", results: [{ machine_type_id: 4, rate_per_unit: "3.00", flat_fee: "0.00", payment_enabled: false, free_below_quantity: "0.00" }] });
      }
      if (path.endsWith("machine-types")) return Promise.resolve([customType]);
      return Promise.resolve(customType);
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MachineTypesPanel makerspaceId={7} canConfigureMachineTypes={false} canEditPricing />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByText("Machine types and pricing"));
    expect(await screen.findByRole("button", { name: "Save pricing" })).toBeVisible();
    expect(screen.getByText("Free below (items)")).toBeInTheDocument();
    expect(screen.queryByText("Enable payment")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save type" })).toBeNull();
    expect(screen.getByText(/You can set pricing for the machine types you manage/)).toBeVisible();
  });

  it("shows no pricing for a type outside their scope", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MachineTypesPanel makerspaceId={7} canConfigureMachineTypes={false} canEditPricing />
      </QueryClientProvider>,
    );
    fireEvent.click(await screen.findByText("Machine types and pricing"));
    await waitFor(() => expect(staffRequest.mock.calls.some(([path]) => String(path).endsWith("machine-type-pricing"))).toBe(true));
    expect(await screen.findByText("Laser cutter")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save pricing" })).toBeNull();
  });
});

describe("MachineTypesPanel pricing save", () => {
  it("cannot save before the stored pricing has loaded", async () => {
    staffRequest.mockImplementation((path: string) => {
      if (path === "/admin/makerspaces") return Promise.resolve([{ id: 7, name: "Lab", slug: "lab", enabled_modules: modules }]);
      if (path.endsWith("machine-type-pricing")) return new Promise(() => undefined);
      if (path.endsWith("machine-types")) return Promise.resolve([customType]);
      return Promise.resolve(customType);
    });
    renderPanel();
    fireEvent.click(await screen.findByText("Machine types and pricing"));
    // Saving now would overwrite the stored row with the zero placeholders.
    expect(await screen.findByRole("button", { name: "Save pricing" })).toBeDisabled();
  });
});

describe("MachineTypesPanel without payments or bookings", () => {
  it("keeps prices for manual usage but drops online charging and the booking flag", async () => {
    modules = ["machines", "machine_service"];
    renderPanel();

    fireEvent.click(await screen.findByText("Machine types and pricing"));
    expect(await screen.findByRole("button", { name: "Save type" })).toBeVisible();
    expect(await screen.findByRole("button", { name: "Save pricing" })).toBeVisible();
    expect(screen.queryByText("Enable payment")).toBeNull();
    expect(screen.queryByText("Requires booking")).toBeNull();
  });
});

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { closeOptions, laserType, machine, openOptions, pick, pool, printerType, renderPanel } from "./machinesPanelTestUtils";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", () => ({ staffRequest }));
vi.mock("./MachineTypesPanel", () => ({ MachineTypesPanel: () => null }));
vi.mock("./machine/MachineDrawer", () => ({ MachineDrawer: () => null }));

beforeEach(() => {
  staffRequest.mockReset();
});

describe("MachinesPanel creation, consumables and service workflows", () => {
  it("creates consumables from a type page with that type scope", async () => {
    renderPanel({ types: [printerType], machines: [machine(2, "Printer One", printerType)] });
    await screen.findByText("Printer One", { selector: "strong" });

    fireEvent.change(screen.getByLabelText("Material"), { target: { value: "PLA" } });
    fireEvent.change(screen.getByLabelText("Initial quantity"), { target: { value: "1000" } });
    fireEvent.click(screen.getByRole("button", { name: "Add filament" }));

    await waitFor(() => {
      const createCall = staffRequest.mock.calls.find(([, options]) => options?.method === "POST" && String(options?.body).includes('"material":"PLA"'));
      expect(createCall).toBeDefined();
      expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({ machine_type_id: printerType.id, unit: "grams", is_public: true });
    });
  });

  it("offers shared pools plus only the selected machine's bound pool", async () => {
    const rows = [machine(1, "Laser One"), machine(2, "Laser Two")];
    const pools = [
      pool(1, "Shared acrylic", null),
      pool(2, "One acrylic", 1),
      pool(3, "Two acrylic", 2),
      pool(4, "All lasers acrylic", null, "millimeters", laserType.id),
      pool(5, "Printer-only PLA", null, "millimeters", printerType.id),
    ];
    renderPanel({ machines: rows, pools, requests: { laser: [{ id: 10, title: "Cut acrylic", status: "accepted", planned_quantity: "20", actual_consumed_quantity: "0" }] } });
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
    pick("Machine", "Laser One");

    const startPool = openOptions("Pool");
    expect(startPool.getByRole("option", { name: /Shared acrylic/ })).toBeInTheDocument();
    expect(startPool.getByRole("option", { name: /One acrylic/ })).toBeInTheDocument();
    expect(startPool.getByRole("option", { name: /All lasers acrylic/ })).toBeInTheDocument();
    expect(startPool.queryByRole("option", { name: /Two acrylic/ })).not.toBeInTheDocument();
    expect(startPool.queryByRole("option", { name: /Printer-only PLA/ })).not.toBeInTheDocument();
    closeOptions();

    pick("Manual usage machine", "Laser Two");
    const manualPool = openOptions("Manual usage pool");
    expect(manualPool.getByRole("option", { name: /Shared acrylic/ })).toBeInTheDocument();
    expect(manualPool.getByRole("option", { name: /Two acrylic/ })).toBeInTheDocument();
    expect(manualPool.getByRole("option", { name: /All lasers acrylic/ })).toBeInTheDocument();
    expect(manualPool.queryByRole("option", { name: /One acrylic/ })).not.toBeInTheDocument();
  });

  it("moves machine creation off the multi-type index and onto an authorized type page", async () => {
    const view = renderPanel({ types: [laserType, printerType] });
    await screen.findByRole("link", { name: /Laser cutters/ });

    expect(screen.queryByRole("button", { name: "Add machine" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Machine name")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Machine type")).not.toBeInTheDocument();

    view.unmount();
    renderPanel({ types: [laserType, printerType] }, {}, "/admin/machines/1-laser");

    fireEvent.click(await screen.findByRole("button", { name: "Add machine" }));
    expect(screen.getByLabelText("Machine name")).toBeInTheDocument();
    expect(screen.queryByLabelText("Machine type")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Laser cutters" })).toBeInTheDocument();
  });

  it("hides machine creation without explicit type authority or the manage gate", async () => {
    const deniedLaser = { ...laserType, can_create_machine: false };
    const denied = renderPanel({ types: [deniedLaser] });
    await screen.findByText("No machines are registered for this type.");
    expect(screen.queryByRole("button", { name: "Add machine" })).not.toBeInTheDocument();

    denied.unmount();
    renderPanel({ types: [laserType] }, { canManage: false });
    await screen.findByText("No machines are registered for this type.");
    expect(screen.queryByRole("button", { name: "Add machine" })).not.toBeInTheDocument();
  });

  it("pre-scopes printer creation, preserves its model, and refreshes the machine list", async () => {
    const creatablePrinter = { ...printerType, can_create_machine: true };
    renderPanel({ types: [creatablePrinter] });
    await screen.findByText("No machines are registered for this type.");

    fireEvent.click(screen.getByRole("button", { name: "Add machine" }));
    fireEvent.change(screen.getByLabelText("Machine name"), { target: { value: "  Printer One  " } });
    fireEvent.change(screen.getByLabelText("Printer model"), { target: { value: "  Prusa MK4  " } });
    fireEvent.click(screen.getByRole("button", { name: "Add 3D printers" }));

    await waitFor(() => {
      const createCall = staffRequest.mock.calls.find(([, options]) => options?.method === "POST" && String(options?.body).includes('"name":"Printer One"'));
      expect(createCall).toBeDefined();
      expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
        name: "Printer One",
        machine_type_id: printerType.id,
        type_payload: { model: "Prusa MK4" },
      });
      expect(staffRequest.mock.calls.filter(([path, options]) => String(path).endsWith("/machines") && !options?.method)).toHaveLength(2);
    });

    expect(screen.queryByLabelText("Machine type")).not.toBeInTheDocument();
  });

  // Drafts used to survive section COLLAPSE; with subpages the equivalent risk is
  // navigation. `useServiceDrafts` therefore lives in the container that stays mounted,
  // not in the type page which unmounts on every move.
  it("preserves a service action draft across navigation to the index and back", async () => {
    renderPanel(
      { types: [laserType, printerType], requests: { laser: [{ id: 10, title: "Cut acrylic", status: "in_progress", planned_quantity: "20", actual_consumed_quantity: "0" }] } },
      {},
      "/admin/machines/1-laser",
    );
    fireEvent.click(await screen.findByRole("button", { name: "Complete" }));
    fireEvent.change(screen.getByLabelText("Actual minutes"), { target: { value: "37" } });

    fireEvent.click(screen.getByRole("link", { name: /All machine types/ }));
    expect(screen.queryByLabelText("Actual minutes")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("link", { name: /Laser cutters/ }));

    expect(await screen.findByLabelText("Actual minutes")).toHaveValue("37");
  });
});

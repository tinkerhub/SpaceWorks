import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MachineType } from "../machinesApi";
import { laserType, machine, pool, printerType, renderPanel, type Setup } from "./machinesPanelTestUtils";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", () => ({ staffRequest }));
vi.mock("./MachineTypesPanel", () => ({ MachineTypesPanel: () => null }));
vi.mock("./machine/MachineDrawer", () => ({ MachineDrawer: () => null }));

beforeEach(() => {
  staffRequest.mockReset();
});

describe("MachinesPanel index and per-type subpages", () => {
  it("shows delegated maintenance recipients only when the switch is enabled", async () => {
    renderPanel({}, { maintenanceEnabled: true });
    expect(screen.queryByRole("heading", { name: "Who gets notified" })).not.toBeInTheDocument();

    renderPanel({}, { maintenanceEnabled: true, delegatedRecipientRulesEnabled: true });

    expect(await screen.findByRole("heading", { name: "Who gets notified" })).toBeVisible();
  });

  // A single reachable type renders ITS PAGE inline at the index URL rather than redirecting.
  // An unconditional redirect would make the index unreachable, and with it machine-type
  // configuration and the delegated recipient picker -- all of which the scoped
  // maintainer with one type is exactly the actor who needs them.
  it("renders the sole reachable type inline without hiding the index controls", async () => {
    renderPanel({ types: [laserType] });

    expect(await screen.findByText("No machines are registered for this type.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Add machine" }));
    expect(screen.getByLabelText("Machine name")).toBeInTheDocument();
    expect(screen.queryByLabelText("Machine type")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Printer model")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Laser cutters" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Shared consumables/ })).not.toBeInTheDocument();
  });

  it("renders a zero-machine reachable type and its service queue", async () => {
    renderPanel({ requests: { laser: [{ id: 10, title: "Cut acrylic", status: "pending", planned_quantity: "20", actual_consumed_quantity: "0" }] } });

    expect(await screen.findByText("No machines are registered for this type.")).toBeVisible();
    expect(await screen.findByText("Cut acrylic")).toBeVisible();
  });

  it("keeps service content mounted when the status filter removes every row", async () => {
    renderPanel({ machines: [machine(1, "Laser One")], requests: { laser: [{ id: 10, title: "Cut acrylic", status: "pending", planned_quantity: "20", actual_consumed_quantity: "0" }] } });
    expect(await screen.findByText("Cut acrylic")).toBeVisible();

    fireEvent.click(within(screen.getByRole("group", { name: "Filter by status" })).getByRole("button", { name: "Offline" }));

    expect(screen.getByText("No machines match the selected status.")).toBeVisible();
    expect(screen.getByText("Cut acrylic")).toBeVisible();
  });

  it("shows a bound pool only on its machine's type page", async () => {
    const setup: Setup = {
      types: [laserType, printerType],
      machines: [machine(1, "Laser One"), machine(2, "Printer One", printerType)],
      pools: [pool(2, "Printer PLA", 2, "grams")],
    };
    renderPanel(setup, {}, "/admin/machines/1-laser");
    await screen.findByText("Laser One", { selector: "strong" });
    expect(screen.queryByText(/Printer PLA/, { selector: "strong" })).not.toBeInTheDocument();

    renderPanel(setup, {}, "/admin/machines/2-3d_printer");

    expect(await screen.findByText("Printer One", { selector: "strong" })).toBeVisible();
    expect(screen.getAllByText(/Printer PLA/, { selector: "strong" }).length).toBeGreaterThan(0);
  });

  it("shows type-wide pools on their machine-type page", async () => {
    const typedPool = pool(4, "All-printer PLA", null, "grams", printerType.id);
    const setup: Setup = {
      types: [printerType],
      machines: [machine(2, "Printer One", printerType)],
      pools: [typedPool],
    };
    renderPanel(setup);

    expect(await screen.findByText("All-printer PLA", { selector: "strong" })).toBeVisible();
    expect(screen.getByText("Type-wide")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Shared consumables/ })).not.toBeInTheDocument();
  });

  it("mounts no service requests when machine_service is disabled", async () => {
    renderPanel({ types: [printerType, laserType] }, { machineServiceEnabled: false });
    await screen.findByRole("link", { name: /3D printers/ });

    // `/admin/makerspaces` is the module lookup, answered from the session cache in the app.
    await waitFor(() => expect(staffRequest.mock.calls.filter(([path]) => path && path !== "/admin/makerspaces")).toHaveLength(2));
    const paths = staffRequest.mock.calls.map(([path]) => String(path));
    expect(paths.filter((path) => path.includes("machine-service"))).toEqual([]);
    expect(paths.filter((path) => path.includes("typed-manual-usage"))).toEqual([]);
    expect(paths.filter((path) => path.includes("machine-service-report"))).toEqual([]);
  });

  it("fetches pools once and service data only for the open type", async () => {
    renderPanel({ types: [laserType, printerType] }, {}, "/admin/machines/1-laser");
    await screen.findByText("Service queue");
    await waitFor(() => expect(staffRequest.mock.calls.some(([path]) => String(path).includes("typed-manual-usage"))).toBe(true));
    const paths = staffRequest.mock.calls.map(([path]) => String(path));

    expect(paths.filter((path) => path.endsWith("machine-service/consumable-pools"))).toHaveLength(1);
    expect(paths.filter((path) => path.includes("machine-service/requests"))).toHaveLength(1);
    expect(paths.some((path) => path.includes(`machine_type_id=${printerType.id}`))).toBe(false);
    expect(paths.some((path) => path.includes("machine-service-report"))).toBe(false);
  });

  // A makerspace may legally create a LOCAL type slugged `3d_printer`. Backend printer
  // semantics require the GLOBAL type (`printer_capabilities.is_printer_type`), so matching
  // the slug alone mounts the printer console for a generic service.
  it("does not treat a makerspace-local type slugged 3d_printer as the built-in printer", async () => {
    const impostor: MachineType = { ...printerType, id: 3, makerspace: 1, name: "Shop printers", is_builtin: false };
    renderPanel({ types: [impostor], machines: [machine(1, "Shop A", impostor)] });

    expect(await screen.findByText("Service queue")).toBeVisible();
    expect(screen.queryByText("3D-printer queue")).not.toBeInTheDocument();
    expect(screen.queryByText("Printer reports")).not.toBeInTheDocument();
  });

  // The machine and machine-type requests are independent. If the type response omits a type
  // whose machines loaded fine, those machines must still appear -- and the type must still be
  // navigable, because the machines list is server-scoped too.
  it("still renders machines whose type is missing from the machine-type response", async () => {
    const nestedLaser = { ...laserType, can_create_machine: undefined };
    renderPanel({ types: [], machines: [machine(1, "Orphaned laser", nestedLaser)] });

    expect(await screen.findByText("Orphaned laser", { selector: "strong" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add machine" })).not.toBeInTheDocument();
  });

  // THE ID IS AUTHORITATIVE, THE SLUG IS DECORATION. Slug uniqueness is only scoped, so a
  // makerspace-local type may carry a global built-in's slug; resolving by slug has already
  // served one type's jobs under another on three shipped surfaces.
  it("selects the machine type by id even when the slug in the URL names another type", async () => {
    renderPanel(
      { types: [laserType, printerType], machines: [machine(1, "Laser One")] },
      {},
      "/admin/machines/1-3d_printer",
    );

    expect(await screen.findByText("Laser One", { selector: "strong" })).toBeVisible();
    expect(screen.queryByText("Printer reports")).not.toBeInTheDocument();
  });

  it("normalises an unreachable machine type back to the index", async () => {
    renderPanel({ types: [laserType, printerType] }, {}, "/admin/machines/999-ghost");

    // The index, not a denial page: a stale deep link is a bad bookmark, not an attempt to
    // reach something forbidden.
    expect(await screen.findByRole("link", { name: /Laser cutters/ })).toBeVisible();
    expect(await screen.findByRole("link", { name: /3D printers/ })).toBeVisible();
  });

  // Counts and status roll-ups are stated as fact on the index cards, so the fleet has to be
  // read in full. The backend pages at 200; consuming only the first page would print a
  // wrong number rather than an obviously truncated list.
  it("counts machines across every page of the fleet", async () => {
    const first = [machine(1, "Laser One"), machine(2, "Laser Two")];
    const second = [machine(3, "Laser Three", laserType, "running")];
    renderPanel({
      types: [laserType, printerType],
      machinePages: {
        "1": { count: 3, next: "http://api.example/admin/makerspace/1/machines?page=2", results: first },
        "2": { count: 3, next: null, results: second },
      },
    });

    expect(await screen.findByText("3 machines")).toBeVisible();
    expect(screen.getByText("1 running")).toBeVisible();
  });
});

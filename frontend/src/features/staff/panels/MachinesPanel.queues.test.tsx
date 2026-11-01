import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanUploadSession, held, http, json, release, resetUploadSession } from "../../../test/staffUploadHarness";
import { serviceJob, serviceMachine } from "../../../test/staffServiceOwnershipHarness";
import { machineKeys } from "../machinesApi";
import { mountQueuePanel, queueRead, queueTypes } from "./queueNavigationTestHarness";

beforeEach(() => resetUploadSession());
afterEach(() => cleanUploadSession());

describe("separate equipment and request pages", () => {
  it.each(["/admin", "/m/forge/admin"])("opens queue first and navigates back to equipment and its drawer under %s", async (base) => {
    http(queueRead);
    mountQueuePanel(`${base}/machines/1-press/queue`, { makerspaceSlug: base === "/admin" ? null : "forge" });
    await screen.findByText("Job A", { exact: true });
    expect(screen.getAllByRole("heading")[0]).toHaveTextContent("Presses requests");
    expect(screen.getAllByRole("heading")[1]).toHaveTextContent("Service queue");
    expect(screen.queryByRole("table", { name: "Machine list" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add machine" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Material")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Initial quantity")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Machines & stock" }));
    expect(await screen.findByRole("button", { name: "Machine 11" })).toBeVisible();
    expect(screen.getByLabelText("Material")).toBeVisible();
    expect(screen.queryByText("Job A", { exact: true })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add machine" }));
    expect(await screen.findByLabelText("Machine name")).toBeVisible();
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Machine 11" }));
    const drawer = await screen.findByRole("dialog", { name: "Machine 11" });
    expect(within(drawer).getByRole("tab", { name: "Overview" })).toBeVisible();
  });

  it.each([
    { canManage: false }, { machineServiceEnabled: false },
    { printingEnabled: false },
  ])("direct unavailable queues expose equipment without fetching forbidden service data: %j", async (gates) => {
    const printer = "printingEnabled" in gates;
    const type = queueTypes[printer ? 1 : 0];
    const net = http(queueRead);
    mountQueuePanel(`/admin/machines/${type.id}-${type.slug}/queue`, gates);
    expect(await screen.findByText("Requests unavailable")).toBeVisible();
    expect(screen.queryByRole("link", { name: "Requests" })).not.toBeInTheDocument();
    expect(net.calls.filter((call) => /machine-service|typed-manual-usage/.test(call.path))).toEqual([]);
    fireEvent.click(screen.getAllByRole("link", { name: "Machines & stock" })[0]);
    expect(await screen.findByRole("button", { name: `Machine ${printer ? 12 : 11}` })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Requests" })).not.toBeInTheDocument();
    if (!printer) expect(net.calls.filter((call) => /machine-service|typed-manual-usage/.test(call.path))).toEqual([]);
  });

  it("uses the ID for tenant and built-in types with an equal slug", async () => {
    const tenant = { ...queueTypes[0], id: 13, slug: "3d_printer", name: "Tenant printer" };
    const net = http((call) => call.path.endsWith("/machine-types") ? json([queueTypes[1], tenant]) : queueRead(call));
    mountQueuePanel("/admin/machines/13-3d_printer/queue", { printingEnabled: false });
    expect(await screen.findByRole("heading", { name: "Service queue" })).toBeVisible();
    await screen.findByText("Job A", { exact: true });
    expect(screen.queryByRole("heading", { name: "3D-printer queue" })).not.toBeInTheDocument();
    expect(net.calls.filter((call) => call.path.includes("/requests?")).map((call) => call.path))
      .toEqual(["/admin/makerspaces/1/machine-service/requests?machine_type_id=13"]);
  });

  it("leaves the sole type equipment and Setup reachable at the index", async () => {
    http((call) => call.path.endsWith("/machine-types") ? json([queueTypes[0]])
      : call.path.endsWith("/machines") ? json({ count: 1, next: null, results: [serviceMachine(queueTypes[0])] }) : queueRead(call));
    mountQueuePanel("/admin/machines");
    await screen.findByRole("button", { name: "Machine 11" });
    expect(screen.getByRole("heading", { name: "Setup" })).toBeVisible();
    expect(screen.getByLabelText("Current path")).toHaveTextContent(/^\/admin\/machines$/);
    fireEvent.click(screen.getByRole("link", { name: "Requests" }));
    await screen.findByText("Job A", { exact: true });
    fireEvent.click(screen.getByRole("link", { name: "All machine types" }));
    expect(await screen.findByRole("heading", { name: "Setup" })).toBeVisible();
  });
});

describe("unreachable queue resolution", () => {
  it.each(["/admin", "/m/forge/admin"])("normalizes an unreachable ID after successful reads under %s", async (base) => {
    http(queueRead);
    mountQueuePanel(`${base}/machines/999-stale/queue`, { makerspaceSlug: base === "/admin" ? null : "forge" });
    await screen.findByRole("link", { name: /Presses/ });
    expect(screen.getByLabelText("Current path")).toHaveTextContent(`${base}/machines`);
    expect(screen.getByLabelText("Current path")).not.toHaveTextContent("999");
  });

  it.each([
    { source: "machines", fail: false }, { source: "machines", fail: true },
    { source: "types", fail: false }, { source: "types", fail: true },
  ])("does not redirect while $source is loading or after a read error=$fail", async ({ source, fail }) => {
    const response = held<Response>();
    let retry = false;
    const endpoint = source === "machines" ? "/machines" : "/machine-types";
    http((call) => call.path.endsWith(endpoint) && !retry ? response.promise : queueRead(call));
    const view = mountQueuePanel("/admin/machines/999-stale/queue");
    expect(await screen.findByText("Loading machine type")).toBeInTheDocument();
    expect(screen.getByLabelText("Current path")).toHaveTextContent("999-stale/queue");
    await release(response, fail ? json({ detail: "Machine data temporarily unavailable" }, 503)
      : source === "types" ? json(queueTypes) : json({ count: 1, next: null, results: [serviceMachine(queueTypes[0])] }));
    if (fail) {
      await waitFor(() => expect(view.client.getQueryState(source === "machines" ? machineKeys.list(1) : machineKeys.types(1))?.status).toBe("error"));
      expect(screen.queryByText("Loading machine type")).not.toBeInTheDocument();
      expect(screen.getByText("Could not load machine type")).toBeVisible();
      expect(screen.getByLabelText("Current path")).toHaveTextContent("999-stale/queue");
      retry = true;
      fireEvent.click(screen.getByRole("button", { name: "Retry machine data" }));
      await screen.findByRole("link", { name: /Presses/ });
      expect(screen.getByLabelText("Current path")).toHaveTextContent(/^\/admin\/machines$/);
    } else {
      await screen.findByRole("link", { name: /Presses/ });
      expect(screen.getByLabelText("Current path")).toHaveTextContent(/^\/admin\/machines$/);
    }
  });

  it("resolves a queue type from nested machine data after the type list omits it", async () => {
    const machines = held<Response>();
    http((call) => call.path.endsWith("/machine-types") ? json([])
      : call.path.endsWith("/machines") ? machines.promise : queueRead(call));
    mountQueuePanel();
    await screen.findByText("Loading machine type");
    await release(machines, json({ count: 1, next: null, results: [serviceMachine(queueTypes[0])] }));
    expect(await screen.findByText(serviceJob().title, { exact: true })).toBeVisible();
    expect(screen.getByLabelText("Current path")).toHaveTextContent("/admin/machines/1-press/queue");
  });
});

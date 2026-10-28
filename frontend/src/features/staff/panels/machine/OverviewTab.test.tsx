import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { machineKeys, type Machine } from "../../machinesApi";
import { OverviewTab } from "./OverviewTab";
import { testMachine } from "./machineTestFixtures";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../../lib/api", () => ({ staffRequest }));
vi.mock("../../ImageUploader", () => ({ ImageUploader: () => null }));
vi.mock("../MachinePublicSettings", () => ({ MachinePublicSettings: () => null }));

function overview(machine: Machine) {
  return <OverviewTab machine={machine} makerspaceId={1} canManageMachines canEdit canOperate canRetire={false} canUnretire={false} />;
}

function renderOverview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}>{overview(testMachine)}</QueryClientProvider>);
  return { ...view, client, refresh: (machine: Machine) => view.rerender(
    <QueryClientProvider client={client}>{overview(machine)}</QueryClientProvider>,
  ) };
}

beforeEach(() => { staffRequest.mockReset(); });

function chooseStatus(label: string) {
  fireEvent.click(screen.getByRole("combobox", { name: "Machine status" }));
  fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: label }));
}

describe("OverviewTab separate status and details saves", () => {
  it("keeps a status draft through unrelated refreshes and blocks both details click and submit", () => {
    const view = renderOverview();
    const details = screen.getByRole("button", { name: "Save machine details" });
    chooseStatus("Maintenance");
    expect(screen.getByRole("status")).toHaveTextContent("Unsaved status change");
    expect(details).toBeDisabled();
    view.refresh({ ...testMachine, usage_hours: "5", notes: "Refetched note" });
    expect(screen.getByRole("combobox", { name: "Machine status" })).toHaveTextContent("Maintenance");
    fireEvent.click(details);
    fireEvent.submit(details.closest("form")!);
    expect(staffRequest).not.toHaveBeenCalled();
    chooseStatus("Idle");
    expect(details).toBeEnabled();
    expect(screen.queryByText(/Unsaved status change/)).not.toBeInTheDocument();
  });

  it("sends the requested status, adopts the authoritative result and refreshes all machine caches", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    client.setQueryData(machineKeys.detail(41), testMachine);
    client.setQueryData(machineKeys.list(1), { count: 1, results: [testMachine], next: null, previous: null });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    let resolveStatus!: (value: Machine) => void;
    staffRequest.mockReturnValue(new Promise<Machine>((resolve) => { resolveStatus = resolve; }));
    function CachedOverview() {
      const query = useQuery({ queryKey: machineKeys.detail(41), queryFn: async () => testMachine, enabled: false });
      return overview(query.data!);
    }
    render(<QueryClientProvider client={client}><CachedOverview /></QueryClientProvider>);
    chooseStatus("Maintenance");
    fireEvent.click(screen.getByRole("button", { name: "Set status" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/machines/41/set-status", {
      method: "POST", body: JSON.stringify({ status: "maintenance" }),
    }));
    expect(screen.getByRole("button", { name: "Save machine details" })).toBeDisabled();
    fireEvent.submit(screen.getByRole("button", { name: "Save machine details" }).closest("form")!);
    expect(staffRequest).toHaveBeenCalledTimes(1);
    resolveStatus({ ...testMachine, status: "offline" });
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Machine status" })).toHaveTextContent("Offline"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save machine details" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "Set status" })).toBeDisabled();
    expect(screen.queryByText(/Unsaved status change/)).not.toBeInTheDocument();
    expect(client.getQueryData<Machine>(machineKeys.detail(41))?.status).toBe("offline");
    expect(client.getQueryData<{ results: Machine[] }>(machineKeys.list(1))?.results[0].status).toBe("offline");
    for (const queryKey of [machineKeys.detail(41), machineKeys.list(1), ["machine-public-preview", 41], ["public-machines"]]) {
      expect(invalidate).toHaveBeenCalledWith({ queryKey });
    }
  });

  it("saves editable details without carrying status or lifecycle fields", async () => {
    staffRequest.mockResolvedValue(testMachine);
    renderOverview();
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "  Renamed printer  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save machine details" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/admin/machines/41", {
      method: "PATCH", body: JSON.stringify({ name: "Renamed printer", location: "Bench", notes: "", firmware_version: "", camera_feed_url: "" }),
    }));
  });
});

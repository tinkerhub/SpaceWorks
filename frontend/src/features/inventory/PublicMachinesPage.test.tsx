import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { genericType, printerType } from "../machineService/serviceTestFixtures";

const { tenantPublicRequest, fetchServiceTypes, state } = vi.hoisted(() => ({
  tenantPublicRequest: vi.fn(), fetchServiceTypes: vi.fn(), state: { modules: ["machines", "machine_service", "printing"] },
}));
vi.mock("../../lib/api", async () => ({ ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest }));
vi.mock("../machineService/publicApi", async () => ({ ...await vi.importActual<typeof import("../machineService/publicApi")>("../machineService/publicApi"), fetchServiceTypes }));
vi.mock("../../lib/modules", () => ({ useModules: () => ({ moduleEnabled: (key: string) => state.modules.includes(key) }) }));
vi.mock("./useMakerspacePublic", () => ({ useMakerspacePublic: () => ({
  makerspaceSlug: "forge", header: { homePath: "/m/forge", name: "Forge" },
  tenantPath: (path = "") => `/m/forge${path ? `/${path}` : ""}`,
}) }));
import { PublicMachinesPage } from "./PublicMachinesPage";

const machine = (name: string, id: number, typeName = "Laser cutter") => ({
  name, machine_type: { id, name: typeName, icon: "" }, status: "idle", image_url: null, usage_hours: "0",
});
function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter><PublicMachinesPage /></MemoryRouter></QueryClientProvider>);
}
beforeEach(() => {
  state.modules = ["machines", "machine_service", "printing"];
  fetchServiceTypes.mockReset().mockResolvedValue([genericType, { ...genericType, id: 33 }, printerType]);
  tenantPublicRequest.mockReset().mockImplementation((_slug: string, path: string) => Promise.resolve(path.endsWith("page=1")
    ? { count: 4, results: [machine("Laser A", 11), machine("Laser B", 11)], next: "https://api.test/machines?page=2" }
    : { count: 4, results: [machine("Different type, same name", 33), machine("Printer", 22, "3D Printer")], next: null }));
});

describe("public machines grouping and service links", () => {
  it("walks all machine pages and groups same-name different types by id with separate CTAs", async () => {
    renderPage();
    expect(await screen.findByText("Different type, same name")).toBeVisible();
    const groups = screen.getAllByRole("button", { name: /Laser cutter/ });
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent("2 items");
    expect(groups[1]).toHaveTextContent("1 item");
    const links = screen.getAllByRole("link", { name: "Request service for Laser cutter" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["/m/forge/machine-service?type=11", "/m/forge/machine-service?type=33"]);
    fireEvent.click(groups[0]);
    expect(screen.queryByText("Laser A")).not.toBeInTheDocument();
    expect(screen.getByText("Different type, same name")).toBeVisible();
    expect(tenantPublicRequest.mock.calls.map((call) => call[1])).toEqual(["/public/forge/machines?page=1", "/public/forge/machines?page=2"]);
  });

  it.each(["machines", "machine_service"])("hides service navigation and cached group CTAs when %s is off", async (module) => {
    state.modules = state.modules.filter((key) => key !== module);
    renderPage();
    await screen.findByText("Laser A");
    expect(screen.queryByRole("link", { name: /Request service/i })).not.toBeInTheDocument();
    expect(fetchServiceTypes).not.toHaveBeenCalled();
  });

  it("hides the printer group CTA when printing is off while retaining generic requests", async () => {
    state.modules = ["machines", "machine_service"];
    renderPage();
    await screen.findByText("Printer");
    await waitFor(() => expect(screen.getAllByRole("link", { name: "Request service for Laser cutter" })).toHaveLength(2));
    expect(screen.queryByRole("link", { name: "Request service for 3D Printer" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Main navigation" })).getByRole("link", { name: "Service requests" })).toHaveAttribute("href", "/m/forge/machine-service");
  });
});

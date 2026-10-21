import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useTenant, bootstrapTenant } = vi.hoisted(() => ({ useTenant: vi.fn(), bootstrapTenant: vi.fn() }));

vi.mock("./lib/tenant", async () => {
  const actual = await vi.importActual<typeof import("./lib/tenant")>("./lib/tenant");
  return { ...actual, useTenant };
});
vi.mock("./lib/api", async () => {
  const actual = await vi.importActual<typeof import("./lib/api")>("./lib/api");
  return { ...actual, bootstrapTenant };
});
// Stand-ins: these tests are about whether a page MOUNTS, not what it renders.
vi.mock("./features/inventory/PublicEventsPage", () => ({ PublicEventsPage: () => <p>events-page</p> }));
vi.mock("./features/inventory/PublicEventFeedbackPage", () => ({ PublicEventFeedbackPage: () => <p>feedback-page</p> }));
vi.mock("./features/inventory/PublicMachinesPage", () => ({ PublicMachinesPage: () => <p>machines-page</p> }));
vi.mock("./features/bookings/PublicBookingsPage", () => ({ PublicBookingsPage: () => <p>bookings-page</p> }));
vi.mock("./features/printing/PublicPrintRequestPage", () => ({ PublicPrintRequestPage: () => <p>print-page</p> }));

import { AppRoutes } from "./AppRoutes";

const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"];
const PAGES: [string, string, string][] = [
  ["events", "events", "events-page"],
  ["events/abc/feedback", "events", "feedback-page"],
  ["machines", "machines", "machines-page"],
  ["bookings", "bookings", "bookings-page"],
  ["print", "printing", "print-page"],
];

const central = { mode: "central", loading: false, error: null, bootstrap: null, slug: "", makerspaceId: null, modules: new Set() };
const single = (modules: string[]) => ({
  mode: "single", loading: false, error: null, bootstrap: { modules }, slug: "forge", makerspaceId: 7, modules: new Set(modules),
});

function renderAt(path: string, mode: "central" | "single") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppRoutes mode={mode} landing={<p>landing</p>} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useTenant.mockReset();
  bootstrapTenant.mockReset();
});

describe("public module pages on the central deployment", () => {
  it.each(PAGES)("/m/forge/%s is a 404 with core modules only", async (subpath, _module, page) => {
    useTenant.mockReturnValue(central);
    bootstrapTenant.mockResolvedValue({ makerspace: { slug: "forge" }, modules: CORE });
    renderAt(`/m/forge/${subpath}`, "central");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(screen.queryByText(page)).not.toBeInTheDocument();
    expect(bootstrapTenant).toHaveBeenCalledWith({ slug: "forge" });
  });

  it.each(PAGES)("/m/forge/%s mounts once %s is on", async (subpath, module, page) => {
    useTenant.mockReturnValue(central);
    bootstrapTenant.mockResolvedValue({ makerspace: { slug: "forge" }, modules: [...CORE, module] });
    renderAt(`/m/forge/${subpath}`, "central");
    expect(await screen.findByText(page)).toBeInTheDocument();
  });

  it("fails closed while the makerspace's modules are loading", () => {
    useTenant.mockReturnValue(central);
    bootstrapTenant.mockReturnValue(new Promise(() => {}));
    renderAt("/m/forge/events", "central");
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.queryByText("events-page")).not.toBeInTheDocument();
  });
});

describe("public module pages on a single-tenant deployment", () => {
  it.each(PAGES)("/%s follows the runtime tenant's modules", (subpath, module, page) => {
    useTenant.mockReturnValue(single(CORE));
    const off = renderAt(`/${subpath}`, "single");
    expect(screen.getByText("Page not found")).toBeInTheDocument();
    off.unmount();

    useTenant.mockReturnValue(single([...CORE, module]));
    renderAt(`/${subpath}`, "single");
    expect(screen.getByText(page)).toBeInTheDocument();
    expect(bootstrapTenant).not.toHaveBeenCalled();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useTenant, bootstrapTenant } = vi.hoisted(() => ({ useTenant: vi.fn(), bootstrapTenant: vi.fn() }));

vi.mock("../lib/tenant", async () => {
  const actual = await vi.importActual<typeof import("../lib/tenant")>("../lib/tenant");
  return { ...actual, useTenant };
});
vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, bootstrapTenant };
});

import { NotFoundPage } from "./NotFoundPage";

const central = { mode: "central", loading: false, error: null, bootstrap: null, slug: "", makerspaceId: null, modules: new Set() };

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useTenant.mockReset();
  bootstrapTenant.mockReset();
});

describe("NotFoundPage", () => {
  it("sends a platform visitor back to the home page", () => {
    useTenant.mockReturnValue(central);
    renderAt("/nowhere");
    expect(screen.getByRole("heading", { level: 1, name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("button", { name: "Go back" })).toBeInTheDocument();
    expect(bootstrapTenant).not.toHaveBeenCalled();
  });

  it("keeps a makerspace's header and links back to its inventory", async () => {
    useTenant.mockReturnValue(central);
    bootstrapTenant.mockResolvedValue({
      makerspace: { slug: "forge", name: "Forge" },
      branding: {},
      modules: ["public_inventory"],
    });
    renderAt("/m/forge/events");
    expect(await screen.findByRole("link", { name: "Forge home" })).toHaveAttribute("href", "/m/forge");
    expect(screen.getByRole("link", { name: "Back to the inventory" })).toHaveAttribute("href", "/m/forge");
    expect(screen.getByRole("link", { name: "All makerspaces" })).toHaveAttribute("href", "/");
    expect(bootstrapTenant).toHaveBeenCalledWith({ slug: "forge" });
  });

  it("falls back to the platform header for a makerspace that does not exist", async () => {
    useTenant.mockReturnValue(central);
    bootstrapTenant.mockRejectedValue(new Error("Not found"));
    renderAt("/m/ghost/print");
    expect(await screen.findByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
  });

  it("links a single-tenant visitor to the inventory at the root", () => {
    useTenant.mockReturnValue({
      mode: "single", loading: false, error: null, slug: "forge", makerspaceId: 7,
      bootstrap: { makerspace: { name: "Forge", slug: "forge" }, branding: {}, modules: ["public_inventory"] },
      modules: new Set(["public_inventory"]),
    });
    renderAt("/machines");
    expect(screen.getByRole("link", { name: "Back to the inventory" })).toHaveAttribute("href", "/");
    expect(screen.queryByRole("link", { name: "All makerspaces" })).not.toBeInTheDocument();
    expect(bootstrapTenant).not.toHaveBeenCalled();
  });
});

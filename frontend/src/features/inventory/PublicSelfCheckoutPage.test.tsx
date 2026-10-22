/**
 * Self-checkout is offered only where the backend can serve it: on the `checked_in`
 * policy (roster identity, no account), or with the `membership` module on (member,
 * waiver, presence). Anywhere else the feature flag alone would render a form whose
 * every submit is refused, so the page says it is unavailable instead.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { useMakerspacePublic, useModules } = vi.hoisted(() => ({
  useMakerspacePublic: vi.fn(),
  useModules: vi.fn(),
}));

vi.mock("./useMakerspacePublic", () => ({ useMakerspacePublic }));
vi.mock("../../lib/modules", () => ({ useModules }));

import { PublicSelfCheckoutPage } from "./PublicSelfCheckoutPage";

function renderPage({ modules, requestAccess }: { modules: string[]; requestAccess?: "anyone" | "checked_in" }) {
  const set = new Set(modules);
  useModules.mockReturnValue({ loading: false, modules: set, moduleEnabled: (key: string) => set.has(key) });
  useMakerspacePublic.mockReturnValue({
    tenant: { mode: "central" },
    makerspaceSlug: "forge",
    tenantPath: () => "/m/forge",
    bootstrapQuery: { isLoading: false, isError: false },
    bootstrap: {
      makerspace: { id: 1, name: "Forge", slug: "forge", ...(requestAccess ? { request_access: requestAccess } : {}) },
      modules,
      features: ["inventory.self_checkout"],
    },
    displayName: "Forge",
    header: { homePath: "/m/forge", name: "Forge" },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PublicSelfCheckoutPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"];

describe("public self-checkout availability", () => {
  beforeEach(() => {
    useMakerspacePublic.mockReset();
    useModules.mockReset();
  });

  it("serves the roster form on a checked-in space with membership off", () => {
    renderPage({ modules: CORE, requestAccess: "checked_in" });

    expect(screen.getByLabelText(/your name, as it appears in tinkerhub/i)).toBeInTheDocument();
    expect(screen.queryByText(/not enabled/i)).not.toBeInTheDocument();
  });

  it("is unavailable with membership off and no check-in policy", () => {
    renderPage({ modules: CORE, requestAccess: "anyone" });

    expect(screen.getByText("Self-checkout is not enabled for this makerspace.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /scan qr/i })).not.toBeInTheDocument();
  });

  it("serves members when the membership module is on", () => {
    renderPage({ modules: [...CORE, "membership"] });

    expect(screen.queryByText(/not enabled/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/as it appears in tinkerhub/i)).not.toBeInTheDocument();
  });
});

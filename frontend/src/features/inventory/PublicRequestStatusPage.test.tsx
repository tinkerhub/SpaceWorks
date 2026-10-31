import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { StructuredApiError } from "../../lib/api";

const { useMakerspacePublic, useModules, fetchRequestStatus } = vi.hoisted(() => ({
  useMakerspacePublic: vi.fn(),
  useModules: vi.fn(),
  fetchRequestStatus: vi.fn(),
}));

vi.mock("./useMakerspacePublic", () => ({ useMakerspacePublic }));
vi.mock("../../lib/modules", () => ({ useModules }));
vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, fetchRequestStatus };
});

import { PublicRequestStatusPage } from "./PublicRequestStatusPage";

function renderPage(route = "/m/forge/request") {
  useModules.mockReturnValue({ loading: false, modules: new Set(), moduleEnabled: () => false });
  useMakerspacePublic.mockReturnValue({
    tenant: { mode: "central" },
    makerspaceSlug: "forge",
    tenantPath: () => "/m/forge",
    bootstrapQuery: { isLoading: false, isError: false },
    bootstrap: { makerspace: { id: 1, name: "Forge", slug: "forge" }, modules: [], features: [] },
    displayName: "Forge",
    header: { homePath: "/m/forge", name: "Forge" },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/m/:slug/request" element={<PublicRequestStatusPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("public request status lookup", () => {
  beforeEach(() => {
    fetchRequestStatus.mockReset();
  });

  it("looks up the token from the link and shows the status", async () => {
    fetchRequestStatus.mockResolvedValue({
      status: "accepted",
      created_at: "2026-10-20T10:00:00Z",
      rejection_reason: "",
      items: [{ product_name: "Logic analyzer", requested_quantity: 2 }],
    });
    renderPage("/m/forge/request?token=tok-1");

    expect(await screen.findByText("Accepted")).toBeInTheDocument();
    expect(fetchRequestStatus).toHaveBeenCalledWith("forge", "tok-1");
    expect(screen.getByText(/collect it from the desk/i)).toBeInTheDocument();
    expect(screen.getByText("Logic analyzer")).toBeInTheDocument();
    expect(screen.getByLabelText("Request reference")).toHaveValue("tok-1");
  });

  it("looks up a typed reference and says when nothing matches", async () => {
    fetchRequestStatus.mockRejectedValue(new StructuredApiError(404, { detail: "Not found." }));
    renderPage();

    expect(fetchRequestStatus).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Request reference"), { target: { value: " tok-2 " } });
    fireEvent.click(screen.getByRole("button", { name: "Check status" }));

    expect(await screen.findByText("No request matches that reference")).toBeInTheDocument();
    await waitFor(() => expect(fetchRequestStatus).toHaveBeenCalledWith("forge", "tok-2"));
  });

  it("separates a failed lookup from a missing request", async () => {
    fetchRequestStatus.mockRejectedValue(new StructuredApiError(503, {}));
    renderPage("/m/forge/request?token=tok-3");

    expect(await screen.findByText("Request status didn't load")).toBeInTheDocument();
  });

  it("shows generic Cancelled status without staff details or an action even if extra fields arrive", async () => {
    fetchRequestStatus.mockResolvedValue({
      status: "cancelled", created_at: "2026-10-20T10:00:00Z",
      items: [{ product_name: "Logic analyzer", requested_quantity: 2 }],
      // A hostile/over-broad response must not become a staff-detail presentation.
      cancellation_reason: "Private staff-only cancellation explanation",
      closed_by: { username: "private-reviewer", role: "Custom reviewer" },
      closed_at: "2026-10-21T12:34:56Z",
    });
    renderPage("/m/forge/request?token=cancelled-token");
    expect(await screen.findByText("Cancelled")).toBeVisible();
    expect(screen.getByText("This request has been cancelled.")).toBeVisible();
    expect(screen.getByText("Logic analyzer")).toBeVisible();
    expect(fetchRequestStatus).toHaveBeenCalledWith("forge", "cancelled-token");
    expect(screen.queryByText("Private staff-only cancellation explanation")).not.toBeInTheDocument();
    expect(screen.queryByText(/private-reviewer|Custom reviewer|Cancelled because|Cancelled by|Cancelled at/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /cancel/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /reason/i })).not.toBeInTheDocument();
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { ToastProvider } from "../../../components/ui";
import { MemberMachineScopeModal } from "./MemberMachineScopeModal";
import type { MemberMachineScope, StaffMembershipRow } from "./rolesApi";

const target: StaffMembershipRow = {
  id: 41,
  user: { id: 5, username: "ahmed", email: "", access_status: "active" },
  makerspace_id: 7,
  makerspace_slug: "forge",
  role: "custom",
  assigned_role: null,
  created_at: "2026-10-01T00:00:00Z",
};

const types = [
  { id: 1, label: "3D Printer", is_builtin: true },
  { id: 2, label: "Laser cutter", is_builtin: false },
  { id: 3, label: "CNC mill", is_builtin: true },
];

function scope(overrides: Partial<MemberMachineScope> = {}): MemberMachineScope {
  return {
    machine_type_ids: [2],
    role_machine_type_ids: [1],
    available_machine_types: types,
    scoping_applies: true,
    role_covers_all: false,
    ...overrides,
  };
}

function renderModal(onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <MemberMachineScopeModal target={target} onClose={onClose} />
      </ToastProvider>
    </QueryClientProvider>,
  );
  return onClose;
}

beforeEach(() => staffRequest.mockReset());

describe("MemberMachineScopeModal", () => {
  it("locks the role's types and saves only the personal selection", async () => {
    staffRequest.mockResolvedValue(scope());
    const onClose = renderModal();

    const printer = await screen.findByRole("checkbox", { name: /3D Printer/ });
    expect(printer).toBeChecked();
    expect(printer).toBeDisabled();
    expect(screen.getByText("Via role")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Laser cutter/ })).toBeChecked();

    fireEvent.click(screen.getByRole("checkbox", { name: /CNC mill/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Laser cutter/ }));
    fireEvent.click(screen.getByRole("button", { name: "Save machine types" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(staffRequest).toHaveBeenCalledWith("/admin/makerspaces/7/memberships/41/machine-scope", {
      method: "PUT",
      body: JSON.stringify({ machine_type_ids: [3] }),
    });
  });

  it("explains instead of offering boxes when the role lacks Machines", async () => {
    staffRequest.mockResolvedValue(scope({ scoping_applies: false }));
    renderModal();

    expect(await screen.findByText("Their role has no Machines capability")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save machine types" })).toBeNull();
  });

  it("says a role that covers everything needs no personal types", async () => {
    staffRequest.mockResolvedValue(scope({ scoping_applies: false, role_covers_all: true }));
    renderModal();

    expect(await screen.findByText("Covers every machine")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});

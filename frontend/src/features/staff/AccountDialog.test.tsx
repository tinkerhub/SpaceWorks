import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

import type { StaffAuthUser } from "../../lib/api";
import { StaffShell } from "./shell/StaffShell";

const spaceManager: StaffAuthUser & { email: string } = {
  username: "space-manager",
  email: "manager@lab.example",
  email_verified: false,
  role: "staff",
  is_superuser: false,
  must_change_password: false,
  makerspaces: [],
};

function renderHeader(onPasswordChanged = vi.fn(), onSignOut = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <StaffShell
          nav={{ activeTab: "", allowedTabs: [], guestOnly: false, singleTenantLocked: false }}
          account={{
            username: spaceManager.username,
            roleName: "Space Manager",
            makerspaces: [],
            selected: null,
            canSwitchMakerspace: false,
            canPickMakerspace: false,
            onPickMakerspace: vi.fn(),
            onSelectMakerspace: vi.fn(),
            onSignOut,
          }}
          publicPath={null}
          workspaceName="Inventory Control"
          user={spaceManager}
          onPasswordChanged={onPasswordChanged}
          onSelectTab={vi.fn()}
        >
          <p>panel</p>
        </StaffShell>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { onPasswordChanged, onSignOut };
}

// The account card opens a menu; its "Account" item opens the dialog once the menu closes.
async function openAccountDialog() {
  fireEvent.keyDown(screen.getByRole("button", { name: "space-manager, account menu" }), { key: "Enter" });
  fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Account" }));
  return screen.findByRole("dialog", { name: "Your account" });
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("staff account dialog", () => {
  it("lets a Space Manager open their account and change their own password", async () => {
    staffRequest.mockResolvedValue({ detail: "Password updated." });
    const { onPasswordChanged } = renderHeader();

    expect(screen.getByRole("button", { name: "space-manager, account menu" })).toHaveAttribute("aria-haspopup", "menu");
    const dialog = await openAccountDialog();
    expect(within(dialog).getByRole("heading", { name: "Change password" })).toBeInTheDocument();
    // No verification chip: staff have no verification flow to act on. The address shows,
    // because that is where a forgotten-password code goes.
    expect(within(dialog).getByText("manager@lab.example")).toBeInTheDocument();
    expect(within(dialog).queryByText(/verified/i)).not.toBeInTheDocument();

    fireEvent.change(within(dialog).getByLabelText("Current password"), { target: { value: "old-password" } });
    fireEvent.change(within(dialog).getByLabelText("New password"), { target: { value: "new-password-123" } });
    fireEvent.change(within(dialog).getByLabelText("Confirm new password"), { target: { value: "new-password-123" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Update password" }));

    expect(await within(dialog).findByText("Password updated.")).toBeInTheDocument();
    expect(onPasswordChanged).toHaveBeenCalledTimes(1);
    expect(staffRequest).toHaveBeenCalledWith("/auth/change-password", expect.objectContaining({ method: "POST" }));
    expect(screen.getByRole("dialog", { name: "Your account" })).toBeInTheDocument();
  });

  it("offers sign out from the dialog", async () => {
    const { onSignOut } = renderHeader();
    const dialog = await openAccountDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Sign out" }));
    await waitFor(() => expect(onSignOut).toHaveBeenCalledTimes(1));
  });
});

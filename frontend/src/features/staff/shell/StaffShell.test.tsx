import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import type { StaffAuthUser } from "../../../lib/api";
import type { Makerspace } from "../panels/shared";
import { StaffShell, type StaffShellProps } from "./StaffShell";
import { SIDEBAR_COLLAPSED_KEY } from "./useSidebarCollapsed";

const makerspace = {
  id: 7, name: "Community Lab", public_code: "community-lab", slug: "community-lab",
  telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false,
} as Makerspace;

const user: StaffAuthUser = {
  username: "space-manager", email_verified: true, role: "staff", is_superuser: false,
  must_change_password: false, makerspaces: [],
};

function renderShell(overrides: { allowedTabs?: string[]; activeTab?: string; onSignOut?: () => void; onSelectTab?: (tab: string) => void } = {}) {
  const props: StaffShellProps = {
    nav: {
      activeMakerspaceSlug: makerspace.slug,
      activeTab: overrides.activeTab ?? "inventory",
      allowedTabs: overrides.allowedTabs ?? ["inventory", "qr"],
      guestOnly: false,
      singleTenantLocked: false,
    },
    account: {
      username: user.username, roleName: "Space Manager", activeMakerspaceName: makerspace.name,
      makerspaces: [makerspace], selected: 7, canSwitchMakerspace: false, canPickMakerspace: false,
      onPickMakerspace: vi.fn(), onSelectMakerspace: vi.fn(), onSignOut: overrides.onSignOut ?? vi.fn(),
    },
    activeMakerspaceId: makerspace.id,
    publicPath: "/m/community-lab",
    workspaceName: makerspace.name,
    user,
    onPasswordChanged: vi.fn(),
    onSelectTab: overrides.onSelectTab ?? vi.fn(),
    children: <p>panel body</p>,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/m/community-lab/admin/inventory"]}>
        <StaffShell {...props} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function openAccountMenu() {
  fireEvent.keyDown(screen.getByRole("button", { name: "space-manager, account menu" }), { key: "Enter" });
  return screen.getByRole("menu");
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockResolvedValue({ count: 0, results: [] });
  window.localStorage.clear();
});

afterEach(() => {
  document.documentElement.classList.remove("dark");
});

describe("StaffShell sidebar", () => {
  it("renders exactly the allowed tabs, grouped, and marks the active one as the current page", () => {
    renderShell({ allowedTabs: ["inventory", "qr", "machines"], activeTab: "qr" });
    const nav = screen.getByRole("navigation", { name: "Staff sections" });

    expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual(["Inventory", "QR Tools", "Machines"]);
    expect(within(nav).getByRole("group", { name: "Inventory" })).toBeInTheDocument();
    expect(within(nav).queryByRole("group", { name: "Operate" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "QR Tools" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Inventory" })).not.toHaveAttribute("aria-current");
    expect(within(nav).getByRole("link", { name: "Machines" })).toHaveAttribute("href", "/m/community-lab/admin/machines");
  });

  it("reports the chosen tab and offers a skip link to the main content", () => {
    const onSelectTab = vi.fn();
    renderShell({ onSelectTab });
    fireEvent.click(screen.getByRole("link", { name: "QR Tools" }));

    expect(onSelectTab).toHaveBeenCalledWith("qr");
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute("href", "#main-content");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
  });

  it("folds to the icon rail and remembers it across visits", () => {
    const first = renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));

    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("1");
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-expanded", "false");
    // On the rail the label text is gone, so each icon link carries it as its name.
    expect(screen.getByRole("link", { name: "Inventory" })).toHaveAttribute("aria-label", "Inventory");
    first.unmount();

    renderShell();
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY)).toBe("0");
  });

  it("opens the same navigation in a sheet on small screens and closes it", () => {
    renderShell();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));

    const sheet = screen.getByRole("dialog", { name: "Navigation" });
    expect(within(sheet).getByRole("navigation", { name: "Staff sections" })).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole("button", { name: "Close navigation menu" }));
    expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    fireEvent.click(within(screen.getByRole("dialog", { name: "Navigation" })).getByRole("link", { name: "QR Tools" }));
    expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument();
  });

  it("requests unread notifications once and folds the count into the link name", async () => {
    staffRequest.mockResolvedValue({ count: 3 });
    renderShell({ allowedTabs: ["notifications"], activeTab: "notifications" });

    expect(await screen.findByRole("link", { name: "Notifications, 3 unread" })).toBeInTheDocument();
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(1));
    expect(staffRequest).toHaveBeenCalledWith("/notifications/makerspace/7/unread-count");
  });

  it("does not request unread notifications without the notifications tab", async () => {
    renderShell({ allowedTabs: ["inventory"] });
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(staffRequest).not.toHaveBeenCalled();
  });
});

describe("StaffShell account menu", () => {
  it("opens the account dialog from the account card", async () => {
    renderShell();
    fireEvent.click(within(openAccountMenu()).getByRole("menuitem", { name: "Account" }));

    const dialog = await screen.findByRole("dialog", { name: "Your account" });
    expect(within(dialog).getByText("space-manager")).toBeInTheDocument();
  });

  it("switches the colour mode and signs out", () => {
    const onSignOut = vi.fn();
    renderShell({ onSignOut });

    fireEvent.click(within(openAccountMenu()).getByRole("menuitem", { name: "Dark mode" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(window.localStorage.getItem("makerspace.theme")).toBe("dark");

    fireEvent.click(within(openAccountMenu()).getByRole("menuitem", { name: "Sign out" }));
    expect(onSignOut).toHaveBeenCalledTimes(1);
  });
});

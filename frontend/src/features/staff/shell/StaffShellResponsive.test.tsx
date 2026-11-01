import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installLiveMatchMedia } from "../../../test/liveMatchMedia";
import { RegressionProviders, regressionClient } from "../../../test/uiRegressionHarness";
import { machineKeys } from "../machinesApi";
import { serviceType } from "../../../test/staffServiceOwnershipHarness";
import type { Makerspace } from "../panels/shared";
import { StaffShell, type StaffShellProps } from "./StaffShell";
import { SIDEBAR_COLLAPSED_KEY } from "./useSidebarCollapsed";

const makerspace = {
  id: 7, name: "Community Lab", public_code: "community-lab", slug: "community-lab",
  telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false,
} as Makerspace;

let media: ReturnType<typeof installLiveMatchMedia>;
beforeEach(() => {
  media = installLiveMatchMedia(800);
  localStorage.removeItem(SIDEBAR_COLLAPSED_KEY);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.removeItem(SIDEBAR_COLLAPSED_KEY); });

function mountShell(nav: Partial<StaffShellProps["nav"]> = {}) {
  const onSelectTab = vi.fn();
  const props: StaffShellProps = {
    nav: { activeMakerspaceSlug: makerspace.slug, activeTab: "inventory", allowedTabs: ["inventory", "qr"], guestOnly: false, singleTenantLocked: false, ...nav },
    account: {
      username: "space-manager", roleName: "Space Manager", activeMakerspaceName: makerspace.name,
      makerspaces: [makerspace], selected: 7, canSwitchMakerspace: false, canPickMakerspace: false,
      onPickMakerspace: vi.fn(), onSelectMakerspace: vi.fn(), onSignOut: vi.fn(),
    },
    activeMakerspaceId: 7, publicPath: "/m/community-lab", workspaceName: makerspace.name,
    user: { username: "space-manager", email_verified: true, role: "staff", is_superuser: false, must_change_password: false, makerspaces: [] },
    onPasswordChanged: vi.fn(), onSelectTab, children: <button>Panel action</button>,
  };
  const client = regressionClient();
  client.setQueryData(machineKeys.types(7), [{ ...serviceType("generic", 12), makerspace: 7 }]);
  render(<RegressionProviders client={client} path="/m/community-lab/admin/inventory">
    <StaffShell {...props} />
  </RegressionProviders>);
  return { onSelectTab };
}

describe("StaffShell responsive modal lifecycle", () => {
  it("800→1200 unmounts the sheet, releases Radix isolation and restores main focus; 800 again stays closed and can reopen", async () => {
    mountShell();
    const main = screen.getByRole("main");
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const dialog = await screen.findByRole("dialog", { name: "Navigation" });
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    expect(main.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(document.body.style.pointerEvents).toBe("none");
    expect(document.body).toHaveAttribute("data-scroll-locked");

    act(() => media.resize(1200));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument());
    await waitFor(() => expect(main).toHaveFocus());
    expect(main.closest('[aria-hidden="true"], [inert]')).toBeNull();
    expect(document.body.style.pointerEvents).toBe("");
    expect(document.body).not.toHaveAttribute("data-scroll-locked");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    const action = screen.getByRole("button", { name: "Panel action" });
    action.focus();
    expect(action).toHaveFocus();
    expect(screen.getByRole("button", { name: "Open navigation menu" })).not.toHaveFocus();

    act(() => media.resize(800));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    expect(await screen.findByRole("dialog", { name: "Navigation" })).toBeInTheDocument();
  });

  it("mobile Escape restores trigger focus and choosing a staff link closes the sheet", async () => {
    const { onSelectTab } = mountShell();
    const trigger = screen.getByRole("button", { name: "Open navigation menu" });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.keyDown(await screen.findByRole("dialog", { name: "Navigation" }), { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.body.style.pointerEvents).toBe("");
    fireEvent.click(trigger);
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Navigation" })).getByRole("link", { name: "QR Tools" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(onSelectTab).toHaveBeenCalledWith("qr");
    expect(screen.getByRole("main").closest('[aria-hidden="true"], [inert]')).toBeNull();
  });

  it("hands Account from the mobile sheet through the real menu cleanup into the account dialog", async () => {
    mountShell();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const sheet = await screen.findByRole("dialog", { name: "Navigation" });
    const accountTrigger = within(sheet).getByRole("button", { name: "space-manager, account menu" });
    accountTrigger.focus();
    fireEvent.keyDown(accountTrigger, { key: "Enter" });
    fireEvent.click(within(await screen.findByRole("menu")).getByRole("menuitem", { name: "Account" }));
    const account = await screen.findByRole("dialog", { name: "Your account" });
    expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await waitFor(() => expect(account).toContainElement(document.activeElement as HTMLElement));
    // Radix's sheet lock is gone before the separate account modal owns focus.
    expect(document.body.style.pointerEvents).toBe("");
    expect(account.closest('[aria-hidden="true"], [inert]')).toBeNull();
    fireEvent.click(within(account).getByRole("button", { name: "Close dialog" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("main").closest('[aria-hidden="true"], [inert]')).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    expect(await screen.findByRole("dialog", { name: "Navigation" })).toBeInTheDocument();
  });
});

it("mobile sheet exposes the same type-specific request link and closes on navigation", async () => {
  const { onSelectTab } = mountShell({ activeTab: "machines", allowedTabs: ["machines"],
    canManageMachines: true, machineServiceEnabled: true, printingEnabled: true });
  fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
  const sheet = within(await screen.findByRole("dialog", { name: "Navigation" }));
  const queue = sheet.getByRole("link", { name: "Presses requests" });
  expect(queue).toHaveAttribute("href", "/m/community-lab/admin/machines/12-press/queue");
  fireEvent.click(queue);
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument());
  expect(onSelectTab).toHaveBeenCalledWith("machines");
});

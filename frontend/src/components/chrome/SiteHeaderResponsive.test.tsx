import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { installLiveMatchMedia } from "../../test/liveMatchMedia";
import { MakerspaceSiteHeader } from "./PublicHeaders";

let media: ReturnType<typeof installLiveMatchMedia>;
beforeEach(() => { media = installLiveMatchMedia(800); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mountHeader() {
  return render(<MemoryRouter initialEntries={["/m/forge"]}>
    <MakerspaceSiteHeader homePath="/m/forge" name="Forge" page="Inventory"
      moduleEnabled={(key) => ["public_inventory", "events", "member_accounts"].includes(key)} />
    <main tabIndex={-1}>Public content</main>
  </MemoryRouter>);
}

describe("SiteHeader responsive modal lifecycle", () => {
  it("800→1200 unmounts the modal and releases Radix isolation/focus; 800 again stays closed and can reopen", async () => {
    mountHeader();
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const main = screen.getByRole("main");
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    const dialog = await screen.findByRole("dialog", { name: "Navigation" });
    await waitFor(() => expect(dialog).toContainElement(document.activeElement as HTMLElement));
    expect(main.closest('[aria-hidden="true"]')).not.toBeNull();
    expect(document.body.style.pointerEvents).toBe("none");
    expect(document.body).toHaveAttribute("data-scroll-locked");

    act(() => media.resize(1200));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument());
    await waitFor(() => expect(nav).toHaveFocus());
    expect(main.closest('[aria-hidden="true"], [inert]')).toBeNull();
    expect(nav.closest('[aria-hidden="true"], [inert]')).toBeNull();
    expect(document.body.style.pointerEvents).toBe("");
    expect(document.body).not.toHaveAttribute("data-scroll-locked");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    const eventsLink = within(nav).getByRole("link", { name: "Events" });
    eventsLink.focus();
    expect(eventsLink).toHaveFocus();
    expect(screen.getByRole("button", { name: "Open navigation menu" })).not.toHaveFocus();

    act(() => media.resize(800));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open navigation menu" }));
    expect(await screen.findByRole("dialog", { name: "Navigation" })).toBeInTheDocument();
  });

  it("mobile Escape restores trigger focus and a navigation link closes the reopened menu", async () => {
    mountHeader();
    const trigger = screen.getByRole("button", { name: "Open navigation menu" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Navigation" });
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(document.body.style.pointerEvents).toBe("");
    fireEvent.click(trigger);
    fireEvent.click(within(await screen.findByRole("dialog", { name: "Navigation" })).getByRole("link", { name: "Events" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("main").closest('[aria-hidden="true"], [inert]')).toBeNull();
    expect(screen.getByRole("link", { name: "Events" })).toHaveAttribute("aria-current", "page");
  });
});

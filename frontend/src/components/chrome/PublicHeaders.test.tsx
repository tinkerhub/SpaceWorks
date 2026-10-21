import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { MakerspaceSiteHeader, PlatformSiteHeader } from "./PublicHeaders";

function renderMakerspaceHeader(modules: string[]) {
  return render(
    <MemoryRouter initialEntries={["/m/forge"]}>
      <MakerspaceSiteHeader
        homePath="/m/forge"
        name="Forge"
        moduleEnabled={(key) => modules.includes(key)}
        page="Inventory"
      />
    </MemoryRouter>,
  );
}

describe("MakerspaceSiteHeader", () => {
  it("hides the member area link when member accounts are off", () => {
    renderMakerspaceHeader(["public_inventory"]);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).queryByRole("link", { name: "Member area" })).not.toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Staff login" })).toHaveAttribute("href", "/admin");
  });

  it("links the member area when member accounts are on", () => {
    renderMakerspaceHeader(["public_inventory", "member_accounts"]);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Member area" })).toHaveAttribute("href", "/m/forge/member");
    expect(within(nav).getByRole("link", { name: "Staff login" })).toBeInTheDocument();
  });

  it("links only the sections whose modules are on", () => {
    renderMakerspaceHeader(["public_inventory", "events"]);
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    expect(within(nav).getByRole("link", { name: "Events" })).toHaveAttribute("href", "/m/forge/events");
    expect(within(nav).queryByRole("link", { name: "Machines" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Bookings" })).not.toBeInTheDocument();
  });
});

describe("PlatformSiteHeader", () => {
  it("offers staff login but never a member area", () => {
    render(
      <MemoryRouter>
        <PlatformSiteHeader page="Makerspaces" />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "Staff login" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Member area" })).not.toBeInTheDocument();
  });
});

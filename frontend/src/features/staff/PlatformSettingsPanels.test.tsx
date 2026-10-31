import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { platformMounts } from "../../test/platformPanelMocks";
import type { StaffAuthUser } from "../../lib/api";
import { PlatformSettingsPanels } from "./PlatformSettingsPanels";

const user: StaffAuthUser = {
  username: "root", email_verified: true, role: "superadmin", is_superuser: true,
  must_change_password: false, makerspaces: [],
  staff_context: { scope_kind: "platform", makerspace_id: null, can_manage_platform: true,
    platform_hosting: true, platform_stripe_connect_available: true },
};

beforeEach(() => { platformMounts.length = 0; });

describe("shared Platform settings capabilities", () => {
  it.each([false, undefined])("managed hosting without payments availability (%s) never mounts Stripe", async (available) => {
    const context = { ...user.staff_context!, platform_stripe_connect_available: available };
    // Undefined models an older backend without the new optional capability.
    render(<PlatformSettingsPanels user={{ ...user, staff_context: context as StaffAuthUser["staff_context"] }} />);
    await screen.findByRole("region", { name: "Platform email leaf" });
    await screen.findByRole("region", { name: "Platform social leaf" });
    expect(screen.queryByRole("region", { name: "Platform Stripe leaf" })).not.toBeInTheDocument();
    expect(platformMounts).not.toContain("stripe");
    expect(screen.getByText(/Email delivery, sign-in providers for every makerspace/)).toBeVisible();
  });

  it("mounts payouts with explicit managed payments capability even without makerspaces", async () => {
    render(<PlatformSettingsPanels user={user} />);
    expect(await screen.findByRole("region", { name: "Platform Stripe leaf" })).toBeVisible();
    expect(screen.getByText(/sign-in providers and payouts/)).toBeVisible();
  });

  it("does not mount Stripe on a self-host even if a malformed context claims availability", async () => {
    render(<PlatformSettingsPanels user={{ ...user, staff_context: { ...user.staff_context!, platform_hosting: false } }} />);
    await screen.findByRole("region", { name: "Platform social leaf" });
    expect(platformMounts).not.toContain("stripe");
  });
});

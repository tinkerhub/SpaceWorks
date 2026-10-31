import { vi } from "vitest";

const observed = vi.hoisted(() => ({ mounts: [] as string[] }));

// Keep the authorization wrapper real; only the external-integration forms are leaves.
vi.mock("../features/staff/PlatformEmailPanel", () => ({
  PlatformEmailPanel: () => {
    observed.mounts.push("email");
    return <section aria-label="Platform email leaf">Email settings</section>;
  },
}));
vi.mock("../features/staff/PlatformSocialAuthPanel", () => ({
  PlatformSocialAuthPanel: () => {
    observed.mounts.push("social");
    return <section aria-label="Platform social leaf">Social settings</section>;
  },
}));
vi.mock("../features/staff/PlatformStripeConnectPanel", () => ({
  PlatformStripeConnectPanel: () => {
    observed.mounts.push("stripe");
    return <section aria-label="Platform Stripe leaf">Payout settings</section>;
  },
}));

export const platformMounts = observed.mounts;

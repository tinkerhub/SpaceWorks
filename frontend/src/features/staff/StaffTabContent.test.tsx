import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { StaffAuthUser } from "../../lib/api";
import type { Makerspace } from "./panels/shared";
import { StaffTabContent } from "./StaffTabContent";

// The panels themselves are not under test: each stub records the props it was handed.
vi.mock("./panels/AuditLog", () => ({
  AuditLog: ({ makerspaceId }: { makerspaceId?: number }) => <p>audit for {String(makerspaceId)}</p>,
}));
vi.mock("./PlatformEmailPanel", () => ({ PlatformEmailPanel: () => null }));
vi.mock("./PlatformSocialAuthPanel", () => ({ PlatformSocialAuthPanel: () => null }));
vi.mock("./PlatformStripeConnectPanel", () => ({ PlatformStripeConnectPanel: () => <p>payouts panel</p> }));

const user: StaffAuthUser = { username: "root", email_verified: false, role: "superadmin", is_superuser: true, must_change_password: false, makerspaces: [] };
const flags = {
  printingOnly: false, canChooseToBuyKind: true, canEditInventory: true, canIssueDirectLoan: true, canReturnRequest: true,
  canReviewRequests: true, canCollectServiceRequests: true, canUseToBuy: true, canManageQr: true, canManageMakerspace: true,
  canManageMachines: true, isMachineOnly: false, canConfigureMachineTypes: true, canManageEvents: false, canManageBookings: false,
  canSeeHardware: true, canSeePrinting: true, canViewAudit: true,
};

function renderTab(activeTab: string, space: Partial<Makerspace> = {}) {
  const makerspace = { id: 7, name: "Lab", slug: "lab", public_code: "LAB", enabled_modules: [], ...space } as unknown as Makerspace;
  render(
    <StaffTabContent
      activeMakerspace={makerspace}
      activeTab={activeTab}
      guestOnly={false}
      makerspaces={[makerspace]}
      isSuperadmin
      currentUser={user}
      onAuthRefresh={vi.fn()}
      {...flags}
    />,
  );
}

describe("StaffTabContent", () => {
  it("scopes the audit log to the active makerspace", async () => {
    // Unscoped, the origin-locked production site 403s and a superadmin sees every space's rows.
    renderTab("audit");
    expect(await screen.findByText("audit for 7")).toBeInTheDocument();
  });

  it("mentions payouts on Platform settings only when the payouts panel renders", async () => {
    renderTab("platform", { platform_hosting: false } as Partial<Makerspace>);
    expect(await screen.findByText("Email delivery and sign-in providers shared by every makerspace on this deployment.")).toBeInTheDocument();
    expect(screen.queryByText("payouts panel")).not.toBeInTheDocument();
  });

  it("keeps payouts in the description when platform hosting shows the payouts panel", async () => {
    renderTab("platform", { platform_hosting: true } as Partial<Makerspace>);
    expect(await screen.findByText("payouts panel")).toBeInTheDocument();
    expect(screen.getByText(/sign-in providers and payouts/)).toBeInTheDocument();
  });
});

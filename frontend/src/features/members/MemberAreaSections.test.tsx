import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MembershipCards, type Membership } from "./MemberAreaSections";

const MEMBERSHIP: Membership = {
  makerspace: { slug: "forge", name: "Forge" },
  membership_status: "active",
  role: "member",
  waiver_acceptance_required: true,
  can_refer: false,
  can_verify: false,
  verified_at: null,
  referrals_enabled: false,
};

function renderCards(waiverAcceptanceRequired: boolean) {
  return render(
    <MembershipCards
      membership={{ ...MEMBERSHIP, waiver_acceptance_required: waiverAcceptanceRequired }}
      waiver={{ has_waiver: true, body: "Wear goggles.", version: "v2" }}
      accepting={false}
      presenceBusy={false}
      canStartPresence
      onAccept={vi.fn()}
      onTogglePresence={vi.fn()}
    />,
  );
}

describe("MembershipCards waiver", () => {
  it("asks for acceptance while the current waiver is outstanding", () => {
    renderCards(true);

    expect(screen.getByText("Wear goggles.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept waiver" })).toBeInTheDocument();
  });

  it("collapses to an accepted state once the waiver is accepted", () => {
    renderCards(false);

    expect(screen.getByText(/waiver accepted/i)).toBeInTheDocument();
    expect(screen.queryByText("Wear goggles.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept waiver" })).not.toBeInTheDocument();
  });
});

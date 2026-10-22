/**
 * The request desk copy is a set of promises about what the backend will demand. Every
 * identity x tab x policy x signed-in combination is checked here so a sentence about
 * membership, waivers or presence can only appear where the `membership` module is on.
 */
import { describe, expect, it } from "vitest";

import { deskCopy, type DeskIdentity, type DeskTab } from "./PublicRequestHeader";

const IDENTITIES: DeskIdentity[] = ["contact", "checkin", "account", "member", "signin", "desk"];
const TABS: DeskTab[] = ["borrow", "scan"];
const POLICIES = [undefined, "anyone", "checked_in"] as const;

function all() {
  return IDENTITIES.flatMap((identity) =>
    TABS.flatMap((tab) =>
      POLICIES.flatMap((requestAccess) =>
        [false, true].map((authenticated) => ({
          args: { identity, tab, requestAccess, authenticated },
          copy: deskCopy({ identity, tab, requestAccess, authenticated }),
        })),
      ),
    ),
  );
}

describe("request desk copy", () => {
  it("mentions membership, waivers and presence only for the member identity", () => {
    for (const { args, copy } of all()) {
      const text = `${copy.title} ${copy.body}`;
      if (args.identity === "member" || (args.tab === "scan" && args.identity !== "checkin")) continue;
      expect(text, JSON.stringify(args)).not.toMatch(/member|waiver|presence/i);
    }
  });

  it("keeps a signed-in borrower on the roster on a checked-in space", () => {
    const copy = deskCopy({ identity: "checkin", tab: "borrow", requestAccess: "checked_in", authenticated: true });
    expect(copy.title).toBe("Borrow with check-in");
    expect(copy.body).toMatch(/always uses check-in, even while you are signed in/);
    expect(copy.body).not.toMatch(/your account/i);
  });

  it("describes check-in self-checkout as roster-only, even for a signed-in caller", () => {
    const copy = deskCopy({ identity: "checkin", tab: "scan", requestAccess: "checked_in", authenticated: true });
    expect(copy.title).toBe("Scan a tool with check-in");
    expect(copy.body).toMatch(/recorded under that check-in name, even while you are signed in/);
    expect(deskCopy({ identity: "checkin", tab: "scan", requestAccess: "checked_in", authenticated: false }).body)
      .not.toMatch(/signed in/);
  });

  it("keeps the member requirements where membership is on", () => {
    expect(deskCopy({ identity: "member", tab: "borrow", authenticated: true }).body)
      .toMatch(/active membership, waiver acceptance, and current presence/);
    expect(deskCopy({ identity: "member", tab: "scan", authenticated: true }).title).toBe("Member self-checkout");
  });

  it("names the configured check-in provider, and stays neutral without one", () => {
    const named = deskCopy({ identity: "checkin", tab: "borrow", requestAccess: "checked_in", authenticated: false, appearsIn: "in Maker Gate" });
    expect(named.body).toMatch(/as it appears in Maker Gate/);
    const neutral = deskCopy({ identity: "checkin", tab: "borrow", requestAccess: "checked_in", authenticated: false });
    expect(neutral.body).toMatch(/as it appears on the check-in list/);
    expect(neutral.body).not.toMatch(/TinkerHub/);
  });
});

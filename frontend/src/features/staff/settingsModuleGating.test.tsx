import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

// Every card is a stub carrying its own name, so these tests pin exactly which cards the
// settings panel mounts -- the gating decision -- and nothing about the cards' internals.
function stub(name: string) {
  return () => <div>{`card:${name}`}</div>;
}
vi.mock("./MakerspaceBrandingSettings", () => ({ MakerspaceBrandingSettings: stub("branding") }));
vi.mock("./MakerspaceGeneralSettings", () => ({ MakerspaceGeneralSettings: stub("general") }));
vi.mock("./MakerspaceLocationSettings", () => ({ MakerspaceLocationSettings: stub("location") }));
vi.mock("./MakerspaceGeofenceSettings", () => ({ MakerspaceGeofenceSettings: stub("geofence") }));
vi.mock("./MakerspacePublicStatsSettings", () => ({ MakerspacePublicStatsSettings: stub("public-stats") }));
vi.mock("./MakerspaceSubdomainSettings", () => ({ MakerspaceSubdomainSettings: stub("subdomain") }));
vi.mock("./MakerspaceCustomDomainSettings", () => ({ MakerspaceCustomDomainSettings: stub("custom-domain") }));
vi.mock("./MakerspaceArchiveRequestPanel", () => ({ MakerspaceArchiveRequestPanel: stub("archive") }));
vi.mock("./IntegrationHealthPanel", () => ({ IntegrationHealthPanel: stub("integration-health") }));
vi.mock("./NotificationMuteMatrix", () => ({ NotificationMuteMatrix: stub("mute-matrix") }));
vi.mock("./NotificationRecipientPicker", () => ({ NotificationRecipientPicker: stub("recipient-picker") }));
vi.mock("./NotificationDestinations", () => ({ NotificationDestinations: stub("destinations") }));
vi.mock("./MakerspaceMembershipSettings", () => ({ MakerspaceMembershipSettings: stub("membership") }));
vi.mock("./MakerspacePaymentSettings", () => ({ MakerspacePaymentSettings: stub("payments") }));
vi.mock("./MakerspaceBookingSettings", () => ({ MakerspaceBookingSettings: stub("booking-emails") }));
vi.mock("./MakerspaceBookingRulesSettings", () => ({ MakerspaceBookingRulesSettings: stub("booking-rules") }));
vi.mock("./MakerspaceFilamentSettings", () => ({ MakerspaceFilamentSettings: stub("filament") }));
vi.mock("./MakerspaceEmailSettings", () => ({ MakerspaceEmailSettings: stub("email") }));
vi.mock("./MakerspaceWebhookSettings", () => ({ MakerspaceWebhookSettings: stub("webhooks") }));
vi.mock("./ApiClientsTelegramSettings", () => ({ ApiClientsTelegramSettings: stub("telegram") }));
vi.mock("./EvidenceRetentionPanel", () => ({ EvidenceRetentionPanel: stub("evidence-retention") }));

import { MakerspaceFeatureSettings } from "./MakerspaceFeatureSettings";
import { MakerspaceSettingsPanel } from "./MakerspaceSettingsPanel";
import type { Makerspace } from "./panels/shared";

const CORE = ["public_inventory", "request_workflow", "staff_admin", "scanner", "qr_management", "evidence_uploads"];
const GATED_CARDS = ["membership", "geofence", "payments", "booking-emails", "booking-rules", "filament", "email", "webhooks", "telegram", "destinations"];

function space(modules: string[]): Makerspace {
  return {
    id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false, enabled_modules: modules, enabled_features: [],
  };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function renderSettings(modules: string[], canManageMakerspace = true) {
  const makerspace = space(modules);
  staffRequest.mockResolvedValue(makerspace);
  return wrap(<MakerspaceSettingsPanel makerspace={makerspace} isSuperadmin={false} canManageMakerspace={canManageMakerspace} />);
}

beforeEach(() => {
  staffRequest.mockReset();
});

// The settings page is tabbed and Radix unmounts inactive tab panels, so a gate is checked
// by visiting every tab and collecting which card stubs (and inline cards) ever mounted.
const INLINE_CARDS = ["Public print status recovery", "Staff email notifications"];
async function mountedAcrossTabs() {
  await screen.findByText("card:general");
  const seen = new Set<string>();
  const tabs = screen.getAllByRole("tab");
  for (const tab of tabs) {
    fireEvent.mouseDown(tab);
    expect(tab).toHaveAttribute("aria-selected", "true");
    for (const card of [...GATED_CARDS, "general"]) if (screen.queryByText(`card:${card}`)) seen.add(card);
    for (const title of INLINE_CARDS) if (screen.queryByText(title)) seen.add(title);
  }
  return { seen, tabs: tabs.map((tab) => tab.textContent) };
}

describe("settings cards follow the module switches", () => {
  it("mounts no card for a switched-off module", async () => {
    renderSettings(CORE);
    const { seen, tabs } = await mountedAcrossTabs();
    // A tab whose cards are all switched off is not offered at all -- with no email or
    // chat module there is nothing to notify through, so Notifications goes too.
    expect(tabs).toEqual(["General", "Integrations", "Domain & access"]);
    expect(seen.has("destinations")).toBe(false);
    expect(seen.has("general")).toBe(true);
    for (const card of GATED_CARDS) expect(seen.has(card)).toBe(false);
    for (const title of INLINE_CARDS) expect(seen.has(title)).toBe(false);
  });

  it("matches the production check-in module set: no membership, booking, payment or webhook cards", async () => {
    renderSettings([...CORE, "printing", "machines", "machine_service", "maintenance", "notifications", "email", "telegram"]);
    const { seen, tabs } = await mountedAcrossTabs();
    expect(tabs).toEqual(["General", "Machines", "Notifications", "Integrations", "Domain & access"]);
    for (const card of ["membership", "geofence", "payments", "booking-emails", "booking-rules", "webhooks"]) {
      expect(seen.has(card)).toBe(false);
    }
    for (const card of ["email", "telegram", "filament", "Staff email notifications"]) expect(seen.has(card)).toBe(true);
  });

  it("mounts each card once its module is on", async () => {
    renderSettings([...CORE, "membership", "payments", "bookings", "machine_service", "printing", "email", "telegram", "slack"]);
    const { seen, tabs } = await mountedAcrossTabs();
    expect(tabs).toEqual(["General", "Bookings", "Machines", "Notifications", "Integrations", "Domain & access"]);
    for (const card of GATED_CARDS) expect(seen.has(card)).toBe(true);
    for (const title of INLINE_CARDS) expect(seen.has(title)).toBe(true);
  });

  it("offers chat rooms only with a chat module", async () => {
    renderSettings([...CORE, "email"]);
    const { seen, tabs } = await mountedAcrossTabs();
    expect(tabs).toEqual(["General", "Notifications", "Integrations", "Domain & access"]);
    expect(seen.has("destinations")).toBe(false);
  });

  it("offers evidence retention in General with events off, to managers only", async () => {
    renderSettings([...CORE, "email", "telegram"], true);
    expect(await screen.findByText("card:evidence-retention")).toBeInTheDocument();
  });

  it("hides evidence retention from an actor who cannot manage the makerspace", async () => {
    renderSettings(CORE, false);
    await screen.findByText("card:general");
    expect(screen.queryByText("card:evidence-retention")).not.toBeInTheDocument();
  });

  it("shows the Telegram settings to a Space Manager in Settings", async () => {
    renderSettings([...CORE, "telegram"], true);
    const { seen } = await mountedAcrossTabs();
    expect(seen.has("telegram")).toBe(true);
  });

  it("hides the Telegram settings from an actor who cannot manage the makerspace", async () => {
    renderSettings([...CORE, "telegram"], false);
    const { seen } = await mountedAcrossTabs();
    expect(seen.has("telegram")).toBe(false);
  });

  it("keeps the archive request as the last card on the page", async () => {
    renderSettings(CORE);
    await screen.findByText("card:general");
    fireEvent.mouseDown(screen.getByRole("tab", { name: "Domain & access" }));
    const panel = screen.getByRole("tabpanel");
    expect(panel.lastElementChild).toHaveTextContent("card:archive");
  });
});

describe("feature settings fieldsets", () => {
  it("renders only the always-available group when every optional module is off", () => {
    wrap(<MakerspaceFeatureSettings makerspace={space(CORE)} loading={false} />);
    const groups = screen.getAllByRole("group").map((group) => group.querySelector("legend")?.textContent);
    expect(groups).toEqual(["General"]);
  });

  it("shows no raw module keys and labels each module group", () => {
    wrap(<MakerspaceFeatureSettings makerspace={space([...CORE, "notifications", "maintenance"])} loading={false} />);
    expect(screen.queryByText("public_inventory")).not.toBeInTheDocument();
    expect(screen.queryByText("notifications")).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Notifications" })).toBeInTheDocument();
  });

  it("offers the presence geofence switch only with the membership module", () => {
    const { unmount } = wrap(<MakerspaceFeatureSettings makerspace={space(CORE)} loading={false} />);
    expect(screen.queryByRole("switch", { name: "Presence geofence" })).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Self checkout" })).toBeInTheDocument();
    unmount();
    wrap(<MakerspaceFeatureSettings makerspace={space([...CORE, "membership"])} loading={false} />);
    expect(screen.getByRole("switch", { name: "Presence geofence" })).toBeInTheDocument();
  });

  it("does not echo features stranded by a switched-off module when toggling another", async () => {
    const makerspace = { ...space([...CORE, "notifications", "maintenance"]), enabled_features: ["mobile.push", "payments.enabled", "inventory.self_checkout"] };
    staffRequest.mockResolvedValue(makerspace);
    wrap(<MakerspaceFeatureSettings makerspace={makerspace} loading={false} />);

    fireEvent.click(screen.getByRole("switch", { name: "Delegated maintenance recipients" }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspaces/7",
      expect.objectContaining({
        body: JSON.stringify({ enabled_features: ["inventory.self_checkout", "notifications.delegated_recipients"] }),
      }),
    ));
  });

  it("offers delegated maintenance recipients only with the maintenance module", () => {
    const { unmount } = wrap(<MakerspaceFeatureSettings makerspace={space([...CORE, "notifications"])} loading={false} />);
    expect(screen.queryByRole("switch", { name: "Delegated maintenance recipients" })).not.toBeInTheDocument();
    unmount();
    wrap(<MakerspaceFeatureSettings makerspace={space([...CORE, "notifications", "maintenance"])} loading={false} />);
    expect(screen.getByRole("switch", { name: "Delegated maintenance recipients" })).toBeInTheDocument();
  });

  it("drops payments.* sub-features while the payments module is off", () => {
    wrap(<MakerspaceFeatureSettings makerspace={space([...CORE, "machines", "machine_service"])} loading={false} />);
    expect(screen.queryByText("Machine payments")).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Machines" })).not.toBeInTheDocument();
  });

  it("offers a parented feature once its module is on", async () => {
    wrap(<MakerspaceFeatureSettings makerspace={space([...CORE, "machines", "machine_service", "payments"])} loading={false} />);
    const toggle = screen.getByRole("switch", { name: "Machine payments" });
    expect(toggle).toBeEnabled();
    fireEvent.click(toggle);
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspaces/7",
      expect.objectContaining({ body: JSON.stringify({ enabled_features: ["payments.machines"] }) }),
    ));
  });
});

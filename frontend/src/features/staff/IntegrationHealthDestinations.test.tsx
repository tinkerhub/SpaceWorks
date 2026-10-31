import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatDestinationsHealth } from "./IntegrationHealthDestinations";
import { IntegrationHealthPanel } from "./IntegrationHealthPanel";
import type { Makerspace } from "./panels/shared";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

type Destination = NonNullable<ChatDestinationsHealth["destinations"]>[number];
const clients: QueryClient[] = [];
const NOW = "2026-10-29T10:00:00Z";
const SENT = "2026-10-29T09:55:00Z";
const FAILED = "2026-10-29T09:58:00Z";
const SAFE_FAILURE = "The last alert wasn't delivered. Check the channel configuration.";

function room(id: number, channel: Destination["channel"], overrides: Partial<Destination> = {}): Destination {
  return {
    id, channel, label: `${channel} fabrication`, is_active: true, configured: true,
    failed: 2, last_sent_at: SENT, last_failure: { at: FAILED, error: SAFE_FAILURE },
    ...overrides,
  };
}

function healthResponse() {
  return {
    status: "warn" as const,
    email: {
      status: "warn" as const, total: 9, pending: 0, sent: 8, failed: 1, stalled: 0,
      last_failure: { created_at: FAILED, subject: "Email-only subject", error: "Email-only failure", stream: "hardware" },
    },
    deliveries_by_stream: { status: "ok" as const, hardware: SENT, printing: SENT },
    smtp: { status: "ok" as const, configured: false },
    telegram: {
      status: "warn" as const, configured: false, enabled: true,
      last_sent_at: null,
      last_failure: { at: FAILED, detail: "Telegram-only legacy failure" },
    },
    worker: { status: "ok" as const, broker_configured: true, eager: false, last_seen: SENT, stale: false },
    chat_destinations: {
      status: "warn",
      destinations: [
        room(1, "slack"), room(2, "discord", { is_active: false }),
        room(3, "telegram", { configured: false }), room(4, "mattermost"),
      ],
      legacy_channels: {},
    } as ChatDestinationsHealth | undefined,
  };
}

function panel(modules?: string[]) {
  const makerspace: Makerspace = {
    id: 41, name: "Fabrication", public_code: "fabrication", slug: "fabrication",
    telegram_group_chat_id: "-100-never-render-chat-secret", frontend_domain: null,
    hidden_from_central_directory: false, enabled_modules: modules,
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter><IntegrationHealthPanel makerspace={makerspace} /></MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
  vi.spyOn(Date, "now").mockReturnValue(new Date(NOW).getTime());
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.restoreAllMocks();
});

describe("IntegrationHealthPanel destination diagnostics", () => {
  it("queries health and diagnoses actual rooms for all four enabled chat channels", async () => {
    staffRequest.mockResolvedValue(healthResponse());
    const { container } = panel(["slack", "discord", "telegram", "mattermost"]);

    await screen.findByRole("row", { name: /slack fabrication/ });

    expect(staffRequest).toHaveBeenCalledExactlyOnceWith("/admin/makerspace/41/integration-health");
    expect(screen.getByRole("region", { name: "Integration health" })).toBeInTheDocument();
    for (const [channel, title] of [["slack", "Slack"], ["discord", "Discord"], ["telegram", "Telegram"], ["mattermost", "Mattermost"]]) {
      const row = screen.getByRole("row", { name: new RegExp(`${channel} fabrication`) });
      const cells = within(row);
      expect(cells.getByText(`${title} destination`)).toBeInTheDocument();
      expect(cells.getByText(channel === "discord" ? "Disabled" : "Active", { exact: true })).toBeInTheDocument();
      expect(cells.getByText(channel === "telegram" ? "Not configured" : "Configured", { exact: true })).toBeInTheDocument();
      expect(cells.getByText("Failed deliveries: 2")).toBeInTheDocument();
      expect(cells.getByText("Last delivery: 5 minutes ago")).toBeInTheDocument();
      expect(cells.getByText(`Last failure 2 minutes ago: ${SAFE_FAILURE}`)).toBeInTheDocument();
    }
    expect(screen.getByRole("row", { name: /Chat destinations/ })).toHaveTextContent("4 destinations for enabled channels.");
    expect(container).not.toHaveTextContent("-100-never-render-chat-secret");
    expect(screen.queryByText("Email-only failure")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Email log" })).not.toBeInTheDocument();
  });

  it("hides disabled channel rooms and legacy rows while retaining disabled rooms on enabled channels", async () => {
    const response = healthResponse();
    response.chat_destinations = {
      ...response.chat_destinations,
      destinations: [room(1, "slack", { is_active: false }), room(2, "telegram"), room(3, "discord")],
      legacy_channels: { telegram: true, discord: false, mattermost: true },
    };
    staffRequest.mockResolvedValue(response);
    panel(["slack"]);

    const row = await screen.findByRole("row", { name: /slack fabrication/ });

    expect(within(row).getByText("Disabled", { exact: true })).toBeInTheDocument();
    expect(within(row).getByText("Configured", { exact: true })).toBeInTheDocument();
    expect(within(row).getByText(/Last failure .*Check the channel configuration/)).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /telegram fabrication|discord fabrication|legacy channel/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/Telegram-only|Email-only/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Telegram test" })).not.toBeInTheDocument();
    expect(screen.getByText("Chat destinations and background worker status. Refreshes every minute.")).toBeInTheDocument();
  });

  it("displays relevant legacy configured booleans without showing disabled channels", async () => {
    const response = healthResponse();
    response.chat_destinations = {
      status: "ok", destinations: [],
      legacy_channels: { slack: true, mattermost: false, telegram: true, discord: true },
    };
    staffRequest.mockResolvedValue(response);
    panel(["slack", "mattermost"]);

    const slack = await screen.findByRole("row", { name: /Slack legacy channel/ });
    const mattermost = screen.getByRole("row", { name: /Mattermost legacy channel/ });

    expect(within(slack).getByText("Configured", { exact: true })).toBeInTheDocument();
    expect(within(mattermost).getByText("Not configured", { exact: true })).toBeInTheDocument();
    expect(screen.queryByRole("row", { name: /Telegram|Discord/ })).not.toBeInTheDocument();
  });

  it("shows unknown destination health when an older backend omits the section", async () => {
    const response = healthResponse();
    delete response.chat_destinations;
    staffRequest.mockResolvedValue(response);
    panel(["slack"]);

    const row = await screen.findByRole("row", { name: /Chat destinations/ });

    expect(within(row).getByText("Unknown", { exact: true })).toBeInTheDocument();
    expect(within(row).getByText("Destination health is unavailable.")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Worker/ })).toBeInTheDocument();
  });

  it("renders a safe unknown section detail when optional destination fields are absent", async () => {
    const response = healthResponse();
    response.chat_destinations = { status: "unknown", detail: "Chat destination health is unavailable." };
    staffRequest.mockResolvedValue(response);
    panel(["discord"]);

    const row = await screen.findByRole("row", { name: /Chat destinations/ });

    expect(within(row).getByText("Unknown", { exact: true })).toBeInTheDocument();
    expect(within(row).getByText("Chat destination health is unavailable.")).toBeInTheDocument();
    expect(screen.queryByText(/fabrication|legacy channel/)).not.toBeInTheDocument();
  });

  it.each([
    { state: "empty", modules: [] as string[] },
    { state: "absent", modules: undefined },
  ])("hides all chat diagnostics when the module list is $state", async ({ modules }) => {
    staffRequest.mockResolvedValue(healthResponse());
    panel(modules);

    await screen.findByRole("row", { name: /Worker/ });

    expect(screen.queryByRole("row", { name: /Chat destinations|fabrication|legacy channel|Telegram|Email|SMTP/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Email log|Telegram test/ })).not.toBeInTheDocument();
    expect(screen.getByText("Background worker status. Refreshes every minute.")).toBeInTheDocument();
    expect(screen.queryByText(/Email-only|Telegram-only|Check the channel configuration/)).not.toBeInTheDocument();
  });

  it("keeps email and Telegram controls and printing stream details gated independently", async () => {
    staffRequest.mockResolvedValue(healthResponse());
    panel(["email", "telegram", "slack"]);

    await screen.findByRole("row", { name: /slack fabrication/ });

    expect(screen.getByRole("link", { name: "Email log" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Telegram test" })).toHaveAttribute("href", "#telegram-settings-title");
    expect(screen.getByText("Platform sender")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Deliveries by stream/ })).not.toHaveTextContent("Printing");
    expect(screen.getByText("Email-only failure")).toBeInTheDocument();
    expect(screen.getByText(/Last alert failed .*Telegram-only legacy failure/)).toBeInTheDocument();
  });
});

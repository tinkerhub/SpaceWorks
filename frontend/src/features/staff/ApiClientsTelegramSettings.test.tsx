import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, staffRequest };
});

import { ToastProvider } from "../../components/ui";
import { ApiClientsTelegramSettings } from "./ApiClientsTelegramSettings";
import { IntegrationHealthPanel } from "./IntegrationHealthPanel";
import type { Makerspace } from "./panels/shared";

const SAVED = { telegram_group_chat_id: "-1001234567890", telegram_bot_token_set: true };

function space(modules: string[]): Makerspace {
  return {
    id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
    frontend_domain: null, hidden_from_central_directory: false, enabled_modules: modules, enabled_features: [],
  };
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <ToastProvider>{node}</ToastProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  staffRequest.mockReset();
});

describe("Telegram alerts card", () => {
  it("shows Telegram's reason when the test alert is not delivered", async () => {
    staffRequest.mockImplementation((path: string) => {
      if (path.endsWith("/api-settings")) return Promise.resolve(SAVED);
      return Promise.resolve({ delivered: false, reason: "bad_token", detail: "Telegram didn't accept the bot token." });
    });
    wrap(<ApiClientsTelegramSettings makerspace={space(["telegram"])} />);

    const test = await screen.findByRole("button", { name: "Send Telegram test alert" });
    await waitFor(() => expect(test).toBeEnabled());
    fireEvent.click(test);

    // Once in the toast, once in the result callout.
    expect(await screen.findAllByText("Telegram didn't accept the bot token.")).toHaveLength(2);
    expect(screen.getByText("Telegram delivered: no")).toBeInTheDocument();
    expect(staffRequest).toHaveBeenCalledWith(
      "/integrations/telegram/test-alert",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("holds the test alert until edits are saved, then saves with a toast", async () => {
    staffRequest.mockResolvedValue(SAVED);
    wrap(<ApiClientsTelegramSettings makerspace={space(["telegram"])} />);

    const test = await screen.findByRole("button", { name: "Send Telegram test alert" });
    await waitFor(() => expect(test).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Telegram bot token"), { target: { value: "123456:abcdefghijklmnopqrstuvwxyz" } });
    expect(test).toBeDisabled();
    expect(screen.getByText("Save your changes before sending a test alert.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save integration settings" }));
    expect(await screen.findByText("Telegram settings saved")).toBeInTheDocument();
    expect(staffRequest).toHaveBeenCalledWith(
      "/admin/makerspace/7/api-settings",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ telegram_group_chat_id: "-1001234567890", telegram_bot_token: "123456:abcdefghijklmnopqrstuvwxyz" }),
      }),
    );
    await waitFor(() => expect(test).toBeEnabled());
  });

  it("shows a field error from the server as a toast instead of saving silently", async () => {
    staffRequest.mockImplementation((_path: string, init?: RequestInit) => {
      if (init?.method === "PATCH") return Promise.reject(new Error("That isn't a Telegram bot token."));
      return Promise.resolve(SAVED);
    });
    wrap(<ApiClientsTelegramSettings makerspace={space(["telegram"])} />);
    const save = await screen.findByRole("button", { name: "Save integration settings" });
    await waitFor(() => expect(save).toBeEnabled());

    fireEvent.click(save);

    expect(await screen.findAllByText("That isn't a Telegram bot token.")).not.toHaveLength(0);
  });
});

const HEALTH = {
  status: "warn",
  email: { status: "ok", total: 2, pending: 0, sent: 2, failed: 0, stalled: 0, last_failure: null },
  deliveries_by_stream: { status: "ok", hardware: null, printing: null },
  smtp: { status: "ok", configured: false },
  telegram: {
    status: "warn", enabled: true, configured: true, last_sent_at: null,
    last_failure: { at: "2026-10-22T10:00:00Z", detail: "Telegram didn't accept the bot token." },
  },
  worker: { status: "ok", broker_configured: true, eager: false, last_seen: null, stale: false },
};

describe("integration health", () => {
  it("shows only rows for modules that are on, and the last Telegram failure", async () => {
    staffRequest.mockResolvedValue(HEALTH);
    wrap(<IntegrationHealthPanel makerspace={space(["email", "telegram"])} />);

    expect(await screen.findByText(/Last alert failed .*Telegram didn't accept the bot token\./)).toBeInTheDocument();
    expect(screen.getByText("Platform sender")).toBeInTheDocument();
    expect(screen.getByText(/Hardware: never sent/)).not.toHaveTextContent("Printing");
  });

  it("drops the email and Telegram rows when those modules are off", async () => {
    staffRequest.mockResolvedValue(HEALTH);
    wrap(<IntegrationHealthPanel makerspace={space([])} />);

    expect(await screen.findByText("Worker")).toBeInTheDocument();
    expect(screen.queryByText("Telegram")).not.toBeInTheDocument();
    expect(screen.queryByText("SMTP")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Email log" })).not.toBeInTheDocument();
    expect(screen.getByText("Background worker status. Refreshes every minute.")).toBeInTheDocument();
  });
});

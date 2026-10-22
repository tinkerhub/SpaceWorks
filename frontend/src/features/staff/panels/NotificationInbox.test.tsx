import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { staffRequest } = vi.hoisted(() => ({ staffRequest: vi.fn() }));

vi.mock("../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../lib/api")>("../../../lib/api");
  return { ...actual, staffRequest };
});

import { NotificationInbox } from "./NotificationInbox";
import { formatLogTime } from "./StaffLogParts";
import type { Makerspace } from "./shared";

const makerspace = {
  id: 7, name: "Forge", public_code: "forge", slug: "forge", telegram_group_chat_id: "",
  frontend_domain: null, hidden_from_central_directory: false,
} as Makerspace;

const page = {
  count: 1, next: null, previous: null,
  results: [{
    id: 3, level: "critical", event: "machine_fault", title: "Laser is down", body: "Tube failure",
    url_path: "", read_at: null, created_at: new Date().toISOString(),
  }],
};

function renderInbox(client: QueryClient) {
  render(<QueryClientProvider client={client}><NotificationInbox makerspace={makerspace} /></QueryClientProvider>);
}

beforeEach(() => {
  staffRequest.mockReset();
  staffRequest.mockImplementation((path: string) =>
    Promise.resolve(path.endsWith("/read-all") ? { updated: 1 } : page),
  );
});

describe("NotificationInbox", () => {
  it("shows an unread alert with its level as a word", async () => {
    renderInbox(new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    expect(await screen.findByRole("heading", { name: "Laser is down" })).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Mark read" })).toBeInTheDocument();
  });

  it("refreshes the sidebar unread badge after marking everything read", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderInbox(client);
    await screen.findByRole("heading", { name: "Laser is down" });
    fireEvent.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith(
      "/notifications/makerspace/7/read-all",
      expect.objectContaining({ method: "POST" }),
    ));
    // useUnreadNotifications caches the badge count under ["notifications-unread", id].
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["notifications-unread", 7] }));
  });

  it("filters to unread only and goes back to page one", async () => {
    renderInbox(new QueryClient({ defaultOptions: { queries: { retry: false } } }));
    await screen.findByRole("heading", { name: "Laser is down" });
    fireEvent.click(screen.getByRole("radio", { name: "Unread only" }));
    await waitFor(() => expect(staffRequest).toHaveBeenCalledWith("/notifications/makerspace/7?unread=true&page=1"));
  });
});

describe("formatLogTime", () => {
  const now = Date.parse("2026-10-21T12:00:00Z");
  it("is relative under a week and a date after", () => {
    expect(formatLogTime("2026-10-21T11:59:30Z", now)).toBe("Just now");
    expect(formatLogTime("2026-10-21T11:58:00Z", now)).toMatch(/2 min/);
    expect(formatLogTime("2026-10-01T09:30:00Z", now)).toMatch(/2026/);
  });
});

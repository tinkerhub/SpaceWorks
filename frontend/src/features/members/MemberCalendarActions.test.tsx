import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { memberRequest, memberRequestBlob } = vi.hoisted(() => ({ memberRequest: vi.fn(), memberRequestBlob: vi.fn() }));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, memberRequest, memberRequestBlob };
});

import { MemberCalendarActions } from "./MemberCalendarActions";

const FEED = "/member/makerspaces/4/event-calendar-feed/";

function renderActions(enabled: boolean) {
  memberRequest.mockImplementation((path: string, init?: RequestInit) => {
    if (init?.method === "POST") return Promise.resolve({ feed_url: "https://cal.example/secret", token_hint: "cret", created_at: "" });
    if (init?.method === "DELETE") return Promise.resolve(undefined);
    if (path === FEED) return Promise.resolve({ enabled, token_hint: enabled ? "abcd" : null, created_at: null, rotated_at: null });
    return Promise.reject(new Error(`Unexpected ${path}`));
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemberCalendarActions makerspaceId={4} makerspaceSlug="forge" />
    </QueryClientProvider>,
  );
}

const confirmSpy = vi.spyOn(window, "confirm");

beforeEach(() => {
  memberRequest.mockReset();
  memberRequestBlob.mockReset();
  confirmSpy.mockReset();
});

describe("MemberCalendarActions", () => {
  it("asks in a dialog before creating the bearer link, and cancel sends nothing", async () => {
    renderActions(false);
    const create = await screen.findByRole("button", { name: "Create subscription link" });
    await waitFor(() => expect(create).toBeEnabled());

    fireEvent.click(create);
    const dialog = screen.getByRole("alertdialog", { name: "Create a calendar link?" });
    expect(dialog).toHaveTextContent("Anyone with the link can see your event schedule.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(memberRequest).not.toHaveBeenCalledWith(FEED, expect.objectContaining({ method: "POST" }));

    fireEvent.click(create);
    fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Create link" }));
    expect(await screen.findByLabelText("Private calendar subscription link")).toHaveValue("https://cal.example/secret");
    expect(memberRequest).toHaveBeenCalledWith(FEED, { method: "POST", body: JSON.stringify({ confirm_bearer_risk: true }) });
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("revokes an active link only after a destructive confirmation", async () => {
    renderActions(true);
    fireEvent.click(await screen.findByRole("button", { name: "Revoke link…" }));
    const dialog = screen.getByRole("alertdialog", { name: "Revoke your calendar link?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Revoke link" }));

    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith(FEED, { method: "DELETE" }));
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});

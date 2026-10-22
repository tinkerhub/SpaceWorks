import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlatformStripeConnectPanel } from "./PlatformStripeConnectPanel";

const { query, staffRequest } = vi.hoisted(() => ({
  query: vi.fn(),
  staffRequest: vi.fn(),
}));

vi.mock("../../lib/api", () => ({ staffRequest }));
vi.mock("./panels/shared", async () => {
  const actual = await vi.importActual<typeof import("./panels/shared")>("./panels/shared");
  return { ...actual, useStaffGet: query };
});

/** Clearing a saved credential asks first; confirm inside the dialog. */
async function confirmClear(short: string) {
  fireEvent.click(screen.getByRole("button", { name: `Clear ${short}…` }));
  const dialog = await screen.findByRole("alertdialog");
  fireEvent.click(within(dialog).getByRole("button", { name: `Clear ${short}` }));
}

describe("PlatformStripeConnectPanel", () => {
  beforeEach(() => {
    query.mockReset();
    staffRequest.mockReset();
  });

  it("submits a new publishable key without rendering a stored value", async () => {
    query.mockReturnValue({
      data: {
        id: 1,
        stripe_publishable_key: "pk_stored_never_returned",
        stripe_publishable_key_set: true,
        stripe_secret_key_set: true,
        stripe_webhook_secret_set: true,
        stripe_connect_client_id: "ca_platform",
        application_fee_bps: 125,
        updated_at: "2026-07-22T00:00:00Z",
      },
      isLoading: false,
      error: null,
    });
    staffRequest.mockResolvedValue({});
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PlatformStripeConnectPanel />
      </QueryClientProvider>,
    );

    const input = screen.getByPlaceholderText("Platform publishable key set");
    expect(input).toHaveValue("");
    expect(screen.queryByDisplayValue("pk_stored_never_returned")).toBeNull();
    fireEvent.change(input, { target: { value: "pk_live_new" } });
    fireEvent.click(screen.getByRole("button", { name: /save stripe connect settings/i }));

    await waitFor(() => expect(staffRequest).toHaveBeenCalled());
    const lastCall = staffRequest.mock.calls[staffRequest.mock.calls.length - 1];
    const body = JSON.parse(lastCall[1]?.body as string);
    expect(body.stripe_publishable_key).toBe("pk_live_new");

    await waitFor(() => expect(screen.getByRole("button", { name: "Clear publishable key…" })).not.toBeDisabled());
    await confirmClear("publishable key");
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(2));
    const clearCall = staffRequest.mock.calls[1];
    const clearBody = JSON.parse(clearCall[1]?.body as string);
    expect(clearBody.stripe_publishable_key).toBe("");
  });

  it("revokes secret credentials explicitly without rendering returned secret-shaped fields", async () => {
    query.mockReturnValue({
      data: {
        id: 1,
        stripe_publishable_key_set: true,
        stripe_secret_key: "sk_stored_never_rendered",
        stripe_secret_key_set: true,
        stripe_webhook_secret: "whsec_stored_never_rendered",
        stripe_webhook_secret_set: true,
        stripe_connect_client_id: "ca_platform",
        application_fee_bps: 125,
        updated_at: "2026-07-22T00:00:00Z",
      },
      isLoading: false,
      error: null,
    });
    staffRequest.mockResolvedValue({});
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PlatformStripeConnectPanel />
      </QueryClientProvider>,
    );

    expect(screen.queryByDisplayValue("sk_stored_never_rendered")).toBeNull();
    expect(screen.queryByDisplayValue("whsec_stored_never_rendered")).toBeNull();

    await confirmClear("secret key");
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(1));
    expect(JSON.parse(staffRequest.mock.calls[0][1]?.body as string)).toEqual({
      stripe_secret_key: "",
    });

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Clear webhook secret…" })).not.toBeDisabled(),
    );
    await confirmClear("webhook secret");
    await waitFor(() => expect(staffRequest).toHaveBeenCalledTimes(2));
    expect(JSON.parse(staffRequest.mock.calls[1][1]?.body as string)).toEqual({
      stripe_webhook_secret: "",
    });
  });

  it("surfaces the pending-session safeguard when webhook revocation is rejected", async () => {
    query.mockReturnValue({
      data: {
        id: 1,
        stripe_publishable_key_set: true,
        stripe_secret_key_set: true,
        stripe_webhook_secret_set: true,
        stripe_connect_client_id: "ca_platform",
        application_fee_bps: 125,
        updated_at: "2026-07-22T00:00:00Z",
      },
      isLoading: false,
      error: null,
    });
    staffRequest.mockRejectedValueOnce(
      new Error("Cannot change the webhook secret while Connect sessions are pending."),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PlatformStripeConnectPanel />
      </QueryClientProvider>,
    );

    await confirmClear("webhook secret");

    expect(await screen.findByRole("alert")).toHaveTextContent(/sessions are pending/i);
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Clear webhook secret…" })).not.toBeDisabled();
  });
});

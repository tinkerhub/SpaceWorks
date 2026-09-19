/**
 * The checked-in borrow form.
 *
 * The property that matters: the request cannot be submitted until a roster entry has
 * been CONFIRMED, and what gets sent is the mid of that entry plus its canonical name --
 * never a contact field, because this policy collects none. Mirrors the account-less
 * test next door, which exists because that form once shipped unable to submit at all.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { submitPublicRequest, lookupCheckin, getAccessToken, memberRequest, refreshAccessToken } =
  vi.hoisted(() => ({
    submitPublicRequest: vi.fn(),
    lookupCheckin: vi.fn(),
    getAccessToken: vi.fn(),
    memberRequest: vi.fn(),
    refreshAccessToken: vi.fn(),
  }));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, submitPublicRequest, lookupCheckin };
});

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, getAccessToken, memberRequest, refreshAccessToken };
});

import { PublicRequestPanel } from "./PublicRequestPanel";

const ITEMS = [{ productId: 7, name: "Logic analyzer", quantity: 1 }];

const ELIGIBLE = {
  mid: 443,
  name: "Ada Example",
  avatar: "",
  purpose: "Working on a project",
  project_name: "Metrocard",
  eligible: true,
  reason: "" as const,
};

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <PublicRequestPanel
        requestAccess="checked_in"
        items={ITEMS}
        makerspaceSlug="makerspace"
        onClear={() => {}}
      />
    </QueryClientProvider>,
  );
}

async function confirmIdentity() {
  fireEvent.change(screen.getByLabelText(/your name/i), {
    target: { value: "ada example" },
  });
  fireEvent.click(screen.getByRole("button", { name: /find me/i }));
  await waitFor(() => expect(lookupCheckin).toHaveBeenCalled());
}

describe("checked-in borrow requests", () => {
  beforeEach(() => {
    submitPublicRequest.mockReset();
    submitPublicRequest.mockResolvedValue({ public_token: "tok-abc-123" });
    lookupCheckin.mockReset();
    getAccessToken.mockReset();
    getAccessToken.mockReturnValue(null);
    memberRequest.mockReset();
    memberRequest.mockResolvedValue({ memberships: [], requests: [] });
    refreshAccessToken.mockReset();
    refreshAccessToken.mockResolvedValue(null);
  });

  it("describes the account-less roster path", async () => {
    renderPanel();

    expect(await screen.findByRole("heading", { name: "Borrow with check-in" }))
      .toBeInTheDocument();
    expect(screen.getByText(/no account needed.*upstream check-in roster/i))
      .toBeInTheDocument();
  });

  it("asks for a name instead of contact details", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByLabelText(/your name/i)).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
  });

  it("sends the confirmed mid and the canonical roster name", async () => {
    lookupCheckin.mockResolvedValue([ELIGIBLE]);
    renderPanel();
    await waitFor(() =>
      expect(screen.getByLabelText(/your name/i)).toBeInTheDocument(),
    );
    await confirmIdentity();

    fireEvent.change(screen.getByLabelText(/what.*for|purpose|needed for/i), {
      target: { value: "Bench testing" },
    });
    const submit = screen.getByRole("button", { name: /submit|send request/i });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() => expect(submitPublicRequest).toHaveBeenCalled());
    const [, payload, idempotencyKey] = submitPublicRequest.mock.calls[0];
    // The CANONICAL name, not "ada example" as typed.
    expect(payload.name).toBe("Ada Example");
    expect(payload.checkin_mid).toBe(443);
    expect(payload.contact_email).toBeUndefined();
    expect(payload.contact_phone).toBeUndefined();
    expect(idempotencyKey).toBeTruthy();
  });

  it("still requires roster identity for an authenticated non-member", async () => {
    getAccessToken.mockReturnValue("access-token");
    lookupCheckin.mockResolvedValue([ELIGIBLE]);
    renderPanel();

    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/memberships/me"));
    expect(await screen.findByLabelText(/your name/i)).toBeInTheDocument();
    await confirmIdentity();
    fireEvent.change(screen.getByLabelText(/what.*for|purpose|needed for/i), {
      target: { value: "Bench testing" },
    });
    const submit = screen.getByRole("button", { name: /submit|send request/i });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() => expect(submitPublicRequest).toHaveBeenCalled());
    const [, payload, idempotencyKey] = submitPublicRequest.mock.calls[0];
    expect(payload).toMatchObject({ name: "Ada Example", checkin_mid: 443 });
    expect(idempotencyKey).toBeTruthy();
  });

  it("lets only an active membership bypass roster identity", async () => {
    getAccessToken.mockReturnValue("access-token");
    memberRequest.mockResolvedValue({
      memberships: [{
        makerspace: { slug: "makerspace" },
        membership_status: "active",
      }],
      requests: [],
    });
    renderPanel();

    await waitFor(() => expect(memberRequest).toHaveBeenCalledWith("/memberships/me"));
    fireEvent.change(screen.getByLabelText(/what.*for|purpose|needed for/i), {
      target: { value: "Bench testing" },
    });
    const submit = screen.getByRole("button", { name: /submit|send request/i });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() => expect(submitPublicRequest).toHaveBeenCalled());
    const [, payload, idempotencyKey] = submitPublicRequest.mock.calls[0];
    expect(payload.checkin_mid).toBeUndefined();
    expect(idempotencyKey).toBeUndefined();
    expect(screen.queryByLabelText(/your name/i)).not.toBeInTheDocument();
  });

  it("explains a fixable refusal rather than just failing", async () => {
    lookupCheckin.mockResolvedValue([
      { ...ELIGIBLE, eligible: false, reason: "project" as const, project_name: "" },
    ]);
    renderPanel();
    await waitFor(() =>
      expect(screen.getByLabelText(/your name/i)).toBeInTheDocument(),
    );
    await confirmIdentity();

    expect(await screen.findByText(/have not chosen one/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /that's me/i })).toBeDisabled();
  });

  it("says so when nobody matches the typed name", async () => {
    lookupCheckin.mockResolvedValue([]);
    renderPanel();
    await waitFor(() =>
      expect(screen.getByLabelText(/your name/i)).toBeInTheDocument(),
    );
    await confirmIdentity();

    expect(await screen.findByText(/no one is checked in under that name/i))
      .toBeInTheDocument();
  });

  it("does not auto-pick when two people share a name", async () => {
    lookupCheckin.mockResolvedValue([
      { ...ELIGIBLE, mid: 1 },
      { ...ELIGIBLE, mid: 2, project_name: "Other project" },
    ]);
    renderPanel();
    await waitFor(() =>
      expect(screen.getByLabelText(/your name/i)).toBeInTheDocument(),
    );
    await confirmIdentity();

    // Both offered, neither confirmed: choosing for them would file the request
    // against the wrong person.
    expect(await screen.findAllByRole("button", { name: /that's me/i })).toHaveLength(2);
  });
});

import { useState } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useParams } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
const { tenantPublicRequest } = vi.hoisted(() => ({ tenantPublicRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest,
}));
import { setAccessToken } from "../../lib/apiSession";
import { accessToken } from "../../test/accessTokens";
import { confirmPerson, deferred, fillContact, lendingClient, mountLending, nextPerson,
  resetLendingSession, rosterMatch, selection } from "../../test/publicLendingHarness";
import { PublicRequestPanel } from "./PublicRequestPanel";

function BorrowRoute({ checkedIn = false }: { checkedIn?: boolean }) {
  const { slug = "" } = useParams();
  const [items, setItems] = useState(selection);
  const [, force] = useState(0);
  return <>
    <button onClick={() => setItems([{ productId: 8, name: "Current drill", quantity: 2 }])}>Change selection</button>
    <button onClick={() => { setAccessToken(accessToken("borrow-next-session", { user_id: 2 })); force((n) => n + 1); }}>New session</button>
    <PublicRequestPanel makerspaceSlug={slug} items={items} onClear={() => setItems([])}
      requestAccess={checkedIn ? "checked_in" : "anyone"} requestStatusHref={`/m/${slug}/request`} />
  </>;
}
const requests = () => tenantPublicRequest.mock.calls.filter(([, path]) => String(path).endsWith("/requests"));
const requestKey = (index: number) => new Headers(requests()[index][2].headers).get("Idempotency-Key");
const submit = () => fireEvent.click(screen.getByRole("button", { name: "Submit request" }));

beforeEach(() => { resetLendingSession(); tenantPublicRequest.mockReset(); });

describe("borrow draft admission and completion ownership", () => {
  it("deduplicates same-tick submissions, captures the body, reuses failed-body keys and rotates changed-body keys", async () => {
    const held = deferred<unknown>();
    tenantPublicRequest.mockReturnValueOnce(held.promise).mockRejectedValue(new Error("Retry this body"));
    mountLending(<BorrowRoute />);
    fillContact();
    act(() => { submit(); submit(); });
    await waitFor(() => expect(requests()).toHaveLength(1));
    const firstBody = requests()[0][2].body;
    expect(JSON.parse(firstBody)).toEqual({ requested_for: "Bench project", website: "", contact_name: "Ada Contact",
      contact_email: "ada@example.com", contact_phone: "12345", items: [{ product_id: 7, quantity: 1 }] });
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "Ignored while pending" } });
    expect(screen.getByLabelText("Request purpose")).toHaveValue("Bench project");
    await act(async () => { held.reject(new Error("Retry this body")); });
    expect(await screen.findByText("Retry this body")).toBeInTheDocument();
    submit();
    await waitFor(() => expect(requests()).toHaveLength(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit request" })).toBeEnabled());
    expect(requests()[1][2].body).toBe(firstBody);
    expect(requestKey(0)).toBeTruthy();
    expect(requestKey(1)).toBe(requestKey(0));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "changed@example.com" } });
    submit();
    await waitFor(() => expect(requests()).toHaveLength(3));
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit request" })).toBeEnabled());
    expect(requestKey(2)).not.toBe(requestKey(1));
    expect(JSON.parse(requests()[2][2].body).contact_email).toBe("changed@example.com");
  });

  it.each(["success", "rejection"] as const)("old maker %s cannot publish a token, clear B cart/draft or toast, or unlock B's pending request", async (outcome) => {
    const a = deferred<unknown>();
    const b = deferred<unknown>();
    tenantPublicRequest.mockImplementation((slug: string) => slug === "a" ? a.promise : b.promise);
    mountLending(<BorrowRoute />);
    fillContact("A purpose"); submit();
    await waitFor(() => expect(requests()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Visit B" }));
    expect(screen.getByLabelText("Your name")).toHaveValue("");
    expect(screen.getByLabelText("Request purpose")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Change selection" }));
    fillContact("B purpose"); submit();
    await waitFor(() => expect(requests()).toHaveLength(2));
    await act(async () => {
      if (outcome === "success") a.resolve({ public_token: "a-private-reference", status: "pending_approval" });
      else a.reject(new Error("A obsolete rejection"));
    });
    expect(screen.getByLabelText("Request purpose")).toHaveValue("B purpose");
    expect(screen.getByText("Current drill")).toBeInTheDocument();
    expect(screen.getByLabelText("Your name")).toHaveValue("Ada Contact");
    expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled();
    expect(screen.queryByText("a-private-reference")).not.toBeInTheDocument();
    expect(screen.queryByText("A obsolete rejection")).not.toBeInTheDocument();
    expect(screen.queryByText("Your request was not submitted")).not.toBeInTheDocument();
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    await act(async () => { b.resolve({ public_token: "b-reference", status: "pending_approval" }); });
    expect(await screen.findByText("b-reference")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Check its status" })).toHaveAttribute("href", "/m/b/request?token=b-reference");
    expect(screen.queryByText("Current drill")).not.toBeInTheDocument();
  });

  it.each(["success", "rejection"] as const)("old session %s cannot publish after an actor switch", async (outcome) => {
    const held = deferred<unknown>();
    tenantPublicRequest.mockReturnValue(held.promise);
    mountLending(<BorrowRoute />);
    fillContact(); submit();
    await waitFor(() => expect(requests()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "New session" }));
    expect(screen.getByLabelText("Request purpose")).toHaveValue("");
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "New member draft" } });
    await act(async () => {
      if (outcome === "success") held.resolve({ public_token: "old-reference", status: "pending_approval" });
      else held.reject(new Error("Old member failure"));
    });
    expect(screen.getByLabelText("Request purpose")).toHaveValue("New member draft");
    expect(screen.getByText("Logic analyzer")).toBeInTheDocument();
    expect(screen.queryByText("old-reference")).not.toBeInTheDocument();
    expect(screen.queryByText("Old member failure")).not.toBeInTheDocument();
    expect(screen.queryByText("Request submitted")).not.toBeInTheDocument();
    expect(screen.queryByText("Your request was not submitted")).not.toBeInTheDocument();
  });

  it("changing confirmed people clears purpose and captures only the new canonical check-in identity", async () => {
    tenantPublicRequest.mockImplementation((_slug: string, path: string, options: RequestInit) => {
      if (path.endsWith("/checkin/lookup")) return Promise.resolve([JSON.parse(String(options.body)).name === "bea typed" ? nextPerson : rosterMatch]);
      return Promise.resolve({ public_token: "bea-reference", status: "pending_approval" });
    });
    mountLending(<BorrowRoute checkedIn />, lendingClient("checked_in"));
    await confirmPerson();
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "Ada purpose" } });
    fireEvent.click(screen.getByRole("button", { name: "Not you?" }));
    expect(screen.getByLabelText("Request purpose")).toHaveValue("");
    await confirmPerson("bea typed");
    expect(screen.getByRole("button", { name: "Submit request" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "Bea purpose" } }); submit();
    expect(await screen.findByText("bea-reference")).toBeInTheDocument();
    expect(JSON.parse(requests()[0][2].body)).toMatchObject({ name: nextPerson.name, checkin_mid: nextPerson.mid, requested_for: "Bea purpose" });
  });

  it("kiosk success retains its reference and status link after clearing the person; next draft is unconfirmed", async () => {
    tenantPublicRequest.mockImplementation((_slug: string, path: string) => Promise.resolve(path.endsWith("/checkin/lookup")
      ? [rosterMatch] : { public_token: "saved-kiosk-reference", status: "pending_approval" }));
    mountLending(<BorrowRoute checkedIn />, lendingClient("checked_in"));
    await confirmPerson();
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "Kiosk project" } }); submit();
    expect(await screen.findByText("saved-kiosk-reference")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Check its status" })).toHaveAttribute("href", "/m/a/request?token=saved-kiosk-reference");
    expect(screen.queryByRole("button", { name: "Not you?" })).not.toBeInTheDocument();
    expect(screen.getByLabelText(/your name, as it appears/i)).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Start another request" }));
    expect(screen.queryByText("saved-kiosk-reference")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Change selection" }));
    fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "Next project" } });
    expect(screen.getByRole("button", { name: "Submit request" })).toBeDisabled();
    expect(requests()).toHaveLength(1);
  });

  it("passes the captured item list to its parent even if the source array is later mutated", async () => {
    const held = deferred<unknown>();
    tenantPublicRequest.mockReturnValue(held.promise);
    const cleared = vi.fn();
    const sourceItems = selection.map((item) => ({ ...item }));
    const client = lendingClient();
    mountLending(<PublicRequestPanel makerspaceSlug="a" items={sourceItems} onClear={cleared} requestAccess="anyone" />, client);
    fillContact(); submit();
    await waitFor(() => expect(requests()).toHaveLength(1));
    sourceItems[0].quantity = 3;
    await act(async () => { held.resolve({ public_token: "captured-reference", status: "pending_approval" }); });
    expect(await screen.findByText("captured-reference")).toBeInTheDocument();
    expect(cleared).toHaveBeenCalledWith([{ productId: 7, name: "Logic analyzer", quantity: 1 }]);
    expect(JSON.parse(requests()[0][2].body).items).toEqual([{ product_id: 7, quantity: 1 }]);
  });
});

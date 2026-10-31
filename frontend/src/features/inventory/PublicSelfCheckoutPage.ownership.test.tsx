import { useState } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { tenantPublicRequest, native, bootstrapTenant } = vi.hoisted(() => ({
  bootstrapTenant: vi.fn(), tenantPublicRequest: vi.fn(), native: { scan: undefined as undefined | ((value: string) => void) },
}));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest, bootstrapTenant,
}));
vi.mock("../../components/ui/QrScanner", () => ({ default: ({ onScan }: { onScan: (payload: string) => void }) => {
  native.scan = onScan;
  return <>{["tool-a", "tool-b"].map((payload) => <button key={payload} onClick={() => onScan(payload)}>Read {payload}</button>)}</>;
} }));
import { setAccessToken } from "../../lib/apiSession";
import { accessToken } from "../../test/accessTokens";
import { bootstrapFixture } from "../../test/uiRegressionHarness";
import { confirmPerson, deferred, lendingClient, loanResult, mountLending, nextPerson, presign,
  resetLendingSession, rosterMatch, uploadPhoto } from "../../test/publicLendingHarness";
import { PublicSelfCheckoutPage } from "./PublicSelfCheckoutPage";
const operations = vi.fn();
function CheckoutRoute() {
  const [, force] = useState(0);
  return <><button onClick={() => { setAccessToken(accessToken("dedicated-next-actor", { user_id: 2 })); force((n) => n + 1); }}>New session</button>
    <PublicSelfCheckoutPage /></>;
}
function scan(payload = "tool-a", entry = "Scan QR") {
  fireEvent.click(screen.getByRole("button", { name: entry }));
  fireEvent.click(screen.getByRole("button", { name: `Read ${payload}` }));
}
function mountCheckout() { return mountLending(<CheckoutRoute />, lendingClient("checked_in")); }
beforeEach(() => {
  bootstrapTenant.mockImplementation(async ({ slug }: { slug: string }) => bootstrapFixture(slug));
  resetLendingSession(); tenantPublicRequest.mockReset(); operations.mockReset(); native.scan = undefined;
  operations.mockResolvedValue(loanResult());
  tenantPublicRequest.mockImplementation((slug: string, path: string, options: RequestInit) => {
    if (path.endsWith("/evidence-url")) return Promise.resolve(presign(JSON.parse(String(options.body)).evidence_type === "issue" ? 91 : 92));
    if (path.endsWith("/checkin/lookup")) return Promise.resolve([JSON.parse(String(options.body)).name === "bea typed" ? nextPerson : rosterMatch]);
    return operations(slug, path, options);
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("dedicated public checkout page ownership", () => {
  it.each([
    ["maker", "success"], ["maker", "rejection"], ["session", "success"], ["session", "rejection"],
  ] as const)("old %s %s cannot render, clear fresh scans/evidence or unlock the current checkout", async (scope, outcome) => {
    const old = deferred<unknown>(); const current = deferred<unknown>();
    operations.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    mountCheckout(); await confirmPerson(); scan(); await uploadPhoto();
    fireEvent.click(screen.getByRole("button", { name: "Check out 1 tool" }));
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: scope === "maker" ? "Visit B" : "New session" }));
    expect(screen.getByLabelText("Issue photo")).toBeDisabled();
    expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    await confirmPerson("bea typed"); scan("tool-b"); await uploadPhoto();
    fireEvent.click(screen.getByRole("button", { name: "Check out 1 tool" }));
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(2));
    await act(async () => {
      if (outcome === "success") old.resolve({ ...loanResult(), items: [{ product_name: "Old private tool", quantity: 1 }] });
      else old.reject(new Error("Old dedicated failure"));
    });
    expect(screen.getByRole("list", { name: "Pending tools" })).toHaveTextContent("tool-b");
    expect(screen.getByLabelText("Issue photo")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "Return" })).toBeDisabled();
    expect(screen.queryByText(/Old private tool/)).not.toBeInTheDocument();
    expect(screen.queryByText("Old dedicated failure")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool checked out")).not.toBeInTheDocument();
    expect(screen.queryByText("Checkout failed")).not.toBeInTheDocument();
    await act(async () => { current.resolve({ ...loanResult(), items: [{ product_name: "Current drill", quantity: 1 }] }); });
    expect(await screen.findByText("Issued: Current drill")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    expect(JSON.parse(operations.mock.calls[0][2].body)).toEqual({ payload: "tool-a", evidence_id: 91,
      name: rosterMatch.name, checkin_mid: rosterMatch.mid });
    expect(JSON.parse(operations.mock.calls[1][2].body)).toEqual({ payload: "tool-b", evidence_id: 91,
      name: nextPerson.name, checkin_mid: nextPerson.mid });
  });

  it("captures a multi-tool body once, deduplicates same-tick submit, and blocks mode/person edits until it settles", async () => {
    const held = deferred<unknown>(); operations.mockReturnValue(held.promise);
    mountCheckout(); await confirmPerson();
    expect(screen.getByRole("button", { name: "Check out 0 tools" })).toBeDisabled();
    scan(); scan("tool-b", "Scan another");
    expect(screen.getByRole("button", { name: "Check out 2 tools" })).toBeDisabled();
    await uploadPhoto();
    const submit = screen.getByRole("button", { name: "Check out 2 tools" });
    act(() => { fireEvent.click(submit); fireEvent.click(submit); });
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("radio", { name: "Return" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Not you?" })).toBeDisabled();
    const body = operations.mock.calls[0][2].body;
    expect(JSON.parse(body)).toEqual({ qr_payloads: ["tool-a", "tool-b"], evidence_id: 91,
      checkin_mid: rosterMatch.mid, name: rosterMatch.name });
    fireEvent.click(screen.getByRole("button", { name: "Remove tool 1" }));
    expect(operations.mock.calls[0][2].body).toBe(body);
    await act(async () => { held.resolve({ ...loanResult(), items: [
      { product_name: "Analyzer", quantity: 1 }, { product_name: "Drill", quantity: 1 },
    ] }); });
    expect(await screen.findByText("Issued: Analyzer, Drill")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    expect(screen.queryByText("Photo uploaded")).not.toBeInTheDocument();
  });

  it("return needs a fresh photo, notes and scan; a stale checkout camera callback cannot enqueue or submit", async () => {
    mountCheckout(); await confirmPerson();
    fireEvent.click(screen.getByRole("button", { name: "Scan QR" }));
    const oldScan = native.scan;
    expect(oldScan).toBeTypeOf("function");
    fireEvent.click(screen.getByRole("radio", { name: "Return" }));
    expect(screen.getByRole("button", { name: "Scan QR" })).toBeDisabled();
    act(() => { oldScan!("old-checkout-tool"); });
    expect(operations).not.toHaveBeenCalled();
    expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    await uploadPhoto("Return photo");
    expect(screen.getByRole("button", { name: "Scan QR" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Return condition notes"), { target: { value: "  Returned clean  " } });
    scan("tool-b");
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(1));
    expect(operations.mock.calls[0][1]).toBe("/public/a/tools/return");
    expect(JSON.parse(operations.mock.calls[0][2].body)).toEqual({ payload: "tool-b", evidence_id: 92,
      remark: "Returned clean", name: rosterMatch.name, checkin_mid: rosterMatch.mid });
  });

  it.each(["mode", "person"] as const)("a new %s hides the previous dedicated result/error and cannot reuse evidence", async (transition) => {
    if (transition === "person") operations.mockRejectedValue(new Error("Previous person's error"));
    mountCheckout(); await confirmPerson(); scan(); await uploadPhoto();
    fireEvent.click(screen.getByRole("button", { name: "Check out 1 tool" }));
    await screen.findByText(transition === "mode" ? "Issued: Logic analyzer" : "Previous person's error");
    await waitFor(() => expect(screen.getByRole("button", { name: "Not you?" })).toBeEnabled());
    if (transition === "mode") {
      fireEvent.click(screen.getByRole("radio", { name: "Return" }));
      expect(screen.getByRole("button", { name: "Scan QR" })).toBeDisabled();
      expect(screen.getByLabelText("Return condition notes")).toHaveValue("");
    } else {
      fireEvent.click(screen.getByRole("button", { name: "Not you?" }));
      await confirmPerson("bea typed");
      expect(screen.getByRole("button", { name: "Check out 0 tools" })).toBeDisabled();
      expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    }
    expect(screen.queryByText("Issued: Logic analyzer")).not.toBeInTheDocument();
    expect(screen.queryByText("Previous person's error")).not.toBeInTheDocument();
    expect(screen.queryByText("Photo uploaded")).not.toBeInTheDocument();
  });
});

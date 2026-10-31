import { useState } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { useParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { tenantPublicRequest, bootstrapTenant } = vi.hoisted(() => ({ tenantPublicRequest: vi.fn(), bootstrapTenant: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest, bootstrapTenant,
}));
vi.mock("../../components/ui/QrScanner", () => ({ default: ({ onScan }: { onScan: (payload: string) => void }) =>
  <>{["tool-a", "tool-b"].map((payload) => <button key={payload} onClick={() => onScan(payload)}>Read {payload}</button>)}</>,
}));
import { setAccessToken } from "../../lib/apiSession";
import { accessToken } from "../../test/accessTokens";
import { bootstrapFixture } from "../../test/uiRegressionHarness";
import { confirmPerson, deferred, lendingClient, loanResult, mountLending, nextPerson, presign,
  resetLendingSession, rosterMatch, uploadPhoto } from "../../test/publicLendingHarness";
import { PublicToolScanPanel } from "./PublicToolScanPanel";
const operations = vi.fn();
function ToolRoute({ checkedIn = false }: { checkedIn?: boolean }) {
  const { slug = "" } = useParams();
  const [, force] = useState(0);
  return <><button onClick={() => { setAccessToken(accessToken("tool-new-actor", { user_id: 2 })); force((n) => n + 1); }}>New session</button>
    <PublicToolScanPanel makerspaceSlug={slug} requiresCheckin={checkedIn} /></>;
}
function scan(payload = "tool-a", entry = "Scan QR with camera") {
  fireEvent.click(screen.getByRole("button", { name: entry }));
  fireEvent.click(screen.getByRole("button", { name: `Read ${payload}` }));
}
async function prepareBoth() {
  scan(); await uploadPhoto(); await uploadPhoto("Return photo");
  fireEvent.change(screen.getByLabelText("Return condition notes"), { target: { value: "Clean and complete" } });
}
beforeEach(() => {
  bootstrapTenant.mockImplementation(async ({ slug }: { slug: string }) => bootstrapFixture(slug));
  resetLendingSession(); tenantPublicRequest.mockReset(); operations.mockReset();
  operations.mockResolvedValue(loanResult());
  tenantPublicRequest.mockImplementation((slug: string, path: string, options: RequestInit) => {
    if (path.endsWith("/evidence-url")) return Promise.resolve(presign(JSON.parse(String(options.body)).evidence_type === "issue" ? 91 : 92));
    if (path.endsWith("/checkin/lookup")) return Promise.resolve([JSON.parse(String(options.body)).name === "bea typed" ? nextPerson : rosterMatch]);
    return operations(slug, path, options);
  });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("inline public tool operation ownership", () => {
  it.each(["checkout", "return"] as const)("%s admits first and blocks the reverse operation in the same tick", async (first) => {
    const held = deferred<unknown>(); operations.mockReturnValue(held.promise);
    mountLending(<ToolRoute />); await prepareBoth();
    const checkout = screen.getByRole("button", { name: "Check out 1 tool" });
    const returning = screen.getByRole("button", { name: "Return" });
    act(() => {
      fireEvent.click(first === "checkout" ? checkout : returning);
      fireEvent.click(first === "checkout" ? returning : checkout);
    });
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(1));
    expect(operations.mock.calls[0][1]).toBe(`/public/a/tools/${first}`);
    expect(screen.getByLabelText("Issue photo")).toBeDisabled();
    expect(screen.getByLabelText("Return photo")).toBeDisabled();
    expect(screen.getByLabelText("Return condition notes")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Scan QR with camera" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove tool 1" })).toBeDisabled();
    await act(async () => { held.resolve(loanResult()); });
    expect(await screen.findByText("loan-reference")).toBeInTheDocument();
  });

  it.each(([
    ["maker", "success"], ["maker", "rejection"], ["session", "success"], ["session", "rejection"],
  ] as const).flatMap(([scope, outcome]) => (["checkout", "return"] as const).map((operation) => ({ scope, outcome, operation }))))(
    "old $scope $operation $outcome cannot render, toast, clear current evidence/scans, or unlock current pending state", async ({ scope, outcome, operation }) => {
    const old = deferred<unknown>(); const current = deferred<unknown>();
    operations.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    mountLending(<ToolRoute />); await prepareBoth();
    fireEvent.click(screen.getByRole("button", { name: operation === "checkout" ? "Check out 1 tool" : "Return" }));
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: scope === "maker" ? "Visit B" : "New session" }));
    expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Return condition notes")).toHaveValue("");
    scan("tool-b"); await uploadPhoto();
    fireEvent.click(screen.getByRole("button", { name: "Check out 1 tool" }));
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(2));
    await act(async () => {
      if (outcome === "success") old.resolve(loanResult("old-tool-reference"));
      else old.reject(new Error("Old checkout failed"));
    });
    expect(screen.getByRole("list", { name: "Pending tools" })).toHaveTextContent("tool-b");
    expect(screen.getByLabelText("Issue photo")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Checking out…" })).toBeDisabled();
    expect(screen.queryByText("old-tool-reference")).not.toBeInTheDocument();
    expect(screen.queryByText("Old checkout failed")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool checked out")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool returned")).not.toBeInTheDocument();
    expect(screen.queryByText("Checkout failed")).not.toBeInTheDocument();
    expect(screen.queryByText("Return failed")).not.toBeInTheDocument();
    await act(async () => { current.resolve(loanResult("current-tool-reference")); });
    expect(await screen.findByText("current-tool-reference")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    expect(JSON.parse(operations.mock.calls[0][2].body)).toEqual(operation === "checkout"
      ? { payload: "tool-a", evidence_id: 91 }
      : { payload: "tool-a", evidence_id: 92, remark: "Clean and complete", report_problem: false, problem_note: "" });
    expect(JSON.parse(operations.mock.calls[1][2].body)).toEqual({ payload: "tool-b", evidence_id: 91 });
  });

  it.each(["success", "rejection"] as const)("a different confirmed person cannot see the previous person's %s, scans, notes or evidence", async (outcome) => {
    if (outcome === "rejection") operations.mockRejectedValue(new Error("Ada checkout error"));
    mountLending(<ToolRoute checkedIn />, lendingClient("checked_in"));
    await confirmPerson(); await prepareBoth();
    fireEvent.click(screen.getByRole("button", { name: "Check out 1 tool" }));
    await screen.findByText(outcome === "success" ? "loan-reference" : "Ada checkout error");
    await waitFor(() => expect(screen.getByRole("button", { name: "Not you?" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Not you?" }));
    expect(screen.queryByText("loan-reference")).not.toBeInTheDocument();
    expect(screen.queryByText("Ada checkout error")).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Return condition notes")).toHaveValue("");
    expect(screen.getByLabelText("Issue photo")).toBeDisabled();
    await confirmPerson("bea typed");
    expect(screen.getByLabelText("Issue photo")).toBeEnabled();
    expect(screen.queryByText("Photo uploaded")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check out 0 tools" })).toBeDisabled();
  });

  it("requires scanned QR, issue/return photos, return remark and a problem note", async () => {
    mountLending(<ToolRoute />);
    expect(screen.getByRole("button", { name: "Check out 0 tools" })).toBeDisabled();
    scan();
    expect(screen.getByRole("button", { name: "Check out 1 tool" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
    await uploadPhoto("Return photo");
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Return condition notes"), { target: { value: "Damaged grip" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Report a problem with this tool" }));
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("What's wrong?"), { target: { value: "Grip is torn" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("button", { name: "Return" })).toBeDisabled();
    scan(); fireEvent.click(screen.getByRole("button", { name: "Return" }));
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(1));
    expect(JSON.parse(operations.mock.calls[0][2].body)).toEqual({ payload: "tool-a", evidence_id: 92,
      remark: "Damaged grip", report_problem: true, problem_note: "Grip is torn" });
  });

  it("legitimate multi-tool checkout captures both scans and clears them only on current success", async () => {
    const held = deferred<unknown>(); operations.mockReturnValue(held.promise);
    mountLending(<ToolRoute />); scan(); scan("tool-b", "Scan another"); await uploadPhoto();
    fireEvent.click(screen.getByRole("button", { name: "Check out 2 tools" }));
    await waitFor(() => expect(operations).toHaveBeenCalledTimes(1));
    expect(JSON.parse(operations.mock.calls[0][2].body)).toEqual({ qr_payloads: ["tool-a", "tool-b"], evidence_id: 91 });
    fireEvent.click(screen.getByRole("button", { name: "Remove tool 1" }));
    expect(screen.getByRole("list", { name: "Pending tools" })).toHaveTextContent("tool-a");
    await act(async () => { held.resolve({ ...loanResult(), items: [
      { product_name: "Logic analyzer", quantity: 1 }, { product_name: "Drill", quantity: 1 },
    ] }); });
    expect(await screen.findByText("Issued: Logic analyzer, Drill")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Pending tools" })).not.toBeInTheDocument();
    expect(screen.queryByText("Photo uploaded")).not.toBeInTheDocument();
  });
});

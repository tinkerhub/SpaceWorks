import { useState, type ComponentProps } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { tenantPublicRequest } = vi.hoisted(() => ({ tenantPublicRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), tenantPublicRequest,
}));
import { setAccessToken } from "../../lib/apiSession";
import { accessToken } from "../../test/accessTokens";
import { deferred, lendingClient, nextPerson, photo, presign, resetLendingSession, rosterMatch } from "../../test/publicLendingHarness";
import { RegressionProviders } from "../../test/uiRegressionHarness";
import { PublicEvidenceUpload } from "./PublicEvidenceUpload";

type Scope = Omit<ComponentProps<typeof PublicEvidenceUpload>, "onUploaded">;
const initial: Scope = { slug: "a", evidenceType: "issue", checkinIdentity: rosterMatch };
const storage = vi.fn<typeof fetch>();
const published = vi.fn();
function EvidenceHost(props: Scope) {
  const [evidence, setEvidence] = useState<number | null>(null);
  const [, force] = useState(0);
  return <>
    <button onClick={() => force((n) => n + 1)}>Rerender callback</button>
    <span data-testid="evidence">{evidence ?? "none"}</span>
    <PublicEvidenceUpload {...props} onUploaded={(id) => { published(id); setEvidence(id); }} />
  </>;
}
function mountEvidence() {
  const client = lendingClient();
  return render(<EvidenceHost {...initial} />, {
    wrapper: ({ children }) => <RegressionProviders client={client}>{children}</RegressionProviders>,
  });
}
function select(label = "Issue photo") {
  fireEvent.change(screen.getByLabelText(label), { target: { files: [photo()] } });
}
const changedScopes: [string, () => Scope][] = [
  ["slug", () => ({ ...initial, slug: "b" })],
  ["type", () => ({ ...initial, evidenceType: "return" })],
  ["check-in mid", () => ({ ...initial, checkinIdentity: { ...rosterMatch, mid: nextPerson.mid } })],
  ["check-in canonical name", () => ({ ...initial, checkinIdentity: { ...rosterMatch, name: nextPerson.name } })],
  ["session epoch", () => { setAccessToken(accessToken("evidence-next-actor", { user_id: 2 })); return initial; }],
];
beforeEach(() => {
  resetLendingSession(); tenantPublicRequest.mockReset(); published.mockReset(); storage.mockReset();
  storage.mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", storage);
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("public evidence upload semantic ownership", () => {
  it.each(changedScopes)("held presign from an obsolete %s never dispatches storage bytes", async (_name, change) => {
    const held = deferred<unknown>();
    tenantPublicRequest.mockReturnValue(held.promise);
    const view = mountEvidence();
    select();
    await waitFor(() => expect(tenantPublicRequest).toHaveBeenCalledTimes(1));
    const next = change();
    view.rerender(<EvidenceHost {...next} />);
    const label = next.evidenceType === "return" ? "Return photo" : "Issue photo";
    expect(screen.getByLabelText(label)).toHaveValue("");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.getByTestId("evidence")).toHaveTextContent("none");
    published.mockClear();
    await act(async () => { held.resolve(presign()); });
    expect(storage).not.toHaveBeenCalled();
    expect(published).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it.each(changedScopes.flatMap(([scope, change]) => (["success", "rejection"] as const).map((outcome) => ({ scope, change, outcome }))))(
    "obsolete $scope raw upload $outcome cannot publish, clear, error or unlock the current upload", async ({ change, outcome }) => {
    tenantPublicRequest.mockResolvedValueOnce(presign(91)).mockResolvedValueOnce(presign(92));
    const oldBytes = deferred<Response>();
    const newBytes = deferred<Response>();
    storage.mockReturnValueOnce(oldBytes.promise).mockReturnValueOnce(newBytes.promise);
    const view = mountEvidence();
    select();
    await waitFor(() => expect(storage).toHaveBeenCalledTimes(1));
    const next = change();
    view.rerender(<EvidenceHost {...next} />);
    const label = next.evidenceType === "return" ? "Return photo" : "Issue photo";
    select(label);
    await waitFor(() => expect(storage).toHaveBeenCalledTimes(2));
    published.mockClear();
    await act(async () => {
      if (outcome === "success") oldBytes.resolve(new Response(null, { status: 204 }));
      else oldBytes.reject(new Error("Obsolete storage failure"));
    });
    expect(screen.getByLabelText(label)).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Uploading evidence.jpg…");
    expect(screen.getByTestId("evidence")).toHaveTextContent("none");
    expect(published).not.toHaveBeenCalled();
    await act(async () => { newBytes.resolve(new Response(null, { status: 204 })); });
    expect(screen.getByRole("status")).toHaveTextContent("Photo uploaded");
    expect(screen.getByTestId("evidence")).toHaveTextContent("92");
    expect(published).toHaveBeenCalledTimes(1);
    expect(published).toHaveBeenCalledWith(92);
  });

  it.each(["presign", "raw upload"] as const)("unmount during %s cannot publish or call the parent setter", async (phase) => {
    const heldPresign = deferred<unknown>();
    const heldBytes = deferred<Response>();
    tenantPublicRequest.mockReturnValue(phase === "presign" ? heldPresign.promise : Promise.resolve(presign()));
    storage.mockReturnValue(heldBytes.promise);
    const view = mountEvidence(); select();
    await waitFor(() => expect(tenantPublicRequest).toHaveBeenCalledTimes(1));
    if (phase === "raw upload") await waitFor(() => expect(storage).toHaveBeenCalledTimes(1));
    published.mockClear(); view.unmount();
    await act(async () => {
      heldPresign.resolve(presign()); heldBytes.resolve(new Response(null, { status: 204 }));
    });
    expect(published).not.toHaveBeenCalled();
    expect(storage).toHaveBeenCalledTimes(phase === "presign" ? 0 : 1);
  });

  it.each(["success", "rejection"] as const)("B's completed evidence survives a later A raw upload %s", async (outcome) => {
    const oldBytes = deferred<Response>();
    tenantPublicRequest.mockResolvedValueOnce(presign(91)).mockResolvedValueOnce(presign(92));
    storage.mockReturnValueOnce(oldBytes.promise).mockResolvedValueOnce(new Response(null, { status: 204 }));
    const view = mountEvidence(); select();
    await waitFor(() => expect(storage).toHaveBeenCalledTimes(1));
    view.rerender(<EvidenceHost {...initial} slug="b" />); select();
    expect(await screen.findByText("Photo uploaded")).toBeInTheDocument();
    expect(screen.getByTestId("evidence")).toHaveTextContent("92");
    published.mockClear();
    await act(async () => {
      if (outcome === "success") oldBytes.resolve(new Response(null, { status: 204 }));
      else oldBytes.reject(new Error("Late obsolete failure"));
    });
    expect(published).not.toHaveBeenCalled();
    expect(screen.getByTestId("evidence")).toHaveTextContent("92");
    expect(screen.getByRole("status")).toHaveTextContent("Photo uploaded");
    expect(screen.queryByText("Late obsolete failure")).not.toBeInTheDocument();
  });

  it("deduplicates same-tick file events and preserves uploaded evidence across callback-identity rerenders", async () => {
    const held = deferred<unknown>();
    tenantPublicRequest.mockReturnValue(held.promise);
    mountEvidence();
    act(() => { select(); select(); });
    expect(tenantPublicRequest).toHaveBeenCalledTimes(1);
    expect(JSON.parse(tenantPublicRequest.mock.calls[0][2].body)).toEqual({
      evidence_type: "issue", content_type: "image/jpeg", size_bytes: photo().size,
      name: rosterMatch.name, checkin_mid: rosterMatch.mid,
    });
    await act(async () => { held.resolve(presign()); });
    expect(await screen.findByText("Photo uploaded")).toBeInTheDocument();
    const body = storage.mock.calls[0][1]?.body;
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("key")).toBe("staged/91");
    expect((body as FormData).get("file")).toBeInstanceOf(File);
    published.mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Rerender callback" }));
    expect(screen.getByTestId("evidence")).toHaveTextContent("91");
    expect(screen.getByRole("status")).toHaveTextContent("Photo uploaded");
    expect(published).not.toHaveBeenCalled();
    expect(storage).toHaveBeenCalledTimes(1);
  });
});

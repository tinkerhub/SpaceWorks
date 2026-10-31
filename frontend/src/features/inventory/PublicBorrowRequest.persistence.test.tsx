import { useState } from "react";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes, useParams } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAccessToken, setAccessToken } from "../../lib/apiSession";
import { accessToken, deferred, json, requestHistoryNetwork } from "../../test/requestHistoryHarness";
import { fillContact, selection } from "../../test/publicLendingHarness";
import { revealRequestCapabilities } from "../requests/requestCapabilities";
import { PublicBorrowRequest } from "./PublicBorrowRequest";
import { PublicRequestPanel } from "./PublicRequestPanel";

let net: ReturnType<typeof requestHistoryNetwork>;
beforeEach(() => { net = requestHistoryNetwork(); });
afterEach(() => { net.dispose(); vi.restoreAllMocks(); });
const submit = () => fireEvent.click(screen.getByRole("button", { name: "Submit request" }));
function Panel() {
  const { slug = "a" } = useParams();
  return <PublicRequestPanel makerspaceSlug={slug} requestAccess="anyone" items={selection}
    onClear={() => {}} requestStatusHref={`/m/${slug}/request`} />;
}
function mountPanel() {
  return net.mount(<Routes><Route path="/m/:slug" element={<Panel />} /></Routes>, "/m/a");
}
function borrowHTTP() {
  const create = vi.fn(async (_url: URL, _init?: RequestInit): Promise<Response> => json({ public_token: "created", status: "pending_approval" }));
  net.other.mockImplementation((url, init) => create(url, init));
  return create;
}

describe("hardware saves only admitted server receipts", () => {
  it("persists two actual submissions before parent clear/completion unmounts the form", async () => {
    const create = borrowHTTP();
    const completions: unknown[][] = [];
    function UnmountingOwner() {
      const [visit, setVisit] = useState(0), [visible, setVisible] = useState(true);
      return <><button onClick={() => { setVisit((v) => v + 1); setVisible(true); }}>Next person</button>
        {visible ? <PublicBorrowRequest key={visit} slug="a" items={selection} identity="contact" accountLess checkedIn={false} ready
          onNewDraft={() => {}} onClear={() => {
            expect(revealRequestCapabilities("a").records.map((row) => row.token)).toContain(`hardware-${visit + 1}`);
            setVisible(false);
          }} onComplete={(...args) => { completions.push(args); }} /> : null}</>;
    }
    create.mockResolvedValueOnce(json({ public_token: "hardware-1", status: "pending_approval" }))
      .mockResolvedValueOnce(json({ public_token: "hardware-2", status: "pending_approval" }));
    net.mount(<UnmountingOwner />);
    fillContact(); submit();
    await waitFor(() => expect(completions).toHaveLength(1));
    expect(screen.queryByLabelText("Request purpose")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next person" })); fillContact(); submit();
    await waitFor(() => expect(completions).toHaveLength(2));
    for (let i = 0; i < 2; i++) expect(completions[i]).toEqual([
      { public_token: `hardware-${i + 1}`, status: "pending_approval" }, true,
      { saved: true, records: expect.arrayContaining([{ kind: "hardware", token: `hardware-${i + 1}`, saved_at: expect.any(Number) }]) },
    ]);
    expect(revealRequestCapabilities("a").records.map((row) => row.token).sort()).toEqual(["hardware-1", "hardware-2"]);
    expect(create).toHaveBeenCalledTimes(2);
  });

  it.each([false, true])("keeps a private receipt/link and truthful warning after storage failure (account=%s)", async (account) => {
    const create = borrowHTTP();
    if (account) setAccessToken(accessToken("hardware-account"));
    const set = Storage.prototype.setItem;
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(function (this: Storage, key, value) {
      if (key.startsWith("spaceworks.requests.")) throw new Error("Quota");
      set.call(this, key, value);
    });
    mountPanel();
    if (!account) { await screen.findByLabelText("Your name"); fillContact(); }
    else fireEvent.change(screen.getByLabelText("Request purpose"), { target: { value: "Account request" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Submit request" })).toBeEnabled()); submit();
    expect(await screen.findByText("created")).toBeVisible();
    expect(screen.getByRole("link", { name: "Check its status" })).toHaveAttribute("href", "/m/a/request?token=created");
    expect(screen.getByText(/could not verify the saved links/)).toBeVisible();
    expect(screen.queryByText(/Saved on this browser\. Open/)).not.toBeInTheDocument();
    expect(screen.queryByText("Your request was not submitted")).not.toBeInTheDocument();
    if (account) expect(screen.getByText(/It is filed under your account/)).toBeVisible();
    expect(create).toHaveBeenCalledOnce();
  });

  it("does not invent a private reference or registry entry for a tokenless honeypot response", async () => {
    const create = borrowHTTP(); create.mockResolvedValueOnce(json({ status: "pending_approval" }));
    mountPanel(); await screen.findByLabelText("Your name"); fillContact(); submit();
    await screen.findByText("Start another request");
    expect(screen.queryByRole("link", { name: "Check its status" })).not.toBeInTheDocument();
    expect(localStorage.getItem("spaceworks.requests.a")).toBeNull();
    expect(create).toHaveBeenCalledOnce();
  });

  it.each(["actor", "maker", "unmount"] as const)("does not save a held server receipt after %s departure", async (departure) => {
    const create = borrowHTTP(), held = deferred<Response>(); create.mockReturnValueOnce(held.promise);
    const view = mountPanel(); await screen.findByLabelText("Your name"); fillContact(); submit();
    await waitFor(() => expect(create).toHaveBeenCalledOnce());
    if (departure === "actor") act(() => setAccessToken(accessToken("other", { user_id: 2 })));
    else if (departure === "maker") view.navigate("/m/b");
    else view.unmount();
    await act(async () => held.resolve(json({ public_token: "obsolete-secret", status: "pending_approval" })));
    await waitFor(() => expect(view.client.getMutationCache().getAll()[0].state.status).not.toBe("pending"));
    expect(localStorage.getItem("spaceworks.requests.a")).toBeNull();
    expect(screen.queryByText("obsolete-secret")).not.toBeInTheDocument();
  });

  it("does not save a rejected create response", async () => {
    const create = borrowHTTP(); create.mockResolvedValueOnce(json({ detail: "Create refused" }, 400));
    clearAccessToken(); mountPanel(); await screen.findByLabelText("Your name"); fillContact(); submit();
    expect(await screen.findByText("Create refused")).toBeVisible();
    expect(localStorage.getItem("spaceworks.requests.a")).toBeNull();
  });
});

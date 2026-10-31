import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAccessToken, getAccessToken, getSessionGeneration, logout, refreshAccessToken, setAccessToken } from "../../lib/apiSession";
import { accessToken, deferred, hardware, json, page, requestHistoryNetwork } from "../../test/requestHistoryHarness";
import { MyRequestsPage } from "./MyRequestsPage";
import { saveRequestCapability } from "./requestCapabilities";

let net: ReturnType<typeof requestHistoryNetwork>;
beforeEach(() => {
  net = requestHistoryNetwork({ accounts: true, modules: ["request_workflow"] });
  setAccessToken(accessToken("account-A"));
});
afterEach(() => { net.dispose(); vi.restoreAllMocks(); });
const mount = () => net.mount(<Routes><Route path="/m/:slug/my-requests" element={<MyRequestsPage />} /></Routes>);

describe("private DOM observes real session mutations without a test rerender", () => {
  it("immediately hides account results and resets browser reveal on clear and a distinct login", async () => {
    saveRequestCapability("a", "hardware", "browser-secret");
    mount(); await screen.findByText("Tool hardware-1");
    fireEvent.click(screen.getByRole("button", { name: "Show requests saved on this browser" }));
    await screen.findByText("Tool browser-secret");
    act(() => clearAccessToken());
    expect(screen.queryByText("Tool hardware-1")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool browser-secret")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open private status link" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show requests saved on this browser" })).toBeVisible();
    net.mine.mockImplementation(async () => json(page([hardware("account-B-only")])));
    act(() => setAccessToken(accessToken("account-B", { user_id: 2 })));
    expect(screen.queryByText("Tool hardware-1")).not.toBeInTheDocument();
    expect(await screen.findByText("Tool account-B-only")).toBeVisible();
    expect(screen.queryByText("Tool browser-secret")).not.toBeInTheDocument();
    expect(new Headers(net.mine.mock.calls[net.mine.mock.calls.length - 1]?.[1]?.headers).get("Authorization"))
      .toBe(`Bearer ${accessToken("account-B", { user_id: 2 })}`);
    fireEvent.click(screen.getByRole("button", { name: "Show requests saved on this browser" }));
    await screen.findByText("Tool browser-secret");
    net.mine.mockImplementation(async () => json(page([hardware("fresh-A")])));
    act(() => setAccessToken(accessToken("account-A-return")));
    expect(screen.queryByText("Tool account-B-only")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool browser-secret")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool hardware-1")).not.toBeInTheDocument();
    expect(await screen.findByText("Tool fresh-A")).toBeVisible();
    expect(screen.getByRole("button", { name: "Show requests saved on this browser" })).toBeVisible();
  });

  it("publishes logout before its held HTTP response and an old logout cannot clear a newer login", async () => {
    mount(); await screen.findByText("Tool hardware-1");
    const held = deferred<Response>(); net.signout.mockReturnValueOnce(held.promise);
    let signingOut!: Promise<void>;
    act(() => { signingOut = logout(); });
    expect(net.signout).toHaveBeenCalledOnce();
    expect(screen.queryByText("Tool hardware-1")).not.toBeInTheDocument();
    expect(getAccessToken()).toBe("");
    net.mine.mockResolvedValue(json(page([hardware("new-login")])));
    act(() => setAccessToken(accessToken("new-account", { user_id: 2 })));
    await screen.findByText("Tool new-login");
    await act(async () => { held.resolve(json({})); await signingOut; });
    expect(getAccessToken()).toBe(accessToken("new-account", { user_id: 2 }));
    expect(screen.getByText("Tool new-login")).toBeVisible();
    expect(screen.queryByText("Tool hardware-1")).not.toBeInTheDocument();
  });

  it.each(["success", "error"] as const)("rejects an old held JSON %s after clear and new login", async (outcome) => {
    const decoded = deferred<unknown>(), entered = deferred<void>();
    const response = json({}, outcome === "success" ? 200 : 503);
    vi.spyOn(response, "json").mockImplementation(() => { entered.resolve(); return decoded.promise; });
    net.mine.mockResolvedValueOnce(response);
    const view = mount();
    await entered.promise;
    act(() => clearAccessToken());
    net.mine.mockResolvedValue(json(page([hardware("current-B")])));
    act(() => setAccessToken(accessToken("B", { user_id: 2 })));
    await screen.findByText("Tool current-B");
    await act(async () => decoded.resolve(outcome === "success" ? page([hardware("old-A-secret")]) : { detail: "Old A private failure" }));
    await waitFor(() => expect(view.client.getQueryCache().findAll({ queryKey: ["my-requests", "a"] })
      .every((query) => query.state.fetchStatus === "idle")).toBe(true));
    expect(screen.getByText("Tool current-B")).toBeVisible();
    expect(screen.queryByText("Tool old-A-secret")).not.toBeInTheDocument();
    expect(screen.queryByText("Old A private failure")).not.toBeInTheDocument();
    expect(screen.queryByText("Hardware requests didn't load")).not.toBeInTheDocument();
  });

  it("does not publish held A decoding after maker A→B→A and uses a new request owner on return", async () => {
    const decoded = deferred<unknown>(), entered = deferred<void>();
    const response = json({});
    vi.spyOn(response, "json").mockImplementation(() => { entered.resolve(); return decoded.promise; });
    net.mine.mockResolvedValueOnce(response).mockImplementation(async (url) => json(page([hardware(`current-${url.pathname.includes("/b/") ? "B" : "A"}`)])));
    const view = mount(); await entered.promise;
    view.navigate("/m/b/my-requests"); await screen.findByText("Tool current-B");
    view.navigate("/m/a/my-requests"); await screen.findByText("Tool current-A");
    await act(async () => decoded.resolve(page([hardware("obsolete-A")])));
    expect(screen.getByText("Tool current-A")).toBeVisible();
    expect(screen.queryByText("Tool obsolete-A")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool current-B")).not.toBeInTheDocument();
  });

  it("retains legitimate account results and explicit browser consent during an accepted same-generation refresh", async () => {
    saveRequestCapability("a", "hardware", "valid-context");
    mount(); await screen.findByText("Tool hardware-1");
    fireEvent.click(screen.getByRole("button", { name: "Show requests saved on this browser" }));
    await screen.findByText("Tool valid-context");
    const generation = getSessionGeneration();
    net.refresh.mockResolvedValueOnce(json({ access: accessToken("refreshed-A") }));
    await act(async () => { expect(await refreshAccessToken()).toBe(true); });
    expect(getSessionGeneration()).toBe(generation);
    expect(screen.getByText("Tool hardware-1")).toBeVisible();
    expect(screen.getByText("Tool valid-context")).toBeVisible();
    expect(screen.getByRole("button", { name: "Hide saved requests" })).toBeVisible();
    expect(net.mine).toHaveBeenCalledOnce(); expect(net.status).toHaveBeenCalledOnce();
  });
});

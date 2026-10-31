import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AppRoutes } from "../../AppRoutes";
import { setAccessToken } from "../../lib/apiSession";
import { accessToken, deferred, json, requestHistoryNetwork } from "../../test/requestHistoryHarness";

let net: ReturnType<typeof requestHistoryNetwork>;
afterEach(() => net.dispose());
const routes = (mode: "single" | "central" = "central") => <AppRoutes mode={mode} landing={<p>Directory</p>} />;

describe("public My requests routes and bootstrap gates", () => {
  it.each(["central", "single"] as const)("opens the real %s route and header with accounts off", async (mode) => {
    net = requestHistoryNetwork();
    if (mode === "single") window.__TENANT__ = { tenantToken: "tenant-a" };
    const path = mode === "single" ? "/my-requests" : "/m/a/my-requests";
    net.mount(routes(mode), path);
    expect(await screen.findByRole("heading", { name: "My requests" })).toBeVisible();
    expect(screen.getAllByRole("link", { name: "My requests" }).every((link) => link.getAttribute("href") === path)).toBe(true);
    expect(screen.getByText(/On a shared browser/)).toBeVisible();
    expect(screen.queryByRole("link", { name: /member area|sign in/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /password|username|code/i })).not.toBeInTheDocument();
    expect(net.mine).not.toHaveBeenCalled();
    expect(net.status).not.toHaveBeenCalled();
    expect(net.refresh).not.toHaveBeenCalled();
    expect(net.other).not.toHaveBeenCalled();
  });

  it("waits for a real bootstrap before exposing browser links or issuing status/history requests", async () => {
    net = requestHistoryNetwork();
    const held = deferred<Response>();
    net.bootstrap.mockReturnValueOnce(held.promise);
    net.mount(routes(), "/m/a/my-requests", net.client(false));
    expect(screen.getByText("Loading requests")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Show requests saved on this browser" })).not.toBeInTheDocument();
    expect(net.mine).not.toHaveBeenCalled(); expect(net.status).not.toHaveBeenCalled();
    await act(async () => held.resolve(json(net.bootstraps.get("a"))));
    expect(await screen.findByRole("button", { name: "Show requests saved on this browser" })).toBeVisible();
  });

  it("allows an existing real account to load its own requests with accounts off, without sign-in or refresh", async () => {
    net = requestHistoryNetwork();
    const token = accessToken("other-surface-account");
    setAccessToken(token);
    net.mount(routes());
    expect(await screen.findByText("Tool hardware-1")).toBeVisible();
    expect(await screen.findByText("Project machine-1")).toBeVisible();
    expect(screen.getByRole("region", { name: "Account requests" })).toBeVisible();
    expect(net.mine).toHaveBeenCalledTimes(2);
    for (const [, init] of net.mine.mock.calls) expect(new Headers(init?.headers).get("Authorization")).toBe(`Bearer ${token}`);
    expect(screen.queryByRole("link", { name: /member area|sign in/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /password|username|code/i })).not.toBeInTheDocument();
    expect(net.refresh).not.toHaveBeenCalled(); expect(net.other).not.toHaveBeenCalled();
  });

  it("lets the own-history API deny an existing accounts-off token without inventing a sign-in form", async () => {
    net = requestHistoryNetwork();
    net.mine.mockImplementation(async () => json({ detail: "Principal cannot access history." }, 403));
    setAccessToken(accessToken("other-surface-account"));
    net.mount(routes());
    await waitFor(() => expect(screen.getAllByText("This account cannot access this request history.")).toHaveLength(2));
    expect(screen.queryByText("Tool hardware-1")).not.toBeInTheDocument();
    expect(screen.queryByText("Project machine-1")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show requests saved on this browser" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /member area|sign in/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /password|username|code/i })).not.toBeInTheDocument();
    expect(net.mine).toHaveBeenCalledTimes(2);
    expect(net.refresh).not.toHaveBeenCalled(); expect(net.status).not.toHaveBeenCalled();
    expect(net.other).not.toHaveBeenCalled();
  });

  it("shows bootstrap failure and recovers without an off-endpoint request", async () => {
    net = requestHistoryNetwork();
    net.bootstrap.mockResolvedValueOnce(json({ detail: "Unavailable" }, 503));
    net.mount(routes(), "/m/a/my-requests", net.client(false));
    expect(await screen.findByText("Requests didn't load")).toBeVisible();
    expect(net.mine).not.toHaveBeenCalled(); expect(net.status).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: "Show requests saved on this browser" })).toBeVisible();
    expect(net.bootstrap).toHaveBeenCalledTimes(2);
  });

  it("returns 404 with neither module enabled and retains the existing accounts-off MemberArea 404", async () => {
    net = requestHistoryNetwork({ modules: [] });
    const view = net.mount(routes());
    expect(await screen.findByRole("heading", { name: /not found/i })).toBeVisible();
    expect(screen.queryByRole("link", { name: "My requests" })).not.toBeInTheDocument();
    view.navigate("/m/a/member");
    expect(await screen.findByRole("heading", { name: /not found/i })).toBeVisible();
    expect(net.mine).not.toHaveBeenCalled(); expect(net.status).not.toHaveBeenCalled();
    expect(net.refresh).not.toHaveBeenCalled(); expect(net.other).not.toHaveBeenCalled();
  });

  it.each(["request_workflow", "machine_service"])("advertises My requests with only %s enabled and keeps the other legacy route off", async (module) => {
    net = requestHistoryNetwork({ modules: [module] });
    const view = net.mount(routes());
    expect(await screen.findByRole("heading", { name: "My requests" })).toBeVisible();
    expect(screen.getByRole("link", { name: "My requests" })).toHaveAttribute("href", "/m/a/my-requests");
    view.navigate(module === "request_workflow" ? "/m/a/machine-service?token=old" : "/m/a/request?token=old");
    expect(await screen.findByRole("heading", { name: /not found/i })).toBeVisible();
    expect(net.mine).not.toHaveBeenCalled(); expect(net.status).not.toHaveBeenCalled();
    expect(net.other).not.toHaveBeenCalled();
  });
});

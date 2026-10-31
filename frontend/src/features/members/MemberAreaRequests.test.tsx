import { fireEvent, screen, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { setAccessToken } from "../../lib/apiSession";
import { accessToken, json, requestHistoryNetwork } from "../../test/requestHistoryHarness";
import { saveRequestCapability } from "../requests/requestCapabilities";
import { MemberArea } from "./MemberArea";

let net: ReturnType<typeof requestHistoryNetwork>;
beforeEach(() => {
  net = requestHistoryNetwork({ accounts: true });
  setAccessToken(accessToken("member-without-membership"));
  net.refresh.mockImplementation(async () => json({ access: accessToken("refreshed-member") }));
  net.other.mockImplementation(async (url) => {
    if (url.pathname.endsWith("/config")) return json({ member_accounts: { enabled: true } });
    if (url.pathname.endsWith("/memberships/me")) return json({ memberships: [], requests: [] });
    if (url.pathname.endsWith("/auth/me")) return json({ username: "ada-account", email_verified: true, must_change_password: false });
    if (url.pathname.endsWith("/memberships/invitations")) return json({ invitations: [] });
    if (url.pathname.endsWith("/member/archived-payments")) return json([]);
    throw new Error(`Unexpected member HTTP: ${url}`);
  });
});
afterEach(() => net.dispose());

describe("actual MemberArea Requests tab without membership", () => {
  it("discovers an authenticated account, mounts history only on selection, and destroys private reveal when leaving", async () => {
    saveRequestCapability("a", "hardware", "browser-only");
    net.mount(<Routes><Route path="/m/:slug/member" element={<MemberArea />} /></Routes>, "/m/a/member");
    const tab = await screen.findByRole("tab", { name: "Requests" });
    expect(tab).toBeVisible();
    expect(screen.getByText("Signed in as ada-account")).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Profile" })).not.toBeInTheDocument();
    expect(screen.queryByText("Active member")).not.toBeInTheDocument();
    expect(net.mine).not.toHaveBeenCalled(); expect(net.status).not.toHaveBeenCalled();
    expect(net.other.mock.calls.some(([url]) => url.pathname.endsWith("/memberships/me"))).toBe(true);
    expect(net.other.mock.calls.some(([url]) => url.pathname.endsWith("/auth/me"))).toBe(true);
    fireEvent.mouseDown(tab, { button: 0, ctrlKey: false }); fireEvent.click(tab);
    await screen.findByText("Tool hardware-1"); await screen.findByText("Project machine-1");
    expect(net.mine).toHaveBeenCalledTimes(2);
    expect(screen.getAllByRole("link", { name: "Open private status link" }).map((link) => link.getAttribute("href")))
      .toEqual(expect.arrayContaining(["/m/a/request?token=hardware-1", "/m/a/machine-service?token=machine-1"]));
    fireEvent.click(screen.getByRole("button", { name: "Show requests saved on this browser" }));
    await screen.findByText("Tool browser-only");
    const overview = screen.getByRole("tab", { name: "Overview" });
    fireEvent.mouseDown(overview, { button: 0, ctrlKey: false }); fireEvent.click(overview);
    expect(screen.queryByText("Tool hardware-1")).not.toBeInTheDocument();
    expect(screen.queryByText("Tool browser-only")).not.toBeInTheDocument();
    fireEvent.mouseDown(tab, { button: 0, ctrlKey: false }); fireEvent.click(tab);
    await screen.findByText("Tool hardware-1");
    expect(screen.queryByText("Tool browser-only")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Show requests saved on this browser" })).toBeVisible();
    await waitFor(() => expect(net.status).toHaveBeenCalledOnce());
    expect(net.other.mock.calls.every(([url]) => !/\/waiver|\/presence|\/activity|\/profile|two-factor/.test(url.pathname))).toBe(true);
  });
});

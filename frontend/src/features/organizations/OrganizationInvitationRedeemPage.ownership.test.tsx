import { accessToken } from "../../test/accessTokens";
import { flushSync } from "react-dom";
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { refreshAccessToken, fetchMe, staffRequest } = vi.hoisted(() => ({
  refreshAccessToken: vi.fn(), fetchMe: vi.fn(), staffRequest: vi.fn(),
}));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), refreshAccessToken, fetchMe, staffRequest,
}));
import { getAccessToken, setAccessToken } from "../../lib/apiSession";
import { changeEpoch, epochChanges, held } from "../../test/authOwnership";
import { invitationLogin, invitationMember, invitationRedeemed, mountInvitation, signIntoInvitation } from "../../test/organizationOwnershipHarness";

const redeemCalls = () => staffRequest.mock.calls.filter(([path]) => path.includes("/redeem/"));
const loginCalls = () => staffRequest.mock.calls.filter(([path]) => path === "/auth/login");
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setAccessToken(accessToken("account-A"));
  refreshAccessToken.mockReset().mockResolvedValue(false);
  fetchMe.mockReset().mockResolvedValue(invitationMember);
  staffRequest.mockReset().mockImplementation((path: string) => Promise.resolve(
    path === "/auth/login" ? invitationLogin : invitationRedeemed,
  ));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function preserved(view: ReturnType<typeof mountInvitation>, token: string) {
  expect(getAccessToken()).toBe(token);
  expect(view.clear).not.toHaveBeenCalled();
  expect(view.client.getQueryData(["private"])).toEqual({ owner: "B" });
  expect(screen.queryByRole("heading", { name: "Staff destination" })).not.toBeInTheDocument();
  expect(screen.queryByText("obsolete error")).not.toBeInTheDocument();
}

describe("invitation local publication ownership", () => {
  it.each(epochChanges)("OI01 restore checks %s before dispatching fetchMe", async (kind) => {
    const restore = held<boolean>();
    refreshAccessToken.mockReturnValue(restore.promise);
    const view = mountInvitation();
    expect(refreshAccessToken).toHaveBeenCalledTimes(1);
    await act(async () => { restore.resolve(true); await changeEpoch(kind); });
    expect(fetchMe).not.toHaveBeenCalled();
    expect(staffRequest).not.toHaveBeenCalled();
    expect(view.clear).not.toHaveBeenCalled();
  });

  it("OI02 unmount before restore completion prevents the profile follow-up", async () => {
    const restore = held<boolean>();
    refreshAccessToken.mockReturnValue(restore.promise);
    const view = mountInvitation();
    view.unmount();
    await act(async () => { restore.resolve(true); });
    expect(fetchMe).not.toHaveBeenCalled();
    expect(staffRequest).not.toHaveBeenCalled();
  });

  it("OI03 profile result from an older account cannot auto-redeem", async () => {
    const profile = held<typeof invitationMember>();
    refreshAccessToken.mockResolvedValue(true);
    fetchMe.mockReturnValue(profile.promise);
    const view = mountInvitation();
    await waitFor(() => expect(fetchMe).toHaveBeenCalledTimes(1));
    await act(async () => { profile.resolve(invitationMember); setAccessToken(accessToken("account-B", { user_id: 2 })); });
    expect(staffRequest).not.toHaveBeenCalled();
    expect(view.clear).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(accessToken("account-B", { user_id: 2 }));
  });

  it.each(["new login", "same-token login", "token visit", "unmount"])("OI04 parsed member login cannot publish after %s", async (cancel) => {
    const response = held<typeof invitationLogin>();
    staffRequest.mockReturnValue(response.promise);
    const view = mountInvitation();
    await signIntoInvitation();
    await waitFor(() => expect(loginCalls()).toHaveLength(1));
    view.client.setQueryData(["private"], { owner: "B" });
    await act(async () => {
      if (cancel === "token visit") {
        flushSync(() => { view.visit("B"); });
        expect(screen.getByLabelText("Committed invitation route")).toHaveTextContent("/invitations/B");
        flushSync(() => { view.visit("A"); });
        expect(screen.getByLabelText("Committed invitation route")).toHaveTextContent("/invitations/A");
      }
      response.resolve(invitationLogin);
      if (cancel === "unmount") view.unmount();
      else if (cancel !== "token visit") setAccessToken(cancel === "same-token login" ? accessToken("account-A") : accessToken("account-B", { user_id: 2 }));
    });
    preserved(view, cancel === "new login" ? accessToken("account-B", { user_id: 2 }) : accessToken("account-A"));
    expect(redeemCalls()).toHaveLength(0);
    expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
  });

  it.each(["new account", "token visit", "unmount"])("OI05 parsed staff login cannot clear B's cache or navigate after %s", async (cancel) => {
    const response = held<typeof invitationLogin>();
    staffRequest.mockImplementation((path: string, init: RequestInit) => {
      if (path !== "/auth/login") return Promise.resolve(invitationRedeemed);
      return JSON.parse(String(init.body)).surface === "staff" ? response.promise : Promise.resolve(invitationLogin);
    });
    const view = mountInvitation();
    await signIntoInvitation();
    await screen.findByRole("heading", { name: "Staff sign-in" });
    expect(screen.getByLabelText("Password")).toHaveValue("");
    await signIntoInvitation(true);
    await waitFor(() => expect(loginCalls()).toHaveLength(2));
    view.client.setQueryData(["private"], { owner: "B" });
    await act(async () => {
      if (cancel === "token visit") {
        flushSync(() => { view.visit("B"); });
        expect(screen.getByLabelText("Committed invitation route")).toHaveTextContent("/invitations/B");
      }
      response.resolve({ ...invitationLogin, access: accessToken("obsolete-staff", { surface: "staff", staff_scope: "platform" }) });
      if (cancel === "unmount") view.unmount();
      else if (cancel !== "token visit") setAccessToken(accessToken("account-B", { user_id: 2 }));
    });
    preserved(view, cancel === "new account" ? accessToken("account-B", { user_id: 2 }) : accessToken("member-A"));
    expect(redeemCalls()).toHaveLength(1);
  });

  it("OI06 token A→B→A ignores old redemption and lets a fresh member redeem once", async () => {
    const old = held<typeof invitationRedeemed>();
    let redemptions = 0;
    staffRequest.mockImplementation((path: string) => {
      if (path === "/auth/login") return Promise.resolve(invitationLogin);
      redemptions += 1;
      return redemptions === 1 ? old.promise : Promise.resolve(invitationRedeemed);
    });
    const view = mountInvitation();
    await signIntoInvitation();
    await waitFor(() => expect(redeemCalls()).toHaveLength(1));
    view.visit("B");
    expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
    await act(async () => { old.resolve(invitationRedeemed); });
    expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
    view.visit("A");
    await signIntoInvitation();
    await screen.findByRole("heading", { name: "Staff sign-in" });
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(redeemCalls()).toHaveLength(2);
    expect(redeemCalls().map(([, init]) => JSON.parse(init.body).token)).toEqual(["A", "A"]);
    expect(loginCalls()).toHaveLength(2);
    expect(view.clear).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Staff destination" })).not.toBeInTheDocument();
  });

  it("OI07 successful A status is hidden immediately for B and does not return on a new A visit", async () => {
    const view = mountInvitation();
    await signIntoInvitation();
    await screen.findByRole("heading", { name: "Staff sign-in" });
    view.visit("B");
    expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Staff sign-in" })).not.toBeInTheDocument();
    view.visit("A");
    expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
    expect(await screen.findByLabelText("Password")).toHaveValue("");
    expect(redeemCalls()).toHaveLength(1);
  });

  it.each(["success", "error"])("OI09 parsed redemption %s after a new account cannot publish or touch B's cache", async (outcome) => {
    const response = held<typeof invitationRedeemed>();
    staffRequest.mockImplementation((path: string) => path === "/auth/login" ? Promise.resolve(invitationLogin) : response.promise);
    const view = mountInvitation();
    await signIntoInvitation();
    await waitFor(() => expect(redeemCalls()).toHaveLength(1));
    view.client.setQueryData(["private"], { owner: "B" });
    await act(async () => {
      if (outcome === "success") response.resolve(invitationRedeemed);
      else response.reject(new Error("obsolete error"));
      setAccessToken(accessToken("account-B", { user_id: 2 }));
    });
    preserved(view, accessToken("account-B", { user_id: 2 }));
    expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
    expect(screen.queryByText("Invitation unavailable")).not.toBeInTheDocument();
    expect(redeemCalls()).toHaveLength(1);
  });

  it("OI08 old redemption finally cannot unlock a newer visit's pending login", async () => {
    const old = held<typeof invitationRedeemed>();
    const current = held<typeof invitationLogin>();
    staffRequest.mockImplementation((path: string) => path === "/auth/login" ? Promise.resolve(invitationLogin) : old.promise);
    const view = mountInvitation();
    await signIntoInvitation();
    await waitFor(() => expect(redeemCalls()).toHaveLength(1));
    view.visit("B");
    staffRequest.mockReturnValue(current.promise);
    await signIntoInvitation();
    await waitFor(() => expect(loginCalls()).toHaveLength(2));
    await act(async () => { old.reject(new Error("obsolete error")); });
    expect(screen.getByLabelText("Password")).toBeDisabled();
    expect(screen.queryByText("obsolete error")).not.toBeInTheDocument();
    expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
    // Leave B pending: the test's assertion is that A's finally did not release it.
  });

  it("OI10 StrictMode replay starts a fresh owned restore and completes one redemption", async () => {
    const oldRestore = held<boolean>();
    const freshRestore = held<boolean>();
    const profile = held<typeof invitationMember>();
    const redemption = held<typeof invitationRedeemed>();
    refreshAccessToken.mockReturnValueOnce(oldRestore.promise).mockReturnValueOnce(freshRestore.promise);
    fetchMe.mockReturnValue(profile.promise);
    staffRequest.mockReturnValue(redemption.promise);
    const view = mountInvitation({ strict: true });
    expect(refreshAccessToken).toHaveBeenCalledTimes(2);

    await act(async () => { oldRestore.resolve(true); });
    expect(fetchMe).not.toHaveBeenCalled();
    expect(staffRequest).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    await act(async () => { freshRestore.resolve(true); });
    await waitFor(() => expect(fetchMe).toHaveBeenCalledTimes(1));
    await act(async () => { profile.resolve(invitationMember); });
    await waitFor(() => expect(redeemCalls()).toHaveLength(1));
    expect(JSON.parse(redeemCalls()[0][1].body).token).toBe("A");
    expect(screen.getByText("Redeeming invitation...")).toBeInTheDocument();
    await act(async () => { redemption.resolve(invitationRedeemed); });
    await screen.findByRole("heading", { name: "Staff sign-in" });
    expect(screen.getByLabelText("Username or email")).toHaveValue(invitationMember.username);
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toBeEnabled();
    expect(refreshAccessToken).toHaveBeenCalledTimes(2);
    expect(redeemCalls()).toHaveLength(1);
    expect(loginCalls()).toHaveLength(0);
    expect(getAccessToken()).toBe(accessToken("account-A"));
    expect(view.clear).not.toHaveBeenCalled();
    expect(view.client.getQueryData(["private"])).toEqual({ owner: "A" });
    expect(screen.queryByRole("heading", { name: "Staff destination" })).not.toBeInTheDocument();
  });
});

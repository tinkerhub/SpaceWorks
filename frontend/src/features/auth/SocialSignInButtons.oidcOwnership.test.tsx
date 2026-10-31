import { accessToken } from "../../test/accessTokens";
import { flushSync } from "react-dom";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { publicV1Request } = vi.hoisted(() => ({ publicV1Request: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), publicV1Request,
}));
import { setAccessToken } from "../../lib/apiSession";
import { held } from "../../test/authOwnership";
import { socialConfig, socialResult } from "../../test/socialOwnershipHarness";
import { SocialSignInButtons } from "./SocialSignInButtons";

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, "", "/member?next=local#kept");
  setAccessToken(accessToken("account-A"));
  publicV1Request.mockReset().mockImplementation((path: string) => Promise.resolve(path === "/config"
    ? { social_auth: { "oidc:campus": socialConfig["oidc:campus"] }, member_accounts: { enabled: false } } : socialResult));
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Unexpected network")));
});
afterEach(() => { vi.unstubAllGlobals(); });

function mount(surface: "member" | "staff" = "member") {
  const success = vi.fn();
  let props = { email: "a@example.test", makerspaceSlug: "A", disabled: false, ownershipScope: {} };
  const node = () => <SocialSignInButtons {...props} surface={surface} onSuccess={success} />;
  const view = render(node());
  return { ...view, success, change: (patch: Partial<typeof props>) => { props = { ...props, ...patch }; view.rerender(node()); } };
}
const callbackCalls = () => publicV1Request.mock.calls.filter(([path]) => path === "/auth/social/oidc/callback");
function callbackUrl() {
  sessionStorage.setItem("spaceworks.oidc.nonce.owned-state", "owned-nonce");
  window.history.replaceState({}, "", "/member?next=local&code=owned-code&state=owned-state&session_state=x&iss=idp#kept");
}

describe("actual OIDC intent ownership", () => {
  it.each(["epoch", "email", "slug", "mode", "disabled", "unmount"])("SO01 stale authorize after %s neither stores state nor assigns a URL", async (cancel) => {
    const response = held<{ authorization_url: string; state: string; nonce: string }>();
    publicV1Request.mockImplementation((path: string) => path === "/config" ? Promise.resolve({
      social_auth: { "oidc:campus": socialConfig["oidc:campus"] }, member_accounts: { enabled: false },
    }) : response.promise);
    const view = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Continue with Campus SSO" }));
    expect(publicV1Request).toHaveBeenCalledWith("/auth/social/oidc/campus/authorize", {
      method: "POST", body: JSON.stringify({ redirect_uri: `${window.location.origin}/member`, email: "a@example.test", makerspace_slug: "A" }),
    });
    if (cancel === "epoch") setAccessToken(accessToken("account-B", { user_id: 2 }));
    else if (cancel === "email") view.change({ email: "b@example.test" });
    else if (cancel === "slug") view.change({ makerspaceSlug: "B" });
    else if (cancel === "mode") view.change({ ownershipScope: {} });
    else if (cancel === "disabled") view.change({ disabled: true });
    else view.unmount();
    const localUrl = window.location.href;
    await act(async () => {
      // A local hash would visibly change if assign were reached. No Location mocking or external URL.
      response.resolve({ authorization_url: `${window.location.origin}/member?next=local#obsolete-authorize`, state: "old-state", nonce: "old-nonce" });
    });
    expect(window.location.href).toBe(localUrl);
    expect(sessionStorage.getItem("spaceworks.oidc.nonce.old-state")).toBeNull();
    expect(view.success).not.toHaveBeenCalled();
  });

  it("SO02 current member callback consumes its nonce, cleans the query and publishes once", async () => {
    callbackUrl();
    const view = mount();
    await waitFor(() => expect(view.success).toHaveBeenCalledExactlyOnceWith(socialResult));
    expect(callbackCalls()).toHaveLength(1);
    expect(callbackCalls()[0][1]).toEqual({ method: "POST", credentials: "include", body: JSON.stringify({ code: "owned-code", state: "owned-state", nonce: "owned-nonce" }) });
    expect(sessionStorage.getItem("spaceworks.oidc.nonce.owned-state")).toBeNull();
    expect(window.location.search).toBe("?next=local");
    expect(window.location.hash).toBe("#kept");
  });

  it.each(["new account", "unmount", "mode"])("SO03 parsed callback cannot publish after %s", async (cancel) => {
    const response = held<typeof socialResult>();
    publicV1Request.mockImplementation((path: string) => path === "/config" ? Promise.resolve({}) : response.promise);
    callbackUrl();
    const view = mount();
    await waitFor(() => expect(callbackCalls()).toHaveLength(1));
    await act(async () => {
      response.resolve(socialResult);
      if (cancel === "new account") setAccessToken(accessToken("account-B", { user_id: 2 }));
      else if (cancel === "unmount") view.unmount();
      else flushSync(() => { view.change({ ownershipScope: {} }); });
    });
    expect(view.success).not.toHaveBeenCalled();
    expect(callbackCalls()).toHaveLength(1);
  });

  it.each(["missing nonce", "cancelled provider", "missing state"])("SO04 invalid callback (%s) cleans query without exchanging", async (failure) => {
    callbackUrl();
    if (failure === "missing nonce") sessionStorage.clear();
    else if (failure === "cancelled provider") window.history.replaceState({}, "", "/member?error=access_denied&error_description=no&state=owned-state&next=local");
    else window.history.replaceState({}, "", "/member?code=owned-code&next=local");
    const view = mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(failure === "missing nonce" ? "expired" : "cancelled or refused");
    expect(callbackCalls()).toHaveLength(0);
    expect(window.location.search).toBe("?next=local");
    expect(view.success).not.toHaveBeenCalled();
  });

  it("SO05 institution OIDC remains member-only and available with consumer accounts off", async () => {
    mount();
    expect(await screen.findByRole("button", { name: "Continue with Campus SSO" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Continue with Apple" })).not.toBeInTheDocument();
    expect(callbackCalls()).toHaveLength(0);
  });

  it("SO06 staff surface neither consumes a member callback nor shows institution OIDC", async () => {
    const discovery = held<object>();
    publicV1Request.mockReturnValue(discovery.promise);
    callbackUrl();
    const view = mount("staff");
    await act(async () => { discovery.resolve({ social_auth: { "oidc:campus": socialConfig["oidc:campus"] } }); });
    expect(callbackCalls()).toHaveLength(0);
    expect(sessionStorage.getItem("spaceworks.oidc.nonce.owned-state")).toBe("owned-nonce");
    expect(view.container).toBeEmptyDOMElement();
    expect(view.success).not.toHaveBeenCalled();
  });
});

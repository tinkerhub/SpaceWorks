import { accessToken } from "../../test/accessTokens";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAccessToken, getAccessToken, logout, setAccessToken } from "../../lib/apiSession";
import { jsonResponse } from "../../lib/apiSessionTestHelpers";
import { fakeIdentitySdks, socialConfig, socialNetwork, socialResult } from "../../test/socialOwnershipHarness";
import { SocialSignInButtons } from "./SocialSignInButtons";

let sdk: ReturnType<typeof fakeIdentitySdks>;
let network: ReturnType<typeof socialNetwork>;
beforeEach(() => {
  window.history.replaceState({}, "", "/member");
  sessionStorage.clear();
  network = socialNetwork();
  sdk = fakeIdentitySdks();
});
afterEach(() => {
  vi.restoreAllMocks(); vi.unstubAllGlobals();
  delete window.google; delete window.AppleID;
});

function mount() {
  const success = vi.fn();
  type Props = Partial<Parameters<typeof SocialSignInButtons>[0]> & { key?: string };
  let props: Props = { makerspaceSlug: "A", email: "a@example.test", ownershipScope: {} };
  const node = () => {
    const { key, ...componentProps } = props;
    return <SocialSignInButtons key={key} surface="member" onSuccess={success} {...componentProps} />;
  };
  const view = render(node());
  return { ...view, success, change: (patch: Props) => { props = { ...props, ...patch }; view.rerender(node()); } };
}
const cancellations = ["logout", "new login", "same-token login", "clear", "slug", "mode", "unmount", "disabled", "replaced host"] as const;
async function cancel(view: ReturnType<typeof mount>, reason: typeof cancellations[number] | "email") {
  if (reason === "logout") await logout();
  else if (reason === "new login") setAccessToken(accessToken("account-B", { user_id: 2 }));
  else if (reason === "same-token login") setAccessToken(accessToken("account-A"));
  else if (reason === "clear") clearAccessToken();
  else if (reason === "unmount") view.unmount();
  else if (reason === "slug") view.change({ makerspaceSlug: "B" });
  else if (reason === "mode") view.change({ ownershipScope: {} });
  else if (reason === "disabled") view.change({ disabled: true });
  else if (reason === "email") view.change({ email: "b@example.test" });
  else view.change({ key: "replacement" });
}

describe("actual social components and SDK ownership", () => {
  it.each(cancellations)("SP01 Google callback after %s dispatches no credential exchange", async (reason) => {
    const view = mount();
    await waitFor(() => expect(sdk.callbacks).toHaveLength(1));
    const oldCredential = sdk.callbacks[0];
    await act(async () => { await cancel(view, reason); });
    await act(async () => { await oldCredential({ credential: "obsolete-google-credential" }); });
    expect(network.exchanges()).toHaveLength(0);
    expect(view.success).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(reason === "new login" ? accessToken("account-B", { user_id: 2 }) : ["logout", "clear"].includes(reason) ? "" : accessToken("account-A"));
  });

  it.each([...cancellations, "email"] as const)("SP02 Apple popup after %s dispatches no credential exchange", async (reason) => {
    const view = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Continue with Apple" }));
    await waitFor(() => expect(sdk.signIn).toHaveBeenCalledTimes(1));
    await act(async () => { await cancel(view, reason); });
    await act(async () => { sdk.popup.resolve({ authorization: { id_token: "obsolete-apple-credential" } }); });
    expect(network.exchanges()).toHaveLength(0);
    expect(view.success).not.toHaveBeenCalled();
    expect(screen.queryByText("Sign-in is no longer active. Please try again.")).not.toBeInTheDocument();
  });

  it("SP03 current Google retains client, nonce, surface and width and completes once", async () => {
    const view = mount();
    await waitFor(() => expect(sdk.callbacks).toHaveLength(1));
    expect(sdk.initialize).toHaveBeenCalledWith(expect.objectContaining({ client_id: "configured-google-client", nonce: "owned-nonce" }));
    expect(sdk.renderButton).toHaveBeenCalledWith(expect.any(HTMLElement), expect.objectContaining({ width: 320 }));
    expect(network.nonces()[0].body).toEqual({ provider: "google", surface: "member", delivery: "web", client_platform: "web" });
    await act(async () => { await sdk.callbacks[0]({ credential: "current-google-credential" }); });
    expect(view.success).toHaveBeenCalledExactlyOnceWith(socialResult);
    expect(network.exchanges()[0].body).toEqual({ id_token: "current-google-credential", nonce: "owned-nonce", surface: "member", delivery: "web", client_platform: "web" });
    expect(network.exchanges()[0].init.credentials).toBe("include");
  });

  it("SP04 current Apple retains service, nonce, surface and name and completes once", async () => {
    const view = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Continue with Apple" }));
    await waitFor(() => expect(sdk.signIn).toHaveBeenCalledTimes(1));
    expect(sdk.appleInit).toHaveBeenCalledWith({ clientId: "configured-apple-service", scope: "name email", redirectURI: window.location.origin, usePopup: true, nonce: "owned-nonce" });
    await act(async () => { sdk.popup.resolve({ authorization: { id_token: "current-apple" }, user: { name: { firstName: "Ada", lastName: "Lovelace" } } }); });
    await waitFor(() => expect(view.success).toHaveBeenCalledExactlyOnceWith(socialResult));
    expect(network.exchanges()[0].body).toEqual({ id_token: "current-apple", nonce: "owned-nonce", surface: "member", delivery: "web", client_platform: "web", apple_name: "Ada Lovelace" });
    expect(screen.getByRole("button", { name: "Continue with Apple" })).toBeEnabled();
  });

  it("SP05 duplicate Google credential callbacks share one in-flight exchange", async () => {
    network.deferExchange();
    const view = mount();
    await waitFor(() => expect(sdk.callbacks).toHaveLength(1));
    let first!: Promise<void>;
    await act(async () => {
      first = sdk.callbacks[0]({ credential: "one-credential" });
      await sdk.callbacks[0]({ credential: "duplicate" });
    });
    await waitFor(() => expect(network.exchanges()).toHaveLength(1));
    await act(async () => { network.exchange.resolve(jsonResponse(200, socialResult)); await first; });
    expect(view.success).toHaveBeenCalledExactlyOnceWith(socialResult);
    expect(network.exchanges()).toHaveLength(1);
  });

  it("SP06 editing the email hint does not replace Google's identity or request another nonce", async () => {
    const view = mount();
    await waitFor(() => expect(sdk.callbacks).toHaveLength(1));
    for (let index = 1; index <= 14; index += 1) view.change({ email: "new@example.test".slice(0, index) });
    expect(network.nonces()).toHaveLength(1);
    expect(sdk.callbacks).toHaveLength(1);
    await act(async () => { await sdk.callbacks[0]({ credential: "still-current-google" }); });
    expect(view.success).toHaveBeenCalledExactlyOnceWith(socialResult);
  });

  it.each(["google", "apple"])("SP08 old %s nonce cannot start an SDK attempt under a new account", async (provider) => {
    network = socialNetwork(provider === "google" ? { google: socialConfig.google } : { apple: socialConfig.apple });
    network.deferNonce();
    const view = mount();
    if (provider === "apple") fireEvent.click(await screen.findByRole("button", { name: "Continue with Apple" }));
    await waitFor(() => expect(network.nonces()).toHaveLength(1));
    await act(async () => { network.nonce.resolve(jsonResponse(200, { nonce: "obsolete-nonce" })); setAccessToken(accessToken("account-B", { user_id: 2 })); });
    expect(sdk.initialize).not.toHaveBeenCalled();
    expect(sdk.signIn).not.toHaveBeenCalled();
    expect(network.exchanges()).toHaveLength(0);
    expect(view.success).not.toHaveBeenCalled();
  });

  it.each(["google", "apple"])("SP09 an in-flight %s exchange cannot call back into a newer account", async (provider) => {
    network.deferExchange();
    const view = mount();
    let credential: Promise<void> | undefined;
    if (provider === "google") {
      await waitFor(() => expect(sdk.callbacks).toHaveLength(1));
      credential = sdk.callbacks[0]({ credential: "owned-at-dispatch" });
    } else {
      fireEvent.click(await screen.findByRole("button", { name: "Continue with Apple" }));
      await waitFor(() => expect(sdk.signIn).toHaveBeenCalledTimes(1));
      await act(async () => { sdk.popup.resolve({ authorization: { id_token: "owned-at-dispatch" } }); });
    }
    await waitFor(() => expect(network.exchanges()).toHaveLength(1));
    await act(async () => {
      network.exchange.resolve(jsonResponse(200, socialResult));
      setAccessToken(accessToken("account-B", { user_id: 2 }));
      if (credential) await credential;
    });
    expect(view.success).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(accessToken("account-B", { user_id: 2 }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("SP07 staff Google exchange preserves the staff surface", async () => {
    network = socialNetwork({ google: socialConfig.google });
    const success = vi.fn();
    render(<SocialSignInButtons surface="staff" onSuccess={success} />);
    await waitFor(() => expect(sdk.callbacks).toHaveLength(1));
    await act(async () => { await sdk.callbacks[0]({ credential: "staff-google" }); });
    expect(network.exchanges()[0].body.surface).toBe("staff");
    expect(success).toHaveBeenCalledExactlyOnceWith(socialResult);
  });
});

import { accessToken } from "../../test/accessTokens";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getAccessToken } from "../../lib/apiSession";
import { enter } from "../../test/authOwnership";
import { chooseSignup, mountMember, submitMember } from "../../test/memberOwnershipHarness";
import { fakeIdentitySdks, socialConfig, socialNetwork } from "../../test/socialOwnershipHarness";

let sdk: ReturnType<typeof fakeIdentitySdks>;
let network: ReturnType<typeof socialNetwork>;
beforeEach(() => {
  window.history.replaceState({}, "", "/member");
  network = socialNetwork({ google: socialConfig.google });
  sdk = fakeIdentitySdks();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); delete window.google; delete window.AppleID; });

describe("member form owns provider intent without consuming nonce quota on typing", () => {
  it("MP01 fourteen email edits and password typing use one nonce; current Google still authenticates", async () => {
    const view = mountMember();
    await waitFor(() => expect(sdk.callbacks).toHaveLength(1));
    const configCount = network.calls.filter(({ path }) => path === "/config").length;
    expect(configCount).toBe(2);
    for (let index = 1; index <= 14; index += 1) enter("Email", "name@example.test".slice(0, index));
    enter("Password", "typed-private-password");
    expect(network.nonces()).toHaveLength(1);
    expect(sdk.callbacks).toHaveLength(1);
    expect(network.calls.filter(({ path }) => path === "/config")).toHaveLength(configCount);
    await act(async () => { await sdk.callbacks[0]({ credential: "current-google-after-typing" }); });
    await waitFor(() => expect(view.authenticated).toHaveBeenCalledTimes(1));
    expect(network.exchanges()).toHaveLength(1);
    expect(getAccessToken()).toBe(accessToken("provider-access"));
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it.each(["password submission", "Back", "mode"])("MP02 a newer %s invalidates an outstanding Google credential before exchange", async (cancel) => {
    const view = mountMember();
    await waitFor(() => expect(sdk.callbacks).toHaveLength(1));
    const oldCredential = sdk.callbacks[0];
    if (cancel === "password submission") submitMember();
    else if (cancel === "Back") fireEvent.click(screen.getByRole("button", { name: "Back" }));
    else chooseSignup();
    await act(async () => { await oldCredential({ credential: "obsolete-google" }); });
    expect(network.exchanges()).toHaveLength(0);
    expect(view.authenticated).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(accessToken("account-A"));
    if (cancel === "password submission") {
      expect(network.calls.filter(({ path }) => path === "/auth/login")).toHaveLength(1);
      expect(screen.getByLabelText("Password")).toBeDisabled();
    }
  });
});

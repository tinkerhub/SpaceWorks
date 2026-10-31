import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getAccessToken, getSessionGeneration } from "../../lib/api";
import { accessToken } from "../../test/accessTokens";
import { fakeIdentitySdks } from "../../test/socialOwnershipHarness";
import {
  calicut, choose, deferred, json, kochi, leaves, mountStaff, noPanel, panelIs,
  routeIs, saved, settle, staff, stored, transport,
} from "../../test/staffSelectionHarness";
import { staffMeKey } from "./paymentsApi";

afterEach(() => {
  vi.restoreAllMocks();
  delete window.google;
  delete window.AppleID;
});

describe("staff Google ownership after password failure", () => {
  it("keeps ownership while typing, blocks the old callback during password login, and recovers into the central picker", async () => {
    transport.restore = false;
    transport.config = {
      social_auth: { google: { enabled: true, web_client_id: "staff-google-client" } },
    };
    saved(kochi.id);
    const password = deferred<Response>();
    const providerUser = staff({ username: "provider-admin" });
    const providerAccess = accessToken("provider-admin", { user_id: 2, surface: "staff", staff_scope: "platform" });
    const passwordError = "Username or password is incorrect. Try again.";
    let nonceSequence = 0;
    transport.routes.set("/auth/login", () => password.promise);
    transport.routes.set("/auth/social/nonce", () => json({ nonce: `staff-google-nonce-${++nonceSequence}` }));
    transport.routes.set("/auth/social/google", () => json({
      access: providerAccess, user: providerUser, outcome: "existing",
    }));
    const sdk = fakeIdentitySdks();
    const { queryClient } = mountStaff("/m/calicut/admin/settings");
    const requests = (path: string) => transport.calls.filter((call) => call.path === path);

    await screen.findByRole("form", { name: "Staff sign in" });
    await waitFor(() => expect(sdk.initialize).toHaveBeenCalledTimes(1));
    const oldCredential = sdk.callbacks[0];
    expect(sdk.initialize).toHaveBeenNthCalledWith(1, expect.objectContaining({
      client_id: "staff-google-client", nonce: "staff-google-nonce-1", callback: oldCredential,
    }));
    expect(requests("/auth/social/nonce")).toHaveLength(1);

    // Exercise LoginPanel's own controlled fields, without replacing its session callback.
    const username = screen.getByRole("textbox", { name: "Username" });
    const passwordInput = screen.getByLabelText("Password", { exact: true });
    for (const [input, value] of [[username, "password-admin"], [passwordInput, "wrong-password"]] as const) {
      for (let length = 1; length <= value.length; length += 1) {
        fireEvent.change(input, { target: { value: value.slice(0, length) } });
      }
    }
    await act(async () => {});
    expect(sdk.initialize).toHaveBeenCalledTimes(1);
    expect(sdk.renderButton).toHaveBeenCalledTimes(1);
    expect(sdk.callbacks).toEqual([oldCredential]);
    expect(requests("/auth/social/nonce")).toHaveLength(1);

    const tokenBeforePassword = getAccessToken();
    const generationBeforePassword = getSessionGeneration();
    fireEvent.submit(screen.getByRole("form", { name: "Staff sign in" }));
    await waitFor(() => expect(requests("/auth/login")).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Fake Google SDK button" })).not.toBeInTheDocument();
    const passwordRequest = requests("/auth/login")[0];
    expect(passwordRequest.init.method).toBe("POST");
    expect(passwordRequest.init.credentials).toBe("include");
    expect(JSON.parse(String(passwordRequest.init.body))).toEqual({
      username: "password-admin", password: "wrong-password", surface: "staff",
    });

    await act(async () => { await oldCredential({ credential: "obsolete-google-credential" }); });
    expect(requests("/auth/social/google")).toHaveLength(0);
    expect(requests("/auth/social/nonce")).toHaveLength(1);
    expect(sdk.initialize).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe(tokenBeforePassword);
    expect(getSessionGeneration()).toBe(generationBeforePassword);
    expect(queryClient.getQueryData(staffMeKey)).toBeUndefined();
    expect(leaves).toEqual([]);
    noPanel();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await routeIs("/m/calicut/admin/settings");

    await settle(password, json({ detail: passwordError }, 401));
    expect(await screen.findByRole("alert")).toHaveTextContent(passwordError);
    await waitFor(() => expect(sdk.initialize).toHaveBeenCalledTimes(2));
    expect(requests("/auth/social/nonce")).toHaveLength(2);
    expect(sdk.callbacks).toHaveLength(2);
    const currentCredential = sdk.callbacks[1];
    expect(currentCredential).not.toBe(oldCredential);
    expect(sdk.initialize).toHaveBeenNthCalledWith(2, expect.objectContaining({
      client_id: "staff-google-client", nonce: "staff-google-nonce-2", callback: currentCredential,
    }));
    expect(sdk.renderButton).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: /^Sign in$/ })).toBeEnabled();
    expect(getAccessToken()).toBe(tokenBeforePassword);
    expect(queryClient.getQueryData(staffMeKey)).toBeUndefined();

    // A retained SDK callback stays obsolete even after the password error releases the UI.
    await act(async () => {
      await oldCredential({ credential: "still-obsolete-google-credential" });
      await oldCredential({});
    });
    expect(requests("/auth/social/google")).toHaveLength(0);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(screen.getByRole("alert")).toHaveTextContent(passwordError);

    await act(async () => { await currentCredential({ credential: "current-google-credential" }); });
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    await routeIs("/admin");
    expect(screen.getByText(/^Signed in as provider-admin\./)).toBeInTheDocument();
    expect(getAccessToken()).toBe(providerAccess);
    expect(getSessionGeneration()).toBeGreaterThan(generationBeforePassword);
    expect(queryClient.getQueryData(staffMeKey)).toEqual(providerUser);
    expect(stored()).toBeNull();
    expect(leaves).toEqual([]);
    noPanel();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(passwordError)).not.toBeInTheDocument();

    await choose("Calicut");
    await panelIs(calicut.id, "dashboard");
    await routeIs("/m/calicut/admin/dashboard");
    expect(screen.getByTestId("leaf-user")).toHaveTextContent(/^provider-admin$/);
    expect(leaves.every(({ username, id, tab }) =>
      username === "provider-admin" && id === calicut.id && tab === "dashboard")).toBe(true);
    expect(stored()).toBe(String(calicut.id));
    expect(getAccessToken()).toBe(providerAccess);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/Sign-in is no longer active|Google sign-in (failed|was cancelled)/)).not.toBeInTheDocument();

    expect(requests("/auth/login")).toHaveLength(1);
    expect(requests("/auth/social/nonce")).toHaveLength(2);
    for (const { init } of requests("/auth/social/nonce")) {
      expect(init.method).toBe("POST");
      expect(JSON.parse(String(init.body))).toEqual({
        provider: "google", surface: "staff", delivery: "web", client_platform: "web",
      });
    }
    const exchanges = transport.calls.filter(({ path }) =>
      path.startsWith("/auth/social/") && path !== "/auth/social/nonce");
    expect(exchanges).toHaveLength(1);
    expect(exchanges[0].path).toBe("/auth/social/google");
    expect(exchanges[0].init.method).toBe("POST");
    expect(exchanges[0].init.credentials).toBe("include");
    expect(JSON.parse(String(exchanges[0].init.body))).toEqual({
      id_token: "current-google-credential", nonce: "staff-google-nonce-2",
      surface: "staff", delivery: "web", client_platform: "web",
    });
    expect(sdk.initialize).toHaveBeenCalledTimes(2);
  });
});

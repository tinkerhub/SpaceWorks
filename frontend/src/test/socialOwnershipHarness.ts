import { accessToken } from "./accessTokens";
import { vi } from "vitest";
import { fetchMock, jsonResponse, resetSessionTransport } from "../lib/apiSessionTestHelpers";
import { held } from "./authOwnership";
import type { SocialConfig, SocialLoginResult } from "../features/auth/socialSdk";

export const socialResult: SocialLoginResult = { access: accessToken("provider-access"), user: { username: "A" }, outcome: "existing" };
export const socialConfig: SocialConfig = {
  google: { enabled: true, web_client_id: "configured-google-client" },
  apple: { enabled: true, service_id: "configured-apple-service" },
  "oidc:campus": { enabled: true, display_name: "Campus SSO", client_id: "campus", issuer: "https://idp.example.test" },
};
export type GoogleCredential = (response: { credential?: string }) => Promise<void>;
export type ApplePopup = { authorization: { id_token: string }; user?: { name?: { firstName?: string; lastName?: string } } };
export function fakeIdentitySdks() {
  const callbacks: GoogleCredential[] = [];
  const initialize = vi.fn((options: Record<string, unknown>) => { callbacks.push(options.callback as GoogleCredential); });
  const renderButton = vi.fn((element: HTMLElement) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Fake Google SDK button";
    element.appendChild(button);
  });
  const popup = held<ApplePopup>();
  const appleInit = vi.fn();
  const signIn = vi.fn(() => popup.promise);
  window.google = { accounts: { id: { initialize, renderButton } } };
  window.AppleID = { auth: { init: appleInit, signIn } };
  const append = document.head.appendChild.bind(document.head);
  vi.spyOn(document.head, "appendChild").mockImplementation(<T extends Node>(node: T): T => {
    const result = append(node);
    if (node instanceof HTMLScriptElement && /accounts.google.com|appleid.cdn-apple.com/.test(node.src)) {
      queueMicrotask(() => node.dispatchEvent(new Event("load")));
    }
    return result;
  });
  // Keep loaded script elements: socialSdk's module-level cache remains canonical across cases.
  return { callbacks, initialize, renderButton, popup, appleInit, signIn };
}
export type SocialCall = { path: string; body: Record<string, unknown>; init: RequestInit };
export function socialNetwork(config: SocialConfig = socialConfig, accounts = true) {
  resetSessionTransport(accessToken("account-A"));
  const calls: SocialCall[] = [];
  const exchange = held<Response>();
  const authorize = held<Response>();
  const password = held<Response>();
  const nonce = held<Response>();
  let holdNonce = false;
  let holdExchange = false;
  fetchMock.mockImplementation(async (url, init = {}) => {
    const path = new URL(String(url), "http://localhost").pathname.split("/api/v1").pop()!;
    const body = typeof init.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : {};
    calls.push({ path, body, init });
    if (path === "/config") return jsonResponse(200, { social_auth: config, member_accounts: { enabled: accounts } });
    if (path === "/auth/social/nonce") return holdNonce ? nonce.promise : jsonResponse(200, { nonce: "owned-nonce" });
    if (path === "/auth/login") return password.promise;
    if (path.endsWith("/authorize")) return authorize.promise;
    if (["/auth/social/google", "/auth/social/apple", "/auth/social/oidc/callback"].includes(path)) {
      return holdExchange ? exchange.promise : jsonResponse(200, socialResult);
    }
    if (path === "/auth/logout") return jsonResponse(204);
    throw new Error(`Unexpected mocked identity request: ${path}`);
  });
  return { calls, exchange, authorize, password, nonce, deferNonce: () => { holdNonce = true; }, deferExchange: () => { holdExchange = true; },
    exchanges: () => calls.filter(({ path }) => ["/auth/social/google", "/auth/social/apple", "/auth/social/oidc/callback"].includes(path)),
    nonces: () => calls.filter(({ path }) => path === "/auth/social/nonce"),
  };
}

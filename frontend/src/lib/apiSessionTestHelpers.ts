import { accessToken } from "../test/accessTokens";
import { vi } from "vitest";

import {
  cacheTenantPublishableKey, clearAccessToken, setAccessToken,
  setRuntimePublishableKey, tenantPublishableKeys,
} from "./apiSession";

export const fetchMock = vi.fn<typeof fetch>();

export function jsonResponse(status: number, body: unknown = {}) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  });
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

/** The entered signal pins the race to a transport boundary, without timer polling. */
export function heldResponse() {
  const entered = deferred<void>();
  const result = deferred<Response>();
  const send = () => {
    entered.resolve();
    return result.promise;
  };
  return { entered: entered.promise, resolve: result.resolve, send };
}

export function resetSessionTransport(token = accessToken("old-access")) {
  window.localStorage.clear();
  window.sessionStorage.clear();
  // Explicit login also resets the in-memory logout latch and pending refresh owner.
  setAccessToken(token || accessToken("cleared-session"));
  if (!token) clearAccessToken();
  setRuntimePublishableKey("");
  tenantPublishableKeys.clear();
  cacheTenantPublishableKey("forge", "pk_forge");
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
}

export function requestHeaders(call: number) {
  return new Headers(fetchMock.mock.calls[call][1]?.headers);
}

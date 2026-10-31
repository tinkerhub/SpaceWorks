import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAccessToken, getAccessToken, getSessionGeneration, logout, setAccessToken } from "../../lib/apiSession";
import { accessToken } from "../../test/accessTokens";
import { deferred, resetLendingSession } from "../../test/publicLendingHarness";
import { usePublicSession } from "./usePublicSession";

const transport = vi.fn<typeof fetch>();
function mountProbe() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = renderHook(() => usePublicSession("a"), {
    wrapper: ({ children }) => <QueryClientProvider client={client}><MemoryRouter>{children}</MemoryRouter></QueryClientProvider>,
  });
  return { ...view, client };
}
const response = (token: string) => new Response(JSON.stringify({ access: token }), {
  status: 200, headers: { "Content-Type": "application/json" },
});
beforeEach(() => { resetLendingSession(); transport.mockReset(); vi.stubGlobal("fetch", transport); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("public session probe generation and cancellation", () => {
  it("cached true from before logout never authorizes the signed-out public visitor", async () => {
    setAccessToken(accessToken("probe-member"));
    const generation = getSessionGeneration();
    const view = mountProbe();
    await waitFor(() => expect(view.result.current.authenticated).toBe(true));
    await waitFor(() => expect(view.client.getQueryData(["public-request-session", "a", generation])).toBe(true));
    transport.mockResolvedValue(new Response(null, { status: 204 }));
    await act(async () => { await logout(); });
    view.rerender();
    expect(view.result.current.authenticated).toBe(false);
    await waitFor(() => expect(view.result.current.signedOut).toBe(true));
    expect(view.client.getQueryData(["public-request-session", "a", generation])).toBe(true);
    expect(getAccessToken()).toBe("");
    expect(transport).toHaveBeenCalledTimes(1);
    expect(String(transport.mock.calls[0][0])).toMatch(/\/auth\/logout$/);
  });

  it("an in-flight refresh cannot install or publish the old actor after a new session generation", async () => {
    setAccessToken(accessToken("probe-old-login")); clearAccessToken();
    const oldGeneration = getSessionGeneration();
    const held = deferred<Response>(); transport.mockReturnValue(held.promise);
    const view = mountProbe();
    await waitFor(() => expect(transport).toHaveBeenCalledTimes(1));
    const nextToken = accessToken("probe-next-login", { user_id: 2 });
    act(() => { setAccessToken(nextToken); });
    view.rerender();
    await waitFor(() => expect(view.result.current.authenticated).toBe(true));
    await act(async () => { held.resolve(response(accessToken("probe-old-refresh"))); });
    expect(getAccessToken()).toBe(nextToken);
    expect(view.client.getQueryData(["public-request-session", "a", oldGeneration])).not.toBe(true);
    expect(view.result.current.authenticated).toBe(true);
  });

  it("cancelling a held probe prevents its result from entering the public query cache", async () => {
    setAccessToken(accessToken("probe-reload")); clearAccessToken();
    const held = deferred<Response>(); transport.mockReturnValue(held.promise);
    const generation = getSessionGeneration();
    const view = mountProbe();
    await waitFor(() => expect(transport).toHaveBeenCalledTimes(1));
    await act(async () => { await view.client.cancelQueries({ queryKey: ["public-request-session", "a", generation] }); });
    await act(async () => { held.resolve(response(accessToken("probe-reloaded"))); });
    expect(view.client.getQueryData(["public-request-session", "a", generation])).toBeUndefined();
    expect(view.client.getQueryState(["public-request-session", "a", generation])?.fetchStatus).toBe("idle");
  });

  it("a matching refresh in the current generation restores a reloaded member", async () => {
    setAccessToken(accessToken("probe-signed-in")); clearAccessToken();
    const held = deferred<Response>(); transport.mockReturnValue(held.promise);
    const view = mountProbe();
    expect(view.result.current.authenticated).toBe(false);
    expect(view.result.current.settled).toBe(false);
    await waitFor(() => expect(transport).toHaveBeenCalledTimes(1));
    const refreshed = accessToken("probe-refreshed");
    await act(async () => { held.resolve(response(refreshed)); });
    await waitFor(() => expect(view.result.current).toEqual({ authenticated: true, settled: true, signedOut: false }));
    expect(getAccessToken()).toBe(refreshed);
    expect(transport.mock.calls[0][1]).toMatchObject({ credentials: "include", method: "POST" });
  });
});

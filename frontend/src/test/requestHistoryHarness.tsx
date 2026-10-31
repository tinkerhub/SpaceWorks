import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render } from "@testing-library/react";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { vi } from "vitest";
import { ToastProvider } from "../components/ui";
import { clearAccessToken, setAccessToken, tenantPublishableKeys } from "../lib/apiSession";
import { TenantProvider } from "../lib/tenant";
import { accessToken } from "./accessTokens";
import { bootstrapFixture } from "./uiRegressionHarness";

export { accessToken } from "./accessTokens";
export { deferred } from "./uiRegressionHarness";
export const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
export const hardware = (token = "hardware-1", status = "partially_returned") => ({
  public_token: token, status, created_at: "2026-10-01T09:00:00Z",
  items: [{ product_name: `Tool ${token}`, requested_quantity: 9, accepted_quantity: 6,
    issued_quantity: 4, returned_quantity: 2 }],
  cancellation_reason: "Private staff reason", contact_email: "other@example.com",
  requester: { username: "unrelated-person" }, evidence: "private-photo.jpg",
});
export const machine = (token = "machine-1", status = "completed") => ({
  public_token: token, title: `Project ${token}`, status, created_at: "2026-10-01T09:00:00Z",
  accepted_at: null, started_at: null, completed_at: null, estimated_minutes: 0,
  queue_position: null, queue_approved_ahead: 0, queue_awaiting_review_ahead: 0,
});
export const page = (results: unknown[], count = results.length, next: string | null = null) => ({
  count, next, previous: null, results,
});

/** Only fetch/storage leaves are controlled; routing, tenant, session and owners stay real. */
export function requestHistoryNetwork({ accounts = false, modules = ["request_workflow", "machine_service"] } = {}) {
  localStorage.clear(); sessionStorage.clear(); tenantPublishableKeys.clear();
  delete window.__TENANT__;
  setAccessToken(accessToken("history-initial")); clearAccessToken();
  localStorage.setItem("makerspace.signed-out", "1");
  const bootstraps = new Map(["a", "b"].map((slug) => {
    const dto = bootstrapFixture(slug);
    dto.modules = [...modules, ...(accounts ? ["member_accounts"] : [])];
    dto.public_api.publishable_key = `public-${slug}`;
    return [slug, dto] as const;
  }));
  const bootstrap = vi.fn(async (url: URL) => json(bootstraps.get(url.searchParams.get("slug") || "a")));
  const mine = vi.fn(async (url: URL, _init?: RequestInit): Promise<Response> => json(page([
    url.pathname.includes("machine-service") ? machine() : hardware(),
  ])));
  const status = vi.fn(async (url: URL, _init?: RequestInit): Promise<Response> => {
    const segments = url.pathname.split("/");
    const token = decodeURIComponent(segments[segments.length - 2]);
    return json(url.pathname.includes("machine-service") ? machine(token) : hardware(token));
  });
  const refresh = vi.fn(async (): Promise<Response> => json({ detail: "Signed out" }, 401));
  const signout = vi.fn(async (): Promise<Response> => json({}));
  const other = vi.fn(async (url: URL, _init?: RequestInit): Promise<Response> => {
    throw new Error(`Unexpected request history HTTP: ${url}`);
  });
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/bootstrap")) return bootstrap(url);
    if (url.pathname.endsWith("/mine")) return mine(url, init);
    if (url.pathname.endsWith("/status")) return status(url, init);
    if (url.pathname.endsWith("/auth/refresh")) return refresh();
    if (url.pathname.endsWith("/auth/logout")) return signout();
    return other(url, init);
  });
  vi.stubGlobal("fetch", fetch);
  const clients: QueryClient[] = [];
  function client(seed = true) {
    const result = new QueryClient({ defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity }, mutations: { retry: false },
    } });
    if (seed) for (const [slug, dto] of bootstraps) result.setQueryData(["tenant-bootstrap", slug], dto);
    clients.push(result);
    return result;
  }
  function mount(content: ReactNode, path = "/m/a/my-requests", cache = client()) {
    let navigate!: ReturnType<typeof useNavigate>;
    function Navigation() { navigate = useNavigate(); return content; }
    const view = render(<QueryClientProvider client={cache}><TenantProvider>
      <MemoryRouter initialEntries={[path]}><ToastProvider><Navigation /></ToastProvider></MemoryRouter>
    </TenantProvider></QueryClientProvider>);
    return { ...view, client: cache, navigate: (to: string) => act(() => { void navigate(to); }) };
  }
  function dispose() {
    cleanup(); clients.forEach((cache) => cache.clear()); clearAccessToken(); tenantPublishableKeys.clear();
    localStorage.clear(); sessionStorage.clear(); delete window.__TENANT__; vi.unstubAllGlobals();
  }
  return { bootstraps, bootstrap, mine, status, refresh, signout, other, fetch, client, mount, dispose };
}

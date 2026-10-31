import { cloneElement, isValidElement, useLayoutEffect, type ComponentProps, type ReactNode } from "react";
import { QueryClient, onlineManager } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { vi } from "vitest";
import { ToastProvider } from "../components/ui";
import { ServiceRequestForm } from "../features/machineService/ServiceRequestForm";
import { genericType, printerType, serviceStatus } from "../features/machineService/serviceTestFixtures";
import { clearAccessToken, setAccessToken, tenantPublishableKeys } from "../lib/apiSession";
import { accessToken } from "./accessTokens";
import { bootstrapFixture, deferred, RegressionProviders, rosterMatch } from "./uiRegressionHarness";

export { deferred, genericType, printerType, serviceStatus, rosterMatch, accessToken };
export { API_V1_URL } from "../lib/apiConfig";
export const personB = { ...rosterMatch, mid: 900, name: "Bea Canonical", project_name: "Bea project" };
export const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});
export const staged = (file_id = 17, queue_id = 8) => ({
  file_id, queue_id, upload: { url: `https://storage.example/${file_id}`, fields: { key: `staging/${file_id}` } },
});
export const pdf = (name = "private.pdf") => new File(["%PDF-private"], name, { type: "application/pdf" });

// Only external fetch leaves are controlled. All API/session/owner/upload code is real.
export function serviceNetwork() {
  const wasOnline = onlineManager.isOnline();
  onlineManager.setOnline(true);
  localStorage.clear();
  sessionStorage.clear();
  tenantPublishableKeys.clear();
  setAccessToken(accessToken("service-A", { user_id: 1 }));
  const bootstraps = new Map(["a", "b"].map((slug) => {
    const dto = bootstrapFixture(slug);
    delete dto.makerspace.request_access; // Account-only bootstrap policy is represented by omission.
    dto.modules = ["machines", "machine_service", "printing", "member_accounts", "public_inventory", "request_workflow"];
    dto.public_api.publishable_key = `public-${slug}`;
    return [slug, dto] as const;
  }));
  const types = vi.fn(async (_url: string, _init?: RequestInit): Promise<Response> =>
    json({ results: [genericType, printerType], next: null }));
  const presign = vi.fn(async (_url: string, _init?: RequestInit): Promise<Response> => json(staged()));
  const storage = vi.fn(async (_url: string, _init?: RequestInit): Promise<Response> => new Response(null, { status: 204 }));
  const create = vi.fn(async (_url: string, _init?: RequestInit): Promise<Response> =>
    json({ public_token: "current-token", status: "pending" }));
  const status = vi.fn(async (url: string, _init?: RequestInit): Promise<Response> => {
    const segments = new URL(url, "http://localhost").pathname.split("/");
    return json({ ...serviceStatus, public_token: decodeURIComponent(segments[segments.length - 2]) });
  });
  const borrow = vi.fn(async (_url: string, _init?: RequestInit): Promise<Response> => json({
    status: "accepted", created_at: "2026-10-01T09:00:00Z", rejection_reason: "",
    items: [{ product_name: "Current tool", requested_quantity: 1 }],
  }));
  const lookup = vi.fn(async (_url: string, _init?: RequestInit): Promise<Response> => json([rosterMatch]));
  const refresh = vi.fn(async (_url: string, _init?: RequestInit): Promise<Response> =>
    json({ access: accessToken("service-refreshed", { user_id: 1 }) }));
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    if (url.startsWith("https://storage.example/")) return storage(url, init);
    const parsed = new URL(url, "http://localhost");
    const path = parsed.pathname;
    if (path.endsWith("/bootstrap")) return json(bootstraps.get(parsed.searchParams.get("slug") ?? "a"));
    if (path.endsWith("/categories")) return json([]);
    if (path.endsWith("/auth/refresh")) return refresh(url, init);
    if (path.endsWith("/machine-service/types")) return types(url, init);
    if (path.endsWith("/machine-service/uploads")) return presign(url, init);
    if (path.endsWith("/machine-service-requests")) return create(url, init);
    if (path.includes("/machine-service/requests/")) return status(url, init);
    if (path.includes("/public/requests/")) return borrow(url, init);
    if (path.endsWith("/checkin/lookup")) return lookup(url, init);
    throw new Error(`Unexpected service test fetch: ${url}`);
  });
  vi.stubGlobal("fetch", fetch);
  const clients: QueryClient[] = [];
  function client() {
    const result = new QueryClient({ defaultOptions: {
      queries: { retry: false, staleTime: Infinity, gcTime: Infinity }, mutations: { retry: false },
    } });
    for (const [slug, bootstrap] of bootstraps) {
      result.setQueryData(["tenant-bootstrap", slug], bootstrap);
      result.setQueryData(["public-categories", slug], []);
    }
    clients.push(result);
    return result;
  }
  function dispose() {
    cleanup();
    clients.forEach((value) => value.clear());
    clearAccessToken();
    tenantPublishableKeys.clear();
    localStorage.clear();
    sessionStorage.clear();
    onlineManager.setOnline(wasOnline);
    vi.unstubAllGlobals();
  }
  return { fetch, types, presign, storage, create, status, borrow, lookup, refresh, bootstraps, client, dispose };
}
export type ServiceNetwork = ReturnType<typeof serviceNetwork>;
export function body(call: [string, RequestInit?]) { return JSON.parse(String(call[1]?.body)); }
export function title(value = "Private A project") {
  fireEvent.change(screen.getByLabelText("Title"), { target: { value } });
}
export function field(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}
export function attach(files = [pdf()], label: string | RegExp = "Attachments") {
  fireEvent.change(screen.getByLabelText(label), { target: { files } });
}
export function submit() {
  const form = screen.getByLabelText("Title").closest("form");
  if (!form) throw new Error("Missing actual service form");
  fireEvent.submit(form);
}
export function choose(label: string, option: string) {
  fireEvent.click(screen.getByRole("combobox", { name: label }));
  fireEvent.click(screen.getByRole("option", { name: option }));
}
export async function settle(complete: () => void) {
  await act(async () => { complete(); });
}

type FormProps = ComponentProps<typeof ServiceRequestForm>;
export function mountServiceForm(net: ServiceNetwork, overrides: Partial<FormProps> = {}) {
  const client = net.client();
  const onSuccess = vi.fn(), onPendingChange = vi.fn();
  let props: FormProps = { slug: "a", type: structuredClone(genericType), identity: {
    name: rosterMatch.name, checkin_mid: rosterMatch.mid,
  }, identityReady: true, onSuccess, onPendingChange, ...overrides };
  const ui = () => <RegressionProviders client={client}><ToastProvider>
    <ServiceRequestForm {...props} />
  </ToastProvider></RegressionProviders>;
  const view = render(ui());
  return { ...view, client, onSuccess, onPendingChange,
    visit: (next: Partial<FormProps> = {}) => { props = { ...props, ...next }; view.rerender(ui()); } };
}

// The same route element survives navigation; production code owns all remounts.
export function mountServiceRoute(net: ServiceNetwork, children: ReactNode, path = "/m/a/service?type=11") {
  const client = net.client();
  let navigate!: ReturnType<typeof useNavigate>;
  const frames: { path: string; text: string; inputs: string[]; links: (string | null)[] }[] = [];
  function RouteFrame({ content }: { content: ReactNode }) {
    navigate = useNavigate();
    const location = useLocation();
    useLayoutEffect(() => {
      frames.push({ path: location.pathname + location.search, text: document.body.textContent ?? "",
        inputs: Array.from(document.querySelectorAll("input")).map((input) => input.value),
        links: Array.from(document.querySelectorAll("a")).map((anchor) => anchor.getAttribute("href")) });
    });
    return <>{content}</>;
  }
  let content = children;
  const ui = () => <RegressionProviders client={client} path={path}><ToastProvider><Routes>
    <Route path="/m/:slug/service" element={<RouteFrame content={content} />} />
  </Routes></ToastProvider></RegressionProviders>;
  const view = render(ui());
  return { ...view, client, frames,
    navigate: (next: string) => act(() => { void navigate(next); }),
    redraw: (next: ReactNode = content) => {
      content = isValidElement(next) ? cloneElement(next) : next;
      view.rerender(ui());
    } };
}

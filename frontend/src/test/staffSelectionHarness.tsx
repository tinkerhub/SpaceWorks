import { accessToken } from "./accessTokens";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { StrictMode, useState, type ComponentProps, type ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, expect, vi } from "vitest";

const shared = vi.hoisted(() => ({
  leaves: [] as { id?: number; tab: string; username: string; override: boolean }[],
  wipeOfflineScopes: vi.fn<(...args: unknown[]) => Promise<void>>(),
}));
vi.mock("../features/staff/eventCheckInOfflineStore", () => ({ wipeOfflineScopes: shared.wipeOfflineScopes }));
// Only the expensive panel leaf is replaced. Routing, session, access calculation,
// workspace, shell, account menu, picker and both list consumers stay real.
vi.mock("../features/staff/StaffTabContent", async () => {
  const { useConsoleModule } = await import("../features/staff/panels/machine/useConsoleModule");
  return {
    StaffTabContent: (props: ComponentProps<typeof import("../features/staff/StaffTabContent").StaffTabContent>) => {
      shared.leaves.push({ id: props.activeMakerspace?.id, tab: props.activeTab,
        username: props.currentUser.username, override: props.isSuperadmin });
      const payments = useConsoleModule(props.activeMakerspace?.id ?? -1, "payments");
      return <section aria-label="Operational panel">
        <output data-testid="leaf-space">{props.activeMakerspace?.id}</output>
        <output data-testid="leaf-tab">{props.activeTab}</output>
        <output data-testid="leaf-user">{props.currentUser.username}</output>
        <output data-testid="leaf-authority">{JSON.stringify({
          override: props.isSuperadmin, edit: props.canEditInventory,
          machines: props.canManageMachines, settings: props.canManageMakerspace,
          configure: props.canConfigureMachineTypes, payments,
        })}</output>
        <button onClick={props.onAuthRefresh}>Refresh identity and access</button>
      </section>;
    },
  };
});

import { StaffApp } from "../features/staff/StaffApp";
import type { Makerspace } from "../features/staff/panels/shared";
import { STAFF_SELECTED_MAKERSPACE_KEY } from "../features/staff/staffTabs";
import { clearAccessToken, setAccessToken, type StaffAuthUser, type TenantBootstrap } from "../lib/api";
import { TenantProvider } from "../lib/tenant";

export const leaves = shared.leaves;
export const wipeOfflineScopes = shared.wipeOfflineScopes;
export const kochi = space(1, "kochi");
export const calicut = space(2, "calicut");
export function space(id: number, slug: string, extra: Partial<Makerspace> = {}): Makerspace {
  return { id, slug, name: slug === "kochi" ? "Kochi" : "Calicut", public_code: slug.toUpperCase(),
    telegram_group_chat_id: "", frontend_domain: null, hidden_from_central_directory: false,
    superadmin_access_enabled: true, enabled_modules: ["machines", "payments", "public_inventory"],
    enabled_features: [], ...extra };
}
export function membership(target: Makerspace, actions: string[] = ["manage_machines"]): StaffAuthUser["makerspaces"][number] {
  return { id: target.id, slug: target.slug, role: null, role_id: 10 + target.id,
    role_name: "Laser operator", role_slug: "laser-operator", source: "membership", actions,
    can_configure_machine_types: false, is_machine_only: true, can_refer: false,
    can_verify: false, verified_at: null, referrals_enabled: false, currency: "inr" };
}
export function staff(extra: Partial<StaffAuthUser> = {}): StaffAuthUser {
  return { username: "global-admin", email_verified: true, role: "superadmin", is_superuser: true,
    must_change_password: false, makerspaces: [], ...extra };
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
export function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
type Reply = (init: RequestInit) => Response | Promise<Response>;
export const transport = {
  routes: new Map<string, Reply>(),
  calls: [] as { path: string; init: RequestInit }[],
  user: staff(),
  spaces: [kochi, calicut] as Makerspace[],
  restore: true,
  config: {} as Record<string, unknown>,
};
export function saved(id: number) { localStorage.setItem(STAFF_SELECTED_MAKERSPACE_KEY, String(id)); }
export function stored() { return localStorage.getItem(STAFF_SELECTED_MAKERSPACE_KEY); }
export function listCalls() { return transport.calls.filter(({ path }) => path === "/admin/makerspaces"); }
export function bootstrap(target = kochi): TenantBootstrap {
  return { makerspace: { id: target.id, slug: target.slug, name: target.name, public_code: target.public_code,
    location: "", geofence_enabled: false, membership_policy: "open" },
    frontend: { type: "makerspace", hostname: "kochi.example", allowed_origins: [] },
    modules: target.enabled_modules ?? [], features: [], workflows: [], theme: {}, branding: {},
    email_enabled: false, public_api: { base_url: "", publishable_key: "test-key", inventory_path: "" } };
}
const clients: QueryClient[] = [];
export function client() {
  const next = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity }, mutations: { retry: false } } });
  clients.push(next);
  return next;
}
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  clearAccessToken();
  setAccessToken(accessToken("initial-test-session", { surface: "staff", staff_scope: "platform" }));
  delete window.__TENANT__;
  leaves.length = 0;
  transport.routes.clear();
  transport.calls.length = 0;
  transport.user = staff();
  transport.spaces = [kochi, calicut];
  transport.restore = true;
  transport.config = {};
  let sessionUserId = 1;
  wipeOfflineScopes.mockReset().mockResolvedValue(undefined);
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = new URL(String(input), "http://localhost").pathname.replace(/^\/api\/v1/, "");
    transport.calls.push({ path, init });
    const custom = transport.routes.get(path);
    if (custom) return custom(init);
    if (path === "/auth/refresh") return json(transport.restore ? {
      access: accessToken("restored-token", { user_id: sessionUserId, surface: "staff", staff_scope: "platform" }),
    } : {}, transport.restore ? 200 : 401);
    if (path === "/auth/me") return json(transport.user);
    if (path === "/auth/login") {
      sessionUserId = 2;
      return json({ access: accessToken("new-login", { user_id: sessionUserId, surface: "staff", staff_scope: "platform" }),
        user: transport.user, surface: "staff" });
    }
    if (path === "/auth/logout") return json({});
    if (path === "/admin/makerspaces") return json(transport.spaces);
    if (path === "/recovery") return json({ mode: "normal" });
    if (path === "/config") return json(transport.config);
    if (path === "/bootstrap") return json(bootstrap());
    if (path.endsWith("/unread-count")) return json({ count: 0 });
    throw new Error(`Unexpected staff selection transport: ${path}`);
  }));
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((queryClient) => queryClient.clear());
  vi.unstubAllGlobals();
  delete window.__TENANT__;
});

function RouteControls({ children }: { children: (key: number) => ReactNode }) {
  const location = useLocation();
  const navigate = useNavigate();
  const [key, setKey] = useState(0);
  const [path, setPath] = useState("");
  return <>
    <output data-testid="route">{location.pathname}</output>
    <input aria-label="Test destination" value={path} onChange={(event) => setPath(event.target.value)} />
    <button onClick={() => navigate(path)}>Navigate test route</button>
    <button onClick={() => navigate(-1)}>History back</button>
    <button onClick={() => navigate(1)}>History forward</button>
    <button onClick={() => setKey((value) => value + 1)}>Remount staff app</button>
    {children(key)}
  </>;
}
export function mountStaff(path = "/admin", options: { guestOnly?: boolean; strict?: boolean; queryClient?: QueryClient } = {}) {
  const queryClient = options.queryClient ?? client();
  const tree = <QueryClientProvider client={queryClient}><TenantProvider>
    <MemoryRouter initialEntries={[path]}>
      <RouteControls>{(key) => <Routes><Route path="*" element={<StaffApp key={key} guestOnly={options.guestOnly} />} /></Routes>}</RouteControls>
    </MemoryRouter>
  </TenantProvider></QueryClientProvider>;
  return { ...render(options.strict ? <StrictMode>{tree}</StrictMode> : tree), queryClient };
}
export async function routeIs(path: string) { await waitFor(() => expect(screen.getByTestId("route")).toHaveTextContent(new RegExp(`^${path}$`))); }
export async function panelIs(id: number, tab?: string) {
  await waitFor(() => expect(screen.getByTestId("leaf-space").textContent).toBe(String(id)));
  if (tab) expect(screen.getByTestId("leaf-tab")).toHaveTextContent(tab);
}
export function noPanel() { expect(screen.queryByRole("region", { name: "Operational panel" })).not.toBeInTheDocument(); }
export function authority() { return JSON.parse(screen.getByTestId("leaf-authority").textContent ?? "{}"); }
export function navigateTo(path: string) {
  fireEvent.change(screen.getByLabelText("Test destination"), { target: { value: path } });
  fireEvent.click(screen.getByRole("button", { name: "Navigate test route" }));
}
export async function passwordLogin() {
  await screen.findByRole("form", { name: "Staff sign in" });
  fireEvent.change(screen.getByRole("textbox", { name: "Username" }), { target: { value: "global-admin" } });
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "test-password" } });
  fireEvent.submit(screen.getByRole("form", { name: "Staff sign in" }));
}
export async function choose(name: string) {
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(`${name}.*Operate this makerspace`, "i") }));
}
export async function settle<T>(pending: ReturnType<typeof deferred<T>>, value: T) {
  await act(async () => { pending.resolve(value); await pending.promise; });
}

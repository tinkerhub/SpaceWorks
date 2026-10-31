import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, useLocation, type NavigateOptions, type To } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const navigation = vi.hoisted(() => ({
  held: true,
  queued: [] as { path: string; commit: () => void | Promise<void> }[],
}));
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  const { useCallback } = await import("react");
  return { ...actual, useNavigate: () => {
    const navigate = actual.useNavigate();
    // Delay only acknowledgement. The real MemoryRouter still owns useLocation,
    // location keys, route state and the eventual commit.
    return useCallback((to: To | number, options?: NavigateOptions) => {
      if (typeof to === "number") return navigate(to);
      if (!navigation.held) return navigate(to, options);
      navigation.queued.push({ path: typeof to === "string" ? to : to.pathname ?? "",
        commit: () => navigate(to, options) });
    }, [navigate]);
  } };
});

import { getSessionGeneration, setAccessToken } from "../../lib/apiSession";
import { TenantProvider } from "../../lib/tenant";
import { accessToken } from "../../test/accessTokens";
import {
  calicut, choose, client, json, kochi, leaves, mountStaff, noPanel, panelIs,
  passwordLogin, routeIs, saved, stored, transport,
} from "../../test/staffSelectionHarness";
import { staffMakerspacesKey } from "./useStaffMakerspaces";
import { useStaffSession } from "./useStaffSession";

const restored = () => accessToken("acknowledgement-staff", { surface: "staff", staff_scope: "platform" });
beforeEach(() => {
  navigation.held = true; navigation.queued.length = 0;
  setAccessToken(restored());
  transport.routes.set("/auth/refresh", () => transport.restore ? json({ access: restored() }) : json({}, 401));
  transport.routes.set("/auth/login", () => json({
    access: accessToken("acknowledgement-new-staff", { surface: "staff", staff_scope: "platform" }),
    surface: "staff", user: transport.user,
  }));
});
function scheduled() { return navigation.queued.map(({ path }) => path); }
async function acknowledge() {
  const next = navigation.queued.shift();
  expect(next).toBeDefined();
  await act(async () => { await next!.commit(); });
}
function hookSession() {
  const queryClient = client();
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={queryClient}>
    <TenantProvider><MemoryRouter initialEntries={["/m/kochi/admin/settings"]}>{children}</MemoryRouter></TenantProvider>
  </QueryClientProvider>;
  return renderHook(() => ({ session: useStaffSession(false), location: useLocation() }), { wrapper });
}

describe("staff selection waits for a committed route", () => {
  it("a fresh superadmin login masks the old scoped workspace and picker until /admin commits, then chooses Calicut's dashboard", async () => {
    transport.restore = false;
    saved(kochi.id);
    const { queryClient } = mountStaff("/m/kochi/admin/settings");
    await passwordLogin();
    await waitFor(() => expect(scheduled()).toEqual(["/admin"]));
    // Ensure this is the navigation barrier, rather than an unfinished access query.
    await waitFor(() => expect(queryClient.getQueryState(staffMakerspacesKey(getSessionGeneration()))?.status).toBe("success"));
    expect(screen.getByTestId("route")).toHaveTextContent(/^\/m\/kochi\/admin\/settings$/);
    expect(within(screen.getByRole("main")).getByRole("status")).toHaveTextContent("Checking makerspace access…");
    noPanel();
    expect(leaves).toEqual([]);
    expect(screen.queryByRole("heading", { name: "Choose a makerspace to operate" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Operate this makerspace/i })).not.toBeInTheDocument();
    expect(stored()).toBeNull();

    await acknowledge();
    await routeIs("/admin");
    await screen.findByRole("heading", { name: "Choose a makerspace to operate" });
    expect(leaves).toEqual([]);
    await choose("Calicut");
    expect(scheduled()).toEqual(["/m/calicut/admin/dashboard"]);
    expect(screen.getByTestId("route")).toHaveTextContent(/^\/admin$/);
    noPanel();
    expect(screen.queryByRole("button", { name: /Operate this makerspace/i })).not.toBeInTheDocument();
    await acknowledge();
    await routeIs("/m/calicut/admin/dashboard");
    await panelIs(calicut.id, "dashboard");
    expect(leaves.every(({ id, tab }) => id === calicut.id && tab === "dashboard")).toBe(true);
    expect(stored()).toBe(String(calicut.id));
  });

  it("invalidates a retained chooser synchronously, rejects the pending render's callback, and accepts the acknowledged picker's fresh callback", async () => {
    const { result } = hookSession();
    await waitFor(() => expect(result.current.session.selected).toBe(kochi.id));
    const retainedChoose = result.current.session.chooseMakerspace;
    const sourceKey = result.current.location.key;
    act(() => { retainedChoose(null); retainedChoose(calicut.id); });
    expect(scheduled()).toEqual(["/admin"]);
    expect(result.current.location.key).toBe(sourceKey);
    expect(result.current.location.pathname).toBe("/m/kochi/admin/settings");
    expect(result.current.session.selection.kind).toBe("loading");
    expect(result.current.session.selected).toBeNull();
    expect(stored()).toBeNull();
    act(() => result.current.session.chooseMakerspace(calicut.id));
    expect(scheduled()).toEqual(["/admin"]);

    await acknowledge();
    await waitFor(() => expect(result.current.session.selection.kind).toBe("picker"));
    expect(result.current.location.pathname).toBe("/admin");
    expect(result.current.location.key).not.toBe(sourceKey);
    act(() => retainedChoose(calicut.id));
    expect(scheduled()).toEqual([]);
    act(() => result.current.session.chooseMakerspace(calicut.id));
    expect(scheduled()).toEqual(["/m/calicut/admin/dashboard"]);
    expect(result.current.session.selection.kind).toBe("loading");
    expect(result.current.location.pathname).toBe("/admin");
    await acknowledge();
    await waitFor(() => expect(result.current.session.selected).toBe(calicut.id));
    expect(result.current.location.pathname).toBe("/m/calicut/admin/dashboard");
    expect(stored()).toBe(String(calicut.id));
    expect(scheduled()).toEqual([]);
  });
});

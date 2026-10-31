import { accessToken } from "../../test/accessTokens";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getAccessToken, type StaffAuthUser } from "../../lib/api";
import { fetchMock, jsonResponse, resetSessionTransport } from "../../lib/apiSessionTestHelpers";
import { OrganizationInvitationRedeemPage } from "./OrganizationInvitationRedeemPage";

const member = {
  username: "canonical-member", email_verified: true, role: "member",
  is_superuser: false, must_change_password: false, makerspaces: [],
} satisfies StaffAuthUser;

type Call = { path: string; init: RequestInit; body: Record<string, unknown> | null };
let calls: Call[];
let restored: boolean;
let staffFailures: number;
type RestoreFailure = "refresh rejected" | "refresh network" | "me 500" | "me network";
let restoreFailure: RestoreFailure | null;

beforeEach(() => {
  resetSessionTransport("");
  calls = [];
  restored = false;
  staffFailures = 0;
  restoreFailure = null;
  fetchMock.mockImplementation(async (url, init = {}) => {
    const path = new URL(String(url), "http://localhost").pathname;
    const body = typeof init.body === "string" ? JSON.parse(init.body) as Record<string, unknown> : null;
    calls.push({ path, init, body });
    if (path.endsWith("/auth/refresh")) {
      if (restoreFailure === "refresh network") throw new TypeError("Refresh network failure");
      return jsonResponse(restored && restoreFailure !== "refresh rejected" ? 200 : 401, { access: accessToken("restored-member") });
    }
    if (path.endsWith("/auth/me")) {
      if (restoreFailure === "me network") throw new TypeError("Profile network failure");
      return jsonResponse(restoreFailure === "me 500" ? 500 : 200, member);
    }
    if (path.endsWith("/auth/organization-invitations/redeem/")) {
      return jsonResponse(200, { membership: { id: 7, organization_id: 3 }, user: member });
    }
    if (path.endsWith("/auth/login")) {
      if (body?.surface === "staff" && staffFailures > 0) {
        staffFailures -= 1;
        return jsonResponse(401, { detail: "Incorrect staff password" });
      }
      const staff = body?.surface === "staff";
      return jsonResponse(200, {
        access: staff ? accessToken("new-staff-access", { surface: "staff", staff_scope: "platform" }) : accessToken("member-access"),
        surface: staff ? "staff" : "member", user: member,
      });
    }
    throw new Error(`Unexpected API request: ${path}`);
  });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryData(["member-private-data"], { owner: "member" });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/organization-invitations/redeem/single-use-token"]}>
        <Routes>
          <Route path="/organization-invitations/redeem/:token" element={<OrganizationInvitationRedeemPage />} />
          <Route path="/admin" element={<h1>Staff console entry</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

const loginCalls = () => calls.filter((call) => call.path.endsWith("/auth/login"));
const redeemCalls = () => calls.filter((call) => call.path.endsWith("/organization-invitations/redeem/"));

function enterPassword(value: string) {
  fireEvent.change(screen.getByLabelText("Password"), { target: { value } });
}

async function memberSignInAndRedeem() {
  const username = await screen.findByLabelText("Username or email");
  fireEvent.change(username, { target: { value: "typed-email@example.test" } });
  enterPassword("member-only-password");
  fireEvent.click(screen.getByRole("button", { name: "Sign in and continue" }));
  await screen.findByRole("heading", { name: "Staff sign-in" });
  expect(screen.getByRole("status")).toHaveTextContent("Invitation redeemed");
}

function expectRedeemedMemberBoundary() {
  expect(loginCalls()).toHaveLength(1);
  expect(loginCalls()[0].body).toEqual({
    username: "typed-email@example.test", password: "member-only-password", surface: "member",
  });
  expect(loginCalls()[0].init.credentials).toBe("include");
  expect(redeemCalls()).toHaveLength(1);
  expect(redeemCalls()[0].body).toEqual({ token: "single-use-token" });
  expect(redeemCalls()[0].init.method).toBe("POST");
  expect(new Headers(redeemCalls()[0].init.headers).get("Authorization")).toBe(`Bearer ${accessToken("member-access")}`);
  expect(getAccessToken()).toBe(accessToken("member-access"));
  expect(screen.getByLabelText("Password")).toHaveValue("");
  expect(screen.getByLabelText("Password")).toBeRequired();
  expect(screen.getByLabelText("Username or email")).toHaveValue("canonical-member");
  expect(screen.queryByRole("heading", { name: "Staff console entry" })).not.toBeInTheDocument();
}

describe("organization invitation staff reauthentication", () => {
  it.each<RestoreFailure>(["refresh rejected", "refresh network", "me 500", "me network"])(
    "finishes restoration and offers member sign-in after %s without side effects",
    async (failure) => {
      restored = true;
      restoreFailure = failure;
      const unhandled = vi.fn();
      window.addEventListener("unhandledrejection", unhandled);
      try {
        const client = renderPage();
        const clear = vi.spyOn(client, "clear");
        const main = screen.getByRole("main");
        expect(main.querySelector(".animate-pulse")).toBeInTheDocument();

        expect(await screen.findByRole("button", { name: "Sign in and continue" })).toBeEnabled();
        expect(main.querySelector(".animate-pulse")).not.toBeInTheDocument();
        expect(screen.getByText("Sign in to bind this single-use invitation to your account.")).toBeInTheDocument();
        expect(screen.getByLabelText("Password")).toHaveValue("");
        expect(screen.getByLabelText("Username or email")).toHaveValue("");
        expect(screen.queryByRole("heading", { name: "Staff sign-in" })).not.toBeInTheDocument();
        expect(screen.queryByRole("heading", { name: "Staff console entry" })).not.toBeInTheDocument();
        expect(screen.queryByText("Invitation redeemed")).not.toBeInTheDocument();
        expect(loginCalls()).toEqual([]);
        expect(redeemCalls()).toEqual([]);
        expect(calls.map((call) => call.path.split("/auth/")[1])).toEqual(
          failure.startsWith("refresh") ? ["refresh"] : ["refresh", "me"],
        );
        expect(clear).not.toHaveBeenCalled();
        expect(client.getQueryData(["member-private-data"])).toEqual({ owner: "member" });
        // Do not suppress events; Vitest also reports unhandled promise rejections.
        expect(unhandled).not.toHaveBeenCalled();
      } finally {
        window.removeEventListener("unhandledrejection", unhandled);
      }
    },
  );

  it("redeems once as a member and requires a fresh password before explicit staff login", async () => {
    const client = renderPage();
    await memberSignInAndRedeem();
    expectRedeemedMemberBoundary();
    expect(calls).toHaveLength(3); // refresh, member login, redeem; no role mutation or automatic login.
    expect(client.getQueryData(["member-private-data"])).toEqual({ owner: "member" });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Sign in to staff console" }));
    });
    expect(loginCalls()).toHaveLength(1); // Required empty password prevents reuse of member credentials.

    enterPassword("explicit-staff-password");
    fireEvent.click(screen.getByRole("button", { name: "Sign in to staff console" }));
    await screen.findByRole("heading", { name: "Staff console entry" });
    expect(loginCalls()).toHaveLength(2);
    expect(loginCalls()[1].body).toEqual({
      username: "canonical-member", password: "explicit-staff-password", surface: "staff",
    });
    expect(loginCalls()[1].init.credentials).toBe("include");
    expect(loginCalls()[1].init.method).toBe("POST");
    expect(getAccessToken()).toBe(accessToken("new-staff-access", { surface: "staff", staff_scope: "platform" }));
    expect(client.getQueryCache().getAll()).toEqual([]);
    expect(redeemCalls()).toHaveLength(1);
    expect(calls).toHaveLength(4);
  });

  it("keeps redemption success and cached member data on staff failure, then permits an explicit retry", async () => {
    staffFailures = 1;
    const client = renderPage();
    await memberSignInAndRedeem();
    expectRedeemedMemberBoundary();
    enterPassword("wrong-staff-password");
    fireEvent.click(screen.getByRole("button", { name: "Sign in to staff console" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect staff password");
    expect(screen.getByRole("status")).toHaveTextContent("Invitation redeemed");
    expect(screen.getByRole("heading", { name: "Staff sign-in" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Staff console entry" })).not.toBeInTheDocument();
    expect(getAccessToken()).toBe(accessToken("member-access"));
    expect(client.getQueryData(["member-private-data"])).toEqual({ owner: "member" });
    expect(redeemCalls()).toHaveLength(1);
    expect(calls.filter((call) => call.path.endsWith("/auth/refresh"))).toHaveLength(1);
    expect(loginCalls()[1].body).toEqual({
      username: "canonical-member", password: "wrong-staff-password", surface: "staff",
    });
    expect(loginCalls()[1].init.credentials).toBe("include");

    enterPassword("retried-staff-password");
    fireEvent.click(screen.getByRole("button", { name: "Sign in to staff console" }));
    await screen.findByRole("heading", { name: "Staff console entry" });
    expect(loginCalls()[2].body).toEqual({
      username: "canonical-member", password: "retried-staff-password", surface: "staff",
    });
    expect(loginCalls()[2].init.credentials).toBe("include");
    expect(redeemCalls()).toHaveLength(1);
    expect(getAccessToken()).toBe(accessToken("new-staff-access", { surface: "staff", staff_scope: "platform" }));
    expect(client.getQueryCache().getAll()).toEqual([]);
  });

  it("restores a member session and redeems without silently acquiring a staff token", async () => {
    restored = true;
    const client = renderPage();
    await screen.findByRole("heading", { name: "Staff sign-in" });
    await waitFor(() => expect(redeemCalls()).toHaveLength(1));
    expect(loginCalls()).toEqual([]);
    expect(calls.map((call) => call.path.split("/auth/")[1])).toEqual([
      "refresh", "me", "organization-invitations/redeem/",
    ]);
    expect(new Headers(redeemCalls()[0].init.headers).get("Authorization")).toBe(`Bearer ${accessToken("restored-member")}`);
    expect(redeemCalls()[0].body).toEqual({ token: "single-use-token" });
    expect(getAccessToken()).toBe(accessToken("restored-member"));
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Username or email")).toHaveValue("canonical-member");
    expect(screen.getByRole("status")).toHaveTextContent("Invitation redeemed");
    expect(screen.queryByRole("heading", { name: "Staff console entry" })).not.toBeInTheDocument();
    expect(client.getQueryData(["member-private-data"])).toEqual({ owner: "member" });
  });
});

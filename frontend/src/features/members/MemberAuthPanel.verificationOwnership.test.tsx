import { accessToken } from "../../test/accessTokens";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { publicV1Request, staffRequest } = vi.hoisted(() => ({ publicV1Request: vi.fn(), staffRequest: vi.fn() }));
vi.mock("../../lib/api", async () => ({
  ...await vi.importActual<typeof import("../../lib/api")>("../../lib/api"), publicV1Request, staffRequest,
}));
import { getAccessToken, setAccessToken } from "../../lib/apiSession";
import { enter, held } from "../../test/authOwnership";
import { chooseSignup, mountMember, submitMember } from "../../test/memberOwnershipHarness";

const limited = { access: accessToken("verification-A", { surface: "verification_only" }), surface: "verification_only" };
beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  setAccessToken(accessToken("account-A"));
  publicV1Request.mockReset();
  staffRequest.mockReset();
  publicV1Request.mockImplementation((path: string) => Promise.resolve(path === "/config" ? {} : limited));
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Unexpected network")));
});
afterEach(() => { vi.unstubAllGlobals(); });

async function verificationSession() {
  const view = mountMember();
  submitMember();
  await screen.findByRole("heading", { name: "Verify your email" });
  expect(getAccessToken()).toBe(accessToken("verification-A", { surface: "verification_only" }));
  expect(view.authenticated).not.toHaveBeenCalled();
  enter("Verification code", "123456");
  return view;
}
function verify(resend: boolean) {
  if (resend) fireEvent.click(screen.getByRole("button", { name: "Resend code" }));
  else fireEvent.submit(screen.getByRole("form", { name: "Verify your email" }));
}

describe("verification-only session ownership", () => {
  it("MV01 accepts only its own verification token, then confirms exactly once", async () => {
    staffRequest.mockResolvedValue({});
    const view = await verificationSession();
    verify(false);
    await waitFor(() => expect(view.authenticated).toHaveBeenCalledTimes(1));
    expect(staffRequest).toHaveBeenCalledExactlyOnceWith("/auth/email-verification/confirm", {
      method: "POST", body: JSON.stringify({ code: "123456" }),
    });
    expect(getAccessToken()).toBe(accessToken("verification-A", { surface: "verification_only" }));
  });

  it("MV02 current resend shows its notice, unlocks, and does not authenticate", async () => {
    staffRequest.mockResolvedValue({});
    const view = await verificationSession();
    verify(true);
    await screen.findByText("If the details are valid, a verification email has been sent.");
    expect(staffRequest).toHaveBeenCalledExactlyOnceWith("/auth/email-verification/resend", { method: "POST" });
    expect(view.authenticated).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Verification code")).toBeEnabled();
  });

  it.each([false, true])("MV03 new account cannot dispatch the old verification UI (resend=%s)", async (resend) => {
    const view = await verificationSession();
    act(() => { setAccessToken(accessToken("account-B", { user_id: 2 })); });
    // Intentionally no rerender: a stale event handler must refuse to send as B.
    verify(resend);
    expect(staffRequest).not.toHaveBeenCalled();
    expect(view.authenticated).not.toHaveBeenCalled();
    view.visit("A");
    expect(screen.queryByLabelText("Verification code")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it.each([false, true])("MV04 parsed verification result after a new account is silent (resend=%s)", async (resend) => {
    const response = held<object>();
    staffRequest.mockReturnValue(response.promise);
    const view = await verificationSession();
    verify(resend);
    expect(staffRequest).toHaveBeenCalledTimes(1);
    await act(async () => { response.resolve({}); setAccessToken(accessToken("account-B", { user_id: 2 })); });
    expect(view.authenticated).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(accessToken("account-B", { user_id: 2 }));
    expect(screen.queryByText("If the details are valid, a verification email has been sent.")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([false, true])("MV05 unmounted verification error has no parent callback (resend=%s)", async (resend) => {
    const response = held<object>();
    staffRequest.mockReturnValue(response.promise);
    const view = await verificationSession();
    verify(resend);
    view.unmount();
    await act(async () => { response.reject(new Error("old verification failed")); });
    expect(view.authenticated).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(accessToken("verification-A", { surface: "verification_only" }));
  });

  it("MV06 old verification finally cannot release B's password login", async () => {
    const old = held<object>();
    staffRequest.mockReturnValue(old.promise);
    const view = await verificationSession();
    verify(false);
    view.visit("B");
    const login = held<typeof limited>();
    publicV1Request.mockImplementation((path: string) => path === "/config" ? Promise.resolve({}) : login.promise);
    submitMember();
    await act(async () => { old.reject(new Error("old verification failed")); });
    expect(screen.getByLabelText("Password")).toBeDisabled();
    expect(screen.queryByText("old verification failed")).not.toBeInTheDocument();
    await act(async () => { login.resolve({ access: accessToken("member-B", { user_id: 2 }), surface: "member" }); });
    expect(view.authenticated).toHaveBeenCalledTimes(1);
    expect(getAccessToken()).toBe(accessToken("member-B", { user_id: 2 }));
  });

  it.each([false, true])("MV08 verification A→B→A ignores old errors (resend=%s)", async (resend) => {
    const response = held<object>();
    staffRequest.mockReturnValue(response.promise);
    const view = await verificationSession();
    verify(resend);
    view.visit("B");
    view.visit("A");
    await act(async () => { response.reject(new Error("obsolete verification visit")); });
    expect(screen.queryByText("obsolete verification visit")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Verification code")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(view.authenticated).not.toHaveBeenCalled();
  });

  it("MV07 current verification failure remains retryable without authenticating", async () => {
    staffRequest.mockRejectedValue(new Error("Incorrect code"));
    const view = await verificationSession();
    verify(false);
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect code");
    expect(screen.getByLabelText("Verification code")).toBeEnabled();
    expect(view.authenticated).not.toHaveBeenCalled();
  });
});

describe("member discovery stays separate from input intent", () => {
  it("MC01 typing fourteen email characters does not refetch global config", async () => {
    const discovery = held<object>();
    publicV1Request.mockReturnValue(discovery.promise);
    mountMember();
    await act(async () => { discovery.resolve({}); });
    expect(publicV1Request.mock.calls.filter(([path]) => path === "/config")).toHaveLength(2);
    const initial = publicV1Request.mock.calls.length;
    for (let index = 1; index <= 14; index += 1) enter("Email", "name@example.test".slice(0, index));
    enter("Password", "ordinary-edit");
    expect(publicV1Request.mock.calls).toHaveLength(initial);
  });

  it("MC02 late accounts-off discovery forces login and invalidates pending signup", async () => {
    const discovery = held<object>();
    const signup = held<object>();
    publicV1Request.mockImplementation((path: string) => path === "/config" ? discovery.promise : signup.promise);
    const view = mountMember();
    chooseSignup();
    submitMember(true);
    await act(async () => { discovery.resolve({ member_accounts: { enabled: false } }); });
    expect(screen.getByRole("heading", { name: "Member sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create a member account" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    await act(async () => { signup.resolve({}); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(view.authenticated).not.toHaveBeenCalled();
  });

  it("MC03 unavailable discovery retains the fail-open form; backend still owns enforcement", async () => {
    const discovery = held<object>();
    publicV1Request.mockReturnValue(discovery.promise);
    mountMember();
    await act(async () => { discovery.reject(new Error("discovery unavailable")); });
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create a member account" })).toBeEnabled();
    expect(publicV1Request.mock.calls.every(([path]) => path === "/config")).toBe(true);
  });
});

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { EmptyState, Skeleton } from "../../components/ui";
import {
  fetchMe,
  refreshAccessToken,
  setAccessToken,
  staffRequest,
  type PasswordLoginRequest,
  type PasswordLoginResponse,
  type StaffAuthUser,
} from "../../lib/api";
import { SessionInstallError } from "../../lib/sessionIntent";

import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";

type RedeemResponse = {
  membership: { id: number; organization_id?: number };
  user: StaffAuthUser;
};

export function OrganizationInvitationRedeemPage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const routeVisit = useMemo(() => ({ token }), [token]);
  const restoreAttempted = useRef<typeof routeVisit | null>(null);
  const owner = useAuthActionOwner(token);
  const empty = { user: null as StaffAuthUser | null, restoring: restoreAttempted.current !== routeVisit, credentials: { username: "", password: "" },
    redeemStatus: "idle" as "idle" | "pending" | "success" | "error", redeemError: "", loginPending: false, loginError: "" };
  const [stored, setStored] = useState({ context: owner.context, ...empty });
  const view = stored.context === owner.context ? stored : { context: owner.context, ...empty };
  const { user, restoring, credentials, redeemStatus, redeemError, loginPending, loginError } = view;
  const staffReauthentication = redeemStatus === "success";
  function update(action: AuthAction, patch: Partial<typeof empty>) {
    if (!owner.isCurrent(action)) return;
    setStored((state) => owner.isCurrent(action)
      ? { ...(state.context === action.context ? state : { context: action.context, ...empty }), ...patch } : state);
  }
  function finishAction(action: AuthAction, phase: "restore" | "login" | "redeem") {
    if (!owner.finish(action)) return;
    setStored((state) => state.context !== action.context ? state : {
      ...state,
      ...(phase === "restore" ? { restoring: false } : phase === "login" ? { loginPending: false } :
        { redeemStatus: state.redeemStatus === "pending" ? "idle" : state.redeemStatus }),
    });
  }
  const redeem = useMutation({
    mutationFn: (input: { action: AuthAction; token: string }) => staffRequest<RedeemResponse>("/auth/organization-invitations/redeem/", {
      method: "POST", body: JSON.stringify({ token: input.token }),
    }),
    onSuccess: (response, { action }) => {
      // Redemption is durable even if the later explicit staff sign-in fails.
      update(action, { redeemStatus: "success", credentials: { username: response.user.username, password: "" } });
    },
    onError: (error, { action }) => update(action, { redeemStatus: "error", redeemError: error.message }),
    onSettled: (_data, _error, { action }) => { finishAction(action, "redeem"); },
  });
  const login = useMutation({
    mutationFn: (input: { action: AuthAction; payload: PasswordLoginRequest }) => staffRequest<PasswordLoginResponse<StaffAuthUser>>("/auth/login", {
      method: "POST", credentials: "include", body: JSON.stringify(input.payload),
    }),
    onSuccess: (response, { action, payload }) => {
      if (!owner.install(action, response.access, setAccessToken)) return;
      // Release login before publishing the user that starts automatic redemption.
      owner.finish(action);
      update(action, { user: response.user, credentials: { username: response.user.username, password: "" }, loginPending: false });
      if (payload.surface === "staff") {
        if (!owner.isCurrent(action)) return;
        queryClient.clear();
        if (owner.isCurrent(action)) navigate("/admin");
      }
    },
    onError: (error, { action }) => update(action, { loginError: error.message, loginPending: false,
      ...(error instanceof SessionInstallError ? { credentials: { ...credentials, password: "" } } : {}) }),
    onSettled: (_data, _error, { action }) => { finishAction(action, "login"); },
  });

  useEffect(() => {
    const action = owner.begin();
    if (!action) return;
    // An auth change in this visit requires explicit login. StrictMode replay still
    // starts a restore for its fresh mounted lifetime, even if this visit attempted one.
    restoreAttempted.current = routeVisit;
    update(action, { restoring: true });
    refreshAccessToken()
      .then((refreshed) => owner.isCurrent(action) && refreshed ? fetchMe() : null)
      .then((current) => { update(action, { user: current }); })
      .catch(() => { update(action, { user: null }); })
      .finally(() => { finishAction(action, "restore"); });
  }, [routeVisit]);

  useEffect(() => {
    // The user and status must come from this token visit and epoch, never the previous render's account.
    if (!user || !token || restoring || redeemStatus !== "idle" || !owner.isContextCurrent()) return;
    const action = owner.begin();
    if (!action) return;
    update(action, { redeemStatus: "pending" });
    redeem.mutate({ action, token });
  }, [owner.context, user, token, restoring, redeemStatus]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const action = owner.begin();
    if (!action) return;
    update(action, { loginPending: true, loginError: "" });
    login.mutate({ action, payload: { ...credentials, surface: staffReauthentication ? "staff" : "member" } });
  }
  function editCredentials(patch: Partial<typeof credentials>) {
    if (owner.isPending()) return;
    setStored({ ...view, credentials: { ...credentials, ...patch } });
  }

  return (
    <main className="desk-shell grid min-h-screen place-items-center px-5 py-10">
      <section className="desk-panel w-full max-w-lg p-6" aria-labelledby="invitation-heading">
        <SpaceWorksBadge className="mb-5" />
        <p className="eyebrow text-secondary-ink">Organization invitation</p>
        <h1 className="title-page mt-2" id="invitation-heading">Join an organization</h1>
        {restoring ? <Skeleton className="mt-5 h-32 w-full" /> : null}
        {user && redeemStatus === "pending" ? <p className="mt-5 text-sm text-muted">Redeeming invitation...</p> : null}
        {staffReauthentication ? (
          <div className="mt-5 rounded-xl border border-success bg-success/15 p-4 text-success-ink" role="status">
            <h2 className="title-section">Invitation redeemed</h2>
            <p className="mt-2 text-sm">Your organization access is active. Makerspace actions remain scoped to the organization's linked makerspaces.</p>
          </div>
        ) : null}
        {!restoring && (!user || staffReauthentication) ? (
          <form className="mt-5 grid gap-3" onSubmit={submit}>
            {staffReauthentication ? (
              <>
                <h2 className="title-section">Staff sign-in</h2>
                <p className="text-sm text-muted">Reenter your password to open the staff console for your authorized makerspaces.</p>
              </>
            ) : <p className="text-sm text-muted">Sign in to bind this single-use invitation to your account.</p>}
            <label className="grid gap-1 text-sm font-semibold">Username or email<input className="desk-input" disabled={loginPending} autoComplete="username" required value={credentials.username} onChange={(event) => editCredentials({ username: event.target.value })} /></label>
            <label className="grid gap-1 text-sm font-semibold">Password<input className="desk-input" disabled={loginPending} type="password" autoComplete="current-password" required value={credentials.password} onChange={(event) => editCredentials({ password: event.target.value })} /></label>
            <button className="desk-button-primary" type="submit" disabled={loginPending}>{loginPending ? "Signing in..." : staffReauthentication ? "Sign in to staff console" : "Sign in and continue"}</button>
            {loginError ? <p className="text-sm text-danger" role="alert">{loginError}</p> : null}
          </form>
        ) : null}
        {(redeemStatus === "error") ? <EmptyState title="Invitation unavailable" description={redeemError} action={<Link className="desk-button" to="/">Return to directory</Link>} /> : null}
        {!(redeemStatus === "error") ? <Link className="desk-button mt-5" to="/">Return to directory</Link> : null}
      </section>
    </main>
  );
}

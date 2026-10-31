import { useEffect, useMemo, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { AuthLayout } from "../../components/chrome/AuthLayout";
import { Button, Callout, ErrorText, Field, Input, PasswordInput, buttonClasses } from "../../components/ui";
import {
  publicV1Request,
  setAccessToken,
  staffRequest,
  type PasswordLoginRequest,
  type PasswordLoginResponse,
} from "../../lib/api";
import { useAuthActionOwner } from "../auth/useAuthActionOwner";
import { SocialSignInButtons } from "../auth/SocialSignInButtons";

export function MemberAuthPanel({
  onAuthenticated,
  onCancel,
  makerspaceSlug = "",
}: {
  onAuthenticated: () => void;
  onCancel?: () => void;
  makerspaceSlug?: string;
}) {
  const { pathname } = useLocation();
  const owner = useAuthActionOwner(makerspaceSlug);
  const discoveryOwner = useAuthActionOwner("member-discovery");
  const empty = { mode: "login" as "login" | "signup", displayName: "", email: "", phone: "", password: "",
    pending: false, error: "", notice: "", verificationOnly: false, verificationCode: "" };
  const [stored, setStored] = useState({ context: owner.context, ...empty });
  // Render a fresh visit immediately; an effect reset would briefly expose the old verification UI.
  const view = stored.context === owner.context ? stored : { context: owner.context, ...empty };
  const { mode, displayName, email, phone, password, pending, error, notice, verificationOnly, verificationCode } = view;
  const providerOwnershipScope = useMemo(() => ({}), [owner.context, mode]);
  function update(patch: Partial<typeof empty>) {
    setStored((state) => owner.isContextCurrent()
      ? { ...(state.context === owner.context ? state : { context: owner.context, ...empty }), ...patch } : state);
  }
  function edit(patch: Partial<typeof empty>) { if (!owner.isPending()) update(patch); }
  function changeMode(next: "login" | "signup") {
    if (owner.isPending()) return;
    owner.cancel();
    update({ mode: next, pending: false, error: "", notice: "", password: "" });
  }
  // Absent keys and failed discovery intentionally keep self-service/password available.
  const [config, setConfig] = useState({ context: discoveryOwner.context, accounts: true, password: true });
  const selfServeAccounts = config.context === discoveryOwner.context ? config.accounts : true;
  const passwordLogin = config.context === discoveryOwner.context ? config.password : true;
  useEffect(() => {
    let active = true;
    publicV1Request<{ member_accounts?: { enabled: boolean }; self_registration?: { enabled: boolean };
      password_login?: { enabled: boolean } }>("/config").then((result) => {
      if (!active || !discoveryOwner.isContextCurrent()) return;
      const accounts = result.member_accounts?.enabled !== false && result.self_registration?.enabled !== false;
      setConfig({ context: discoveryOwner.context, accounts, password: result.password_login?.enabled !== false });
    }).catch(() => {
      if (active && discoveryOwner.isContextCurrent()) setConfig({ context: discoveryOwner.context, accounts: true, password: true });
    });
    return () => { active = false; };
  }, [discoveryOwner.context]);
  useEffect(() => {
    if (!selfServeAccounts && mode === "signup") {
      owner.cancel();
      update({ mode: "login", pending: false, error: "", password: "" });
    }
  }, [selfServeAccounts, mode]);

  const submit = async () => {
    const action = owner.begin();
    if (!action) return;
    const payload = { display_name: displayName, email, phone, password, website: "" };
    update({ pending: true, error: "", notice: "" });
    try {
      if (mode === "signup") {
        await publicV1Request("/auth/member-sign-up", { method: "POST", body: JSON.stringify(payload) });
        if (!owner.isCurrent(action)) return;
        update({ mode: "login", password: "", pending: false, notice: "Check your email to verify the new account, then sign in." });
      } else {
        const request = { username: email, password, surface: "member" } satisfies PasswordLoginRequest;
        const result = await publicV1Request<PasswordLoginResponse>("/auth/login", {
          method: "POST", credentials: "include", body: JSON.stringify(request),
        });
        if (!owner.install(action, result.access, setAccessToken)) return;
        if (!owner.isCurrent(action)) return;
        update({ password: "", pending: false, verificationOnly: result.surface === "verification_only",
          notice: result.surface === "verification_only" ? "Enter the verification code sent to your email." : "" });
        if (result.surface !== "verification_only" && owner.isCurrent(action)) onAuthenticated();
      }
    } catch (nextError) {
      if (owner.isCurrent(action)) update({ pending: false, error: nextError instanceof Error ? nextError.message : "Unable to continue." });
    } finally {
      if (owner.finish(action)) setStored((state) => state.context === action.context ? { ...state, pending: false } : state);
    }
  };

  const verify = async (resend: boolean) => {
    if (!verificationOnly) return;
    const action = owner.begin();
    if (!action) return;
    update({ pending: true, error: "" });
    try {
      await staffRequest(`/auth/email-verification/${resend ? "resend" : "confirm"}`, {
        method: "POST", ...(resend ? {} : { body: JSON.stringify({ code: verificationCode }) }),
      });
      if (!owner.isCurrent(action)) return;
      if (resend) update({ pending: false, notice: "If the details are valid, a verification email has been sent." });
      else { update({ pending: false, password: "" }); if (owner.isCurrent(action)) onAuthenticated(); }
    } catch (nextError) {
      if (owner.isCurrent(action)) update({ pending: false, error: nextError instanceof Error ? nextError.message : resend ? "Unable to resend the code." : "Unable to verify email." });
    } finally {
      if (owner.finish(action)) setStored((state) => state.context === action.context ? { ...state, pending: false } : state);
    }
  };

  if (verificationOnly) {
    return (
      <AuthLayout
        title="Verify your email"
        description="This session can only verify the address until email ownership is confirmed."
      >
        <form
          className="flex flex-col gap-4"
          aria-label="Verify your email"
          onSubmit={(event) => { event.preventDefault(); void verify(false); }}
        >
          <Field label="Verification code" id="member-verification-code">
            <Input
              disabled={pending}
              inputMode="numeric"
              autoComplete="one-time-code"
              value={verificationCode}
              onChange={(event) => edit({ verificationCode: event.target.value })}
              required
            />
          </Field>
          {notice ? <Callout tone="success" role="status">{notice}</Callout> : null}
          <ErrorText message={error} />
          <Button variant="primary" type="submit" fullWidth loading={pending}>
            Verify email
          </Button>
          <Button variant="secondary" fullWidth disabled={pending} onClick={() => { void verify(true); }}>
            Resend code
          </Button>
        </form>
      </AuthLayout>
    );
  }

  const showPassword = passwordLogin || mode === "signup";
  return (
    <AuthLayout
      kicker="Member area"
      title={mode === "login" ? "Member sign in" : "Create a member account"}
      description={mode === "signup"
        ? "Use one global account across every makerspace you join."
        : passwordLogin
          ? "Sign in to manage memberships, waivers, visits, and payments."
          : "This space signs members in through an identity provider."}
    >
      <form
        className="flex flex-col gap-4"
        aria-label={mode === "login" ? "Member sign in" : "Create a member account"}
        onSubmit={(event) => { event.preventDefault(); void submit(); }}
      >
        {mode === "signup" ? (
          <>
            <Field label="Name" id="member-name">
              <Input disabled={pending} autoComplete="name" value={displayName} onChange={(event) => edit({ displayName: event.target.value })} required />
            </Field>
            <Field label="Phone" optional id="member-phone">
              <Input disabled={pending} autoComplete="tel" value={phone} onChange={(event) => edit({ phone: event.target.value })} />
            </Field>
          </>
        ) : null}
        <Field label="Email" id="member-email">
          <Input disabled={pending} type="email" autoComplete="email" value={email} onChange={(event) => edit({ email: event.target.value })} required />
        </Field>
        {/* Sign-up still needs a password: it sets the one it cannot be used with yet, so the
            account stays recoverable if the switch is ever turned back on. */}
        {showPassword ? (
          <Field label="Password" id="member-password">
            <PasswordInput disabled={pending} autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => edit({ password: event.target.value })} required />
          </Field>
        ) : null}
        {showPassword && mode === "login" ? (
          <Link className={buttonClasses({ variant: "quiet", size: "sm", className: "-mt-2 self-start" })} to={`/reset-password?next=${encodeURIComponent(pathname)}`}>Forgot password?</Link>
        ) : null}
        {notice ? <Callout tone="success" role="status">{notice}</Callout> : null}
        <ErrorText message={error} />
        {showPassword ? (
          <Button variant="primary" type="submit" fullWidth loading={pending}>
            {mode === "login" ? "Sign in" : "Create account"}
          </Button>
        ) : null}
        {selfServeAccounts ? (
          <Button variant="secondary" fullWidth disabled={pending} onClick={() => changeMode(mode === "login" ? "signup" : "login")}>
            {mode === "login" ? "Create a member account" : "Back to sign in"}
          </Button>
        ) : (
          <p className="text-center text-body-ui text-ink-muted">
            This space does not run self sign-up. Ask a staff member to add you.
          </p>
        )}
        {onCancel ? (
          <Button variant="quiet" fullWidth onClick={() => { owner.cancel(); update({ pending: false }); onCancel(); }}>
            Back
          </Button>
        ) : null}
        <SocialSignInButtons
          disabled={pending}
          ownershipScope={providerOwnershipScope}
          isHostCurrent={owner.isIntentCurrent}
          surface="member"
          email={email}
          makerspaceSlug={makerspaceSlug}
          onSuccess={(result) => {
            // This closure belongs to the rendered intent; provider guards never borrow a later callback.
            if (!owner.isIntentCurrent()) return;
            const action = owner.begin();
            if (!action) return;
            try {
              if (!owner.install(action, result.access, setAccessToken)) return;
              update({ password: "", pending: false });
              if (owner.isCurrent(action)) onAuthenticated();
            } catch (nextError) {
              if (owner.isCurrent(action)) update({ password: "", pending: false,
                error: nextError instanceof Error ? nextError.message : "Unable to continue." });
            } finally {
              if (owner.finish(action)) setStored((state) => state.context === action.context ? { ...state, pending: false } : state);
            }
          }}
        />
      </form>
    </AuthLayout>
  );
}

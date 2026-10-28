import { useEffect, useState } from "react";
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
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [verificationOnly, setVerificationOnly] = useState(false);
  const [verificationCode, setVerificationCode] = useState("");
  // Each of these appears in the public config only when it has been switched off, so
  // an absent key — and a failed request — mean available.
  const [selfServeAccounts, setSelfServeAccounts] = useState(true);
  const [passwordLogin, setPasswordLogin] = useState(true);

  useEffect(() => {
    publicV1Request<{
      member_accounts?: { enabled: boolean };
      self_registration?: { enabled: boolean };
      password_login?: { enabled: boolean };
    }>("/config")
      .then((result) => {
        setSelfServeAccounts(
          result.member_accounts?.enabled !== false &&
            result.self_registration?.enabled !== false,
        );
        setPasswordLogin(result.password_login?.enabled !== false);
      })
      .catch(() => {
        setSelfServeAccounts(true);
        setPasswordLogin(true);
      });
  }, []);

  useEffect(() => {
    if (!selfServeAccounts) setMode("login");
  }, [selfServeAccounts]);

  const submit = async () => {
    setPending(true);
    setError("");
    setNotice("");
    try {
      if (mode === "signup") {
        await publicV1Request("/auth/member-sign-up", {
          method: "POST",
          body: JSON.stringify({ display_name: displayName, email, phone, password, website: "" }),
        });
        setMode("login");
        setNotice("Check your email to verify the new account, then sign in.");
      } else {
        const request = {
          username: email,
          password,
          surface: "member",
        } satisfies PasswordLoginRequest;
        const result = await publicV1Request<PasswordLoginResponse>("/auth/login", {
          method: "POST",
          credentials: "include",
          body: JSON.stringify(request),
        });
        setAccessToken(result.access);
        if (result.surface === "verification_only") {
          setVerificationOnly(true);
          setNotice("Enter the verification code sent to your email.");
        } else {
          onAuthenticated();
        }
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to continue.");
    } finally {
      setPending(false);
    }
  };

  const confirmVerification = async () => {
    setPending(true);
    setError("");
    try {
      await staffRequest("/auth/email-verification/confirm", {
        method: "POST",
        body: JSON.stringify({ code: verificationCode }),
      });
      onAuthenticated();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to verify email.");
    } finally {
      setPending(false);
    }
  };

  const resendVerification = async () => {
    setPending(true);
    setError("");
    try {
      await staffRequest("/auth/email-verification/resend", { method: "POST" });
      setNotice("If the details are valid, a verification email has been sent.");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Unable to resend the code.");
    } finally {
      setPending(false);
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
          onSubmit={(event) => { event.preventDefault(); void confirmVerification(); }}
        >
          <Field label="Verification code" id="member-verification-code">
            <Input
              inputMode="numeric"
              autoComplete="one-time-code"
              value={verificationCode}
              onChange={(event) => setVerificationCode(event.target.value)}
              required
            />
          </Field>
          {notice ? <Callout tone="success" role="status">{notice}</Callout> : null}
          <ErrorText message={error} />
          <Button variant="primary" type="submit" fullWidth loading={pending}>
            Verify email
          </Button>
          <Button variant="secondary" fullWidth disabled={pending} onClick={() => { void resendVerification(); }}>
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
              <Input autoComplete="name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required />
            </Field>
            <Field label="Phone" optional id="member-phone">
              <Input autoComplete="tel" value={phone} onChange={(event) => setPhone(event.target.value)} />
            </Field>
          </>
        ) : null}
        <Field label="Email" id="member-email">
          <Input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </Field>
        {/* Sign-up still needs a password: it sets the one it cannot be used with yet, so the
            account stays recoverable if the switch is ever turned back on. */}
        {showPassword ? (
          <Field label="Password" id="member-password">
            <PasswordInput autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(event) => setPassword(event.target.value)} required />
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
          <Button variant="secondary" fullWidth onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(""); }}>
            {mode === "login" ? "Create a member account" : "Back to sign in"}
          </Button>
        ) : (
          <p className="text-center text-body-ui text-ink-muted">
            This space does not run self sign-up. Ask a staff member to add you.
          </p>
        )}
        {onCancel ? (
          <Button variant="quiet" fullWidth onClick={onCancel}>
            Back
          </Button>
        ) : null}
        <SocialSignInButtons
          surface="member"
          email={email}
          makerspaceSlug={makerspaceSlug}
          onSuccess={(result) => {
            setAccessToken(result.access);
            onAuthenticated();
          }}
        />
      </form>
    </AuthLayout>
  );
}

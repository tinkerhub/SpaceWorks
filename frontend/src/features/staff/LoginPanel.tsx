import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { publicV1Request } from "../../lib/api";
import { AuthLayout } from "../../components/chrome/AuthLayout";
import { Button, Callout, ErrorText, Field, Input, PasswordInput, buttonClasses } from "../../components/ui";
import { SocialSignInButtons } from "../auth/SocialSignInButtons";
import type { SocialLoginResult } from "../auth/socialSdk";

export function LoginPanel({
  error,
  notice,
  guestOnly,
  isPending,
  onSubmit,
  onSocialSuccess,
}: {
  error?: string;
  notice?: string;
  guestOnly: boolean;
  isPending: boolean;
  onSubmit: (payload: { username: string; password: string }) => void;
  onSocialSuccess?: (result: SocialLoginResult) => void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [emailEnabled, setEmailEnabled] = useState(false);
  // Present in the config only when password sign-in has been switched off, so an
  // absent key — and a failed request — mean it is available.
  const [passwordLogin, setPasswordLogin] = useState(true);
  const providerOwnershipScope = useMemo(() => ({}), [onSocialSuccess]);

  useEffect(() => {
    let active = true;
    publicV1Request<{ email_enabled: boolean; password_login?: { enabled: boolean } }>(
      "/config",
    )
      .then((config) => {
        if (active) {
          setEmailEnabled(config.email_enabled === true);
          setPasswordLogin(config.password_login?.enabled !== false);
        }
      })
      .catch(() => {
        if (active) {
          setEmailEnabled(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <AuthLayout
      kicker={guestOnly ? "Guest admin desk" : "Space Manager desk"}
      title="Sign in"
      description={passwordLogin
        ? "Use your staff account to manage requests, inventory, and handovers."
        : "This deployment signs staff in through an identity provider."}
    >
      <form
        className="flex flex-col gap-4"
        aria-label="Staff sign in"
        onSubmit={(event) => {
          event.preventDefault();
          if (isPending) return;
          onSubmit({ username, password });
        }}
      >
        {passwordLogin ? (
          <>
            <Field label="Username" id="staff-username">
              <Input
                name="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </Field>
            <Field label="Password" id="staff-password">
              <PasswordInput
                name="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
          </>
        ) : null}
        {notice ? <Callout tone="warning" role="alert">{notice}</Callout> : null}
        <ErrorText message={error} />
        {passwordLogin ? (
          <Button variant="primary" type="submit" fullWidth loading={isPending} loadingLabel="Signing in…">
            Sign in
          </Button>
        ) : null}
        {emailEnabled && passwordLogin ? (
          <Link className={buttonClasses({ variant: "quiet", fullWidth: true })} to="/reset-password">
            Forgot password?
          </Link>
        ) : null}
        {onSocialSuccess ? (
          <SocialSignInButtons
            surface="staff"
            onSuccess={onSocialSuccess}
            ownershipScope={providerOwnershipScope}
            disabled={isPending}
          />
        ) : null}
      </form>
    </AuthLayout>
  );
}

import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { AuthLayout } from "../../components/chrome/AuthLayout";
import { Button, Callout, ErrorText, Field, Input, buttonClasses } from "../../components/ui";
import { NewPasswordFields } from "./NewPasswordFields";
import {
  CONFIRM_FAILURE_MESSAGE,
  RESEND_COOLDOWN_SECONDS,
  confirmOtpPasswordReset,
  isRecoveryUnavailable,
  requestPasswordReset,
  signInPath,
} from "./passwordRecovery";
import { useAuthActionOwner, type AuthAction } from "./useAuthActionOwner";

type RecoveryStep = "request" | "confirm" | "success" | "unavailable";
const emptyView = {
  step: "request" as RecoveryStep,
  confirmedEmail: "", code: "", newPassword: "", confirmPassword: "",
  acknowledgement: "", error: "", pending: false, cooldown: 0,
};

export function PasswordRecoveryFlow() {
  const signInHref = signInPath(useLocation().search);
  const [email, setEmail] = useState("");
  const owner = useAuthActionOwner(email);
  const context = owner.context;
  const [storedView, setView] = useState({ context, ...emptyView });
  // A different email renders a fresh request immediately, even before any effects.
  const view = storedView.context === context ? storedView : { context, ...emptyView };
  const { step, code, newPassword, confirmPassword, acknowledgement, error, pending, cooldown } = view;
  function updateView(patch: Partial<typeof emptyView>, action?: AuthAction) {
    const isCurrent = () => action ? owner.isCurrent(action) : owner.isContextCurrent();
    if (!isCurrent()) return;
    setView((state) => isCurrent()
      ? { ...(state.context === context ? state : { context, ...emptyView }), ...patch }
      : state);
  }

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      if (!owner.isContextCurrent(context)) return;
      setView((state) => owner.isContextCurrent(context) && state.context === context
        ? { ...state, cooldown: Math.max(0, state.cooldown - 1) } : state);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [context, cooldown > 0]);

  const requestCode = async (isResend: boolean) => {
    if (isResend ? step !== "confirm" || cooldown > 0 || view.confirmedEmail !== email : step !== "request") return;
    const action = owner.begin();
    if (!action) return;
    const requestedEmail = isResend ? view.confirmedEmail : email;
    updateView({ pending: true, error: "" }, action);
    try {
      const result = await requestPasswordReset({ email: requestedEmail });
      updateView({
        confirmedEmail: requestedEmail, acknowledgement: result.detail,
        cooldown: RESEND_COOLDOWN_SECONDS, step: "confirm",
      }, action);
    } catch (requestError) {
      if (isRecoveryUnavailable(requestError)) {
        updateView({ step: "unavailable" }, action);
      } else {
        updateView({ error: "Unable to request password recovery. Please try again." }, action);
      }
    } finally {
      updateView({ pending: false }, action);
      owner.finish(action);
    }
  };

  const submitConfirmation = async () => {
    if (step !== "confirm" || view.confirmedEmail !== email) return;
    const action = owner.begin();
    if (!action) return;
    const payload = { email: view.confirmedEmail, code, new_password: newPassword };
    updateView({ pending: true, error: "" }, action);
    try {
      await confirmOtpPasswordReset(payload);
      updateView({ step: "success" }, action);
    } catch {
      // All server rejections intentionally share one message. Showing password-policy
      // details only after a valid OTP would recreate an account-existence oracle.
      updateView({ error: CONFIRM_FAILURE_MESSAGE }, action);
    } finally {
      updateView({ pending: false }, action);
      owner.finish(action);
    }
  };

  const canConfirm = /^\d{6}$/.test(code)
    && newPassword.length >= 8
    && newPassword === confirmPassword
    && !pending;

  const backToSignIn = <Link className={buttonClasses({ variant: "quiet", fullWidth: true })} to={signInHref}>Back to sign in</Link>;

  if (step === "unavailable") {
    return (
      <AuthLayout kicker="Account access" title="Password recovery unavailable">
        <div className="flex flex-col gap-4">
          <Callout tone="warning" role="alert">
            Password recovery is unavailable on this deployment — contact your makerspace staff
          </Callout>
          {backToSignIn}
        </div>
      </AuthLayout>
    );
  }

  if (step === "success") {
    return (
      <AuthLayout kicker="Account access" title="Password updated" description="Your password has been updated. You can now sign in.">
        <Link className={buttonClasses({ variant: "primary", fullWidth: true })} to={signInHref}>Go to sign in</Link>
      </AuthLayout>
    );
  }

  if (step === "request") {
    return (
      <AuthLayout kicker="Account access" title="Reset password" description="Enter your account email to request a six-digit recovery code.">
        <form className="flex flex-col gap-4" aria-label="Reset password" onSubmit={(event) => { event.preventDefault(); void requestCode(false); }}>
          <Field id="recovery-email" label="Email">
            <Input
              name="email"
              autoComplete="email"
              type="email"
              required
              value={email}
              onChange={(event) => { if (owner.isContextCurrent()) setEmail(event.target.value); }}
            />
          </Field>
          <ErrorText message={error} />
          <Button variant="primary" type="submit" fullWidth loading={pending}>
            Request recovery code
          </Button>
          {backToSignIn}
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout kicker="Account access" title="Enter your recovery code" description={acknowledgement}>
      <form className="flex flex-col gap-4" aria-label="Enter your recovery code" onSubmit={(event) => { event.preventDefault(); if (canConfirm) void submitConfirmation(); }}>
        <p className="text-caption text-ink-muted">
          Email delivery runs on a schedule and may take a few minutes.
        </p>
        <Field id="recovery-code" label="Six-digit code">
          <Input
            className="font-mono tracking-[0.3em]"
            autoComplete="one-time-code"
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            required
            value={code}
            onChange={(event) => updateView({ code: event.target.value.replace(/\D/g, "") })}
          />
        </Field>
        <NewPasswordFields
          idPrefix="otp-reset"
          newPassword={newPassword}
          confirmPassword={confirmPassword}
          onNewPasswordChange={(value) => updateView({ newPassword: value })}
          onConfirmPasswordChange={(value) => updateView({ confirmPassword: value })}
        />
        <ErrorText message={error} />
        <Button variant="primary" type="submit" fullWidth disabled={!canConfirm} loading={pending}>
          Update password
        </Button>
        <Button
          variant="secondary"
          fullWidth
          disabled={pending || cooldown > 0}
          onClick={() => void requestCode(true)}
        >
          {cooldown > 0 ? `Request another code in ${cooldown}s` : "Request another code"}
        </Button>
      </form>
    </AuthLayout>
  );
}

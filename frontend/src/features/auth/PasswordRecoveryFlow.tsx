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

type RecoveryStep = "request" | "confirm" | "success" | "unavailable";

export function PasswordRecoveryFlow() {
  const signInHref = signInPath(useLocation().search);
  const [step, setStep] = useState<RecoveryStep>("request");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [acknowledgement, setAcknowledgement] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((seconds) => Math.max(0, seconds - 1));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [cooldown > 0]);

  const requestCode = async (isResend: boolean) => {
    setPending(true);
    setError("");
    try {
      const result = await requestPasswordReset({ email });
      setAcknowledgement(result.detail);
      setCooldown(RESEND_COOLDOWN_SECONDS);
      if (!isResend) setStep("confirm");
    } catch (requestError) {
      if (isRecoveryUnavailable(requestError)) {
        setStep("unavailable");
      } else {
        setError("Unable to request password recovery. Please try again.");
      }
    } finally {
      setPending(false);
    }
  };

  const submitConfirmation = async () => {
    setPending(true);
    setError("");
    try {
      await confirmOtpPasswordReset({ email, code, new_password: newPassword });
      setStep("success");
    } catch {
      // All server rejections intentionally share one message. Showing password-policy
      // details only after a valid OTP would recreate an account-existence oracle.
      setError(CONFIRM_FAILURE_MESSAGE);
    } finally {
      setPending(false);
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
              onChange={(event) => setEmail(event.target.value)}
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
            onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))}
          />
        </Field>
        <NewPasswordFields
          idPrefix="otp-reset"
          newPassword={newPassword}
          confirmPassword={confirmPassword}
          onNewPasswordChange={setNewPassword}
          onConfirmPasswordChange={setConfirmPassword}
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

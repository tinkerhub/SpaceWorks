import { useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { AuthLayout } from "../../components/chrome/AuthLayout";
import { Button, ErrorText, buttonClasses } from "../../components/ui";
import { NewPasswordFields } from "./NewPasswordFields";
import { CONFIRM_FAILURE_MESSAGE, confirmLegacyPasswordReset, signInPath } from "./passwordRecovery";

export function LegacyPasswordResetForm({ uid, token }: { uid: string; token: string }) {
  const signInHref = signInPath(useLocation().search);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState(false);
  const canSubmit = newPassword.length >= 8
    && newPassword === confirmPassword
    && !pending;

  const submit = async () => {
    setPending(true);
    setError("");
    try {
      await confirmLegacyPasswordReset({ uid, token, new_password: newPassword });
      setUpdated(true);
    } catch {
      setError(CONFIRM_FAILURE_MESSAGE);
    } finally {
      setPending(false);
    }
  };

  if (updated) {
    return (
      <AuthLayout kicker="Account access" title="Password updated" description="Your password has been updated. You can now sign in.">
        <Link className={buttonClasses({ variant: "primary", fullWidth: true })} to={signInHref}>Go to sign in</Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout kicker="Account access" title="Set a new password" description="Choose a password you have not used here before.">
      <form
        className="flex flex-col gap-4"
        aria-label="Set a new password"
        onSubmit={(event) => { event.preventDefault(); if (canSubmit) void submit(); }}
      >
        <NewPasswordFields
          idPrefix="legacy-reset"
          newPassword={newPassword}
          confirmPassword={confirmPassword}
          onNewPasswordChange={setNewPassword}
          onConfirmPasswordChange={setConfirmPassword}
        />
        <ErrorText message={error} />
        <Button variant="primary" type="submit" fullWidth disabled={!canSubmit} loading={pending}>
          Update password
        </Button>
      </form>
    </AuthLayout>
  );
}

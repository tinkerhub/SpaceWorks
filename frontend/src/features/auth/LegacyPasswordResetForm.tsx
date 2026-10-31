import { useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { AuthLayout } from "../../components/chrome/AuthLayout";
import { Button, ErrorText, buttonClasses } from "../../components/ui";
import { NewPasswordFields } from "./NewPasswordFields";
import { CONFIRM_FAILURE_MESSAGE, confirmLegacyPasswordReset, signInPath } from "./passwordRecovery";
import { useAuthActionOwner, type AuthAction } from "./useAuthActionOwner";

const emptyView = { newPassword: "", confirmPassword: "", pending: false, error: "", updated: false };

export function LegacyPasswordResetForm({ uid, token }: { uid: string; token: string }) {
  const signInHref = signInPath(useLocation().search);
  const owner = useAuthActionOwner(JSON.stringify([uid, token]));
  const [storedView, setView] = useState({ context: owner.context, ...emptyView });
  // Context identity also resets direct prop changes and A → B → A visits.
  const view = storedView.context === owner.context ? storedView : { context: owner.context, ...emptyView };
  const { newPassword, confirmPassword, pending, error, updated } = view;
  function updateView(patch: Partial<typeof emptyView>, action?: AuthAction) {
    const isCurrent = () => action ? owner.isCurrent(action) : owner.isContextCurrent();
    if (!isCurrent()) return;
    setView((state) => isCurrent()
      ? { ...(state.context === owner.context ? state : { context: owner.context, ...emptyView }), ...patch }
      : state);
  }
  const canSubmit = newPassword.length >= 8
    && newPassword === confirmPassword
    && !pending;

  const submit = async () => {
    const action = owner.begin();
    if (!action) return;
    const payload = { uid, token, new_password: newPassword };
    updateView({ pending: true, error: "" }, action);
    try {
      await confirmLegacyPasswordReset(payload);
      updateView({ updated: true }, action);
    } catch {
      updateView({ error: CONFIRM_FAILURE_MESSAGE }, action);
    } finally {
      updateView({ pending: false }, action);
      owner.finish(action);
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
          onNewPasswordChange={(value) => updateView({ newPassword: value })}
          onConfirmPasswordChange={(value) => updateView({ confirmPassword: value })}
        />
        <ErrorText message={error} />
        <Button variant="primary" type="submit" fullWidth disabled={!canSubmit} loading={pending}>
          Update password
        </Button>
      </form>
    </AuthLayout>
  );
}

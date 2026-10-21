import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, ErrorText, Field, PasswordInput, buttonClasses, useToast } from "../../components/ui";
import { cn } from "../../lib/cn";
import { setAccessToken, StructuredApiError } from "../../lib/api";

export type ChangePasswordResponse = { detail: string; access?: string | null };

type ChangePasswordFormProps = {
  username: string;
  request: (path: string, init: RequestInit) => Promise<ChangePasswordResponse>;
  onChanged: () => void;
  submitLabel?: string;
  /** Stretch the submit button (auth layouts). Otherwise it sizes to its label from 640px. */
  fullWidth?: boolean;
};

// The backend reports field errors as a string or a list of strings per field.
function fieldMessage(error: unknown, field: string): string | null {
  if (!(error instanceof StructuredApiError)) return null;
  const value = error.body[field];
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.filter((item) => typeof item === "string").join(" ") || null;
  return null;
}

function generalMessage(error: unknown): string | null {
  if (!error) return null;
  if (error instanceof StructuredApiError && error.status === 429) {
    return "Too many attempts. Wait a minute and try again.";
  }
  if (fieldMessage(error, "current_password") || fieldMessage(error, "new_password")) return null;
  return error instanceof Error ? error.message : "Unable to update the password.";
}

// `password_not_set`: an account created through a social or identity-provider sign-in has
// no password to confirm, so the only way to set one is the emailed recovery flow. DRF sends
// the field message without its code, so the message itself is the fallback signal.
function passwordNotSet(error: unknown): boolean {
  if (!(error instanceof StructuredApiError)) return false;
  if (error.code === "password_not_set") return true;
  return (fieldMessage(error, "current_password") ?? "").startsWith("This account has no password yet");
}

// Field errors from the server are announced (role="alert") as well as described.
function announced(message: string | null) {
  return message ? <span role="alert">{message}</span> : undefined;
}

// One change-password form for every surface. A successful change revokes every outstanding
// refresh token server-side; when the server re-issues this browser's session it returns a
// fresh access token (and sets the new refresh cookie), which must replace the dead one. The API
// is cross-origin in production, so the request must include credentials or the browser drops
// that Set-Cookie and the next refresh fails with the revoked cookie.
export function ChangePasswordForm({ username, request, onChanged, submitLabel = "Update password", fullWidth = false }: ChangePasswordFormProps) {
  const { showToast } = useToast();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      request("/auth/change-password", {
        method: "POST",
        credentials: "include",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      }),
    onSuccess: (data) => {
      if (data?.access) setAccessToken(data.access);
      setCurrentPassword("");
      setNewPassword("");
      setConfirm("");
      showToast("Password updated", { tone: "success" });
      onChanged();
    },
    onError: () => showToast("Password not updated", { tone: "error" }),
  });
  const mismatch = confirm.length > 0 && newPassword !== confirm;
  const unchanged = newPassword.length > 0 && newPassword === currentPassword;
  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length > 0 &&
    confirm.length > 0 &&
    confirm === newPassword &&
    !unchanged &&
    !mutation.isPending;
  const currentError = fieldMessage(mutation.error, "current_password");
  const newError = fieldMessage(mutation.error, "new_password");
  const otherError = generalMessage(mutation.error);
  const noPassword = passwordNotSet(mutation.error);

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSubmit) mutation.mutate();
      }}
    >
      <input
        aria-label="Username"
        className="sr-only"
        type="text"
        autoComplete="username"
        value={username}
        readOnly
        tabIndex={-1}
        aria-hidden="true"
      />
      <Field label="Current password" error={announced(currentError)}>
        <PasswordInput
          autoComplete="current-password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
        />
      </Field>
      {noPassword ? (
        <a className={buttonClasses({ variant: "quiet", size: "sm", className: "-mt-2 self-start" })} href="/reset-password">
          Set a password by email
        </a>
      ) : null}
      <Field
        label="New password"
        error={announced(unchanged ? "New password must be different." : newError)}
      >
        <PasswordInput
          autoComplete="new-password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
        />
      </Field>
      <Field label="Confirm new password" error={announced(mismatch ? "Passwords do not match." : null)}>
        <PasswordInput
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
        />
      </Field>
      <ErrorText message={otherError} />
      <Button
        variant="primary"
        type="submit"
        disabled={!canSubmit}
        loading={mutation.isPending}
        loadingLabel="Updating…"
        className={cn(fullWidth ? "w-full" : "w-full sm:w-auto sm:self-start")}
      >
        {submitLabel}
      </Button>
    </form>
  );
}

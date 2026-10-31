import { useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, ErrorText, Field, PasswordInput, buttonClasses, useToast } from "../../components/ui";
import { cn } from "../../lib/cn";
import { setAccessToken, StructuredApiError } from "../../lib/api";

import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";

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
  const owner = useAuthActionOwner(username);
  const emptyCredentials = { currentPassword: "", newPassword: "", confirm: "" };
  const [storedCredentials, setCredentials] = useState({ context: owner.context, ...emptyCredentials });
  // Masked inputs must also belong to this identity, immediately on the first render.
  const credentials = storedCredentials.context === owner.context ? storedCredentials : { context: owner.context, ...emptyCredentials };
  const { currentPassword, newPassword, confirm } = credentials;
  function editCredentials(patch: Partial<typeof emptyCredentials>) {
    setCredentials((state) => owner.isContextCurrent()
      ? { ...(state.context === owner.context ? state : { context: owner.context, ...emptyCredentials }), ...patch } : state);
  }
  const [status, setStatus] = useState<{ context: typeof owner.context; pending: boolean; error: unknown }>();
  const pending = status?.context === owner.context && status.pending;
  const error = status?.context === owner.context ? status.error : null;
  const mutation = useMutation({
    mutationFn: ({ payload }: { owner: AuthAction; payload: { current_password: string; new_password: string } }) =>
      request("/auth/change-password", {
        method: "POST", credentials: "include", body: JSON.stringify(payload),
      }),
    onSuccess: (data, input) => {
      if (!owner.isCurrent(input.owner)) return;
      try {
        if (data?.access && !owner.install(input.owner, data.access, setAccessToken)) return;
      } catch {
        if (!owner.isCurrent(input.owner)) return;
        setCredentials({ context: input.owner.context, ...emptyCredentials });
        setStatus({ context: input.owner.context, pending: false,
          error: new Error("Password updated; sign in again.") });
        return;
      }
      if (!owner.isCurrent(input.owner)) return;
      setCredentials({ context: input.owner.context, ...emptyCredentials });
      setStatus({ context: input.owner.context, pending: false, error: null });
      if (!owner.isCurrent(input.owner)) return;
      showToast("Password updated", { tone: "success" });
      if (owner.isCurrent(input.owner)) onChanged();
    },
    onError: (error, input) => {
      if (!owner.isCurrent(input.owner)) return;
      setStatus({ context: input.owner.context, pending: false, error });
      if (owner.isCurrent(input.owner)) showToast("Password not updated", { tone: "error" });
    },
    onSettled: (_data, _error, input) => {
      if (owner.finish(input.owner)) setStatus((state) => state?.context === input.owner.context ? { ...state, pending: false } : state);
    },
  });
  const mismatch = confirm.length > 0 && newPassword !== confirm;
  const unchanged = newPassword.length > 0 && newPassword === currentPassword;
  const canSubmit =
    currentPassword.length > 0 &&
    newPassword.length > 0 &&
    confirm.length > 0 &&
    confirm === newPassword &&
    !unchanged &&
    !pending;
  const currentError = fieldMessage(error, "current_password");
  const newError = fieldMessage(error, "new_password");
  const otherError = generalMessage(error);
  const noPassword = passwordNotSet(error);

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const action = owner.begin();
        if (!action) return;
        setStatus({ context: action.context, pending: true, error: null });
        mutation.mutate({ owner: action, payload: { current_password: currentPassword, new_password: newPassword } });
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
          onChange={(e) => editCredentials({ currentPassword: e.target.value })}
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
          onChange={(e) => editCredentials({ newPassword: e.target.value })}
        />
      </Field>
      <Field label="Confirm new password" error={announced(mismatch ? "Passwords do not match." : null)}>
        <PasswordInput
          autoComplete="new-password"
          value={confirm}
          onChange={(e) => editCredentials({ confirm: e.target.value })}
        />
      </Field>
      <ErrorText message={otherError} />
      <Button
        variant="primary"
        type="submit"
        disabled={!canSubmit}
        loading={pending}
        loadingLabel="Updating…"
        className={cn(fullWidth ? "w-full" : "w-full sm:w-auto sm:self-start")}
      >
        {submitLabel}
      </Button>
    </form>
  );
}

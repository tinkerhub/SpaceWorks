import { Field, PasswordInput } from "../../components/ui";

export function NewPasswordFields({
  idPrefix,
  newPassword,
  confirmPassword,
  onNewPasswordChange,
  onConfirmPasswordChange,
}: {
  idPrefix: string;
  newPassword: string;
  confirmPassword: string;
  onNewPasswordChange: (value: string) => void;
  onConfirmPasswordChange: (value: string) => void;
}) {
  const tooShort = newPassword.length > 0 && newPassword.length < 8;
  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword;

  return (
    <>
      <Field
        id={`${idPrefix}-password`}
        label="New password"
        helperText="At least 8 characters."
        error={tooShort ? <span role="alert">Password must be at least 8 characters.</span> : undefined}
      >
        <PasswordInput
          autoComplete="new-password"
          value={newPassword}
          onChange={(event) => onNewPasswordChange(event.target.value)}
        />
      </Field>
      <Field
        id={`${idPrefix}-confirm`}
        label="Confirm password"
        error={mismatch ? <span role="alert">Passwords do not match.</span> : undefined}
      >
        <PasswordInput
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(event) => onConfirmPasswordChange(event.target.value)}
        />
      </Field>
    </>
  );
}

import { staffRequest } from "../../lib/api";
import { AuthLayout } from "../../components/chrome/AuthLayout";
import { Button } from "../../components/ui";
import { ChangePasswordForm } from "../account/ChangePasswordForm";

type ChangePasswordGateProps = {
  username: string;
  onChanged: () => void;
  onSignOut: () => void;
};

// Shown after login when the account still carries must_change_password. It blocks the
// console until the password is rotated.
export function ChangePasswordGate({ username, onChanged, onSignOut }: ChangePasswordGateProps) {
  return (
    <AuthLayout
      kicker="Security"
      title="Set a new password"
      description={(
        <>
          The account <span className="font-semibold text-ink">{username}</span> must set a new
          password before continuing.
        </>
      )}
    >
      <div className="flex flex-col gap-3">
        <ChangePasswordForm username={username} request={staffRequest} onChanged={onChanged} submitLabel="Save new password" fullWidth />
        <Button variant="quiet" fullWidth onClick={onSignOut}>
          Sign out
        </Button>
      </div>
    </AuthLayout>
  );
}

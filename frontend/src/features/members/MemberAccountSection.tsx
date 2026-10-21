import { useState } from "react";
import { LogOut } from "lucide-react";

import { AuthLayout } from "../../components/chrome/AuthLayout";
import { Button, useToast } from "../../components/ui";
import { logout, memberRequest } from "../../lib/api";
import { AccountCard } from "../account/AccountCard";
import { ChangePasswordForm } from "../account/ChangePasswordForm";

// Signed-in member's own account controls: change password and sign out.
export function MemberAccountSection({ username, onSignedOut }: { username: string; onSignedOut: () => void }) {
  const { showToast } = useToast();
  const [signingOut, setSigningOut] = useState(false);
  const signOut = async () => {
    setSigningOut(true);
    try {
      await logout();
      showToast("Signed out", { tone: "success" });
    } catch (error) {
      // logout() has already dropped the local token and latched refresh off, so the
      // reset below cannot be refreshed back in by a surviving server cookie.
      showToast(error instanceof Error ? error.message : "Signed out on this device only.", { tone: "warning" });
    } finally {
      setSigningOut(false);
      onSignedOut();
    }
  };

  return (
    <div className="flex flex-col gap-5">
      <AccountCard title="Password" description="Changing your password signs you out on your other devices.">
        <div className="max-w-md">
          <ChangePasswordForm username={username} request={memberRequest} onChanged={() => undefined} />
        </div>
      </AccountCard>
      <AccountCard
        title="Sign out"
        description={<>Signed in as <span className="font-semibold text-ink">{username}</span>.</>}
        action={(
          <Button startIcon={<LogOut />} loading={signingOut} onClick={() => { void signOut(); }}>
            Sign out
          </Button>
        )}
      />
    </div>
  );
}

// Shown instead of the whole member area while the account must rotate its password.
export function MemberPasswordRequired({ username, onChanged }: { username: string; onChanged: () => void }) {
  return (
    <AuthLayout
      kicker="Member area"
      title="Set a new password"
      description={(
        <>
          The account <span className="font-semibold text-ink">{username}</span> must set a new
          password before continuing.
        </>
      )}
    >
      <ChangePasswordForm username={username} request={memberRequest} onChanged={onChanged} submitLabel="Save new password" fullWidth />
    </AuthLayout>
  );
}

import { useState } from "react";

import { Avatar, Button, Callout, Modal, SectionHeading } from "../../components/ui";
import { staffRequest, type StaffAuthUser } from "../../lib/api";
import { ChangePasswordForm } from "../account/ChangePasswordForm";

// Self-service account controls for every staff role. Changing your own password lives
// here (not in Users), because the admin reset endpoint refuses self-targeted resets.
// No email-verification state: the console has no verification flow (that belongs to the
// member sign-up), so a "Not verified" chip would flag something no staff member can act
// on. The address itself is shown because "Forgot password?" sends the recovery code there.
export function AccountDialog({
  open,
  onClose,
  onPasswordChanged,
  onSignOut,
  user,
}: {
  open: boolean;
  onClose: () => void;
  onPasswordChanged: () => void;
  onSignOut: () => void;
  // `/auth/me` carries the address; the shared session type does not declare it.
  user: StaffAuthUser & { email?: string };
}) {
  const [changed, setChanged] = useState(false);
  const close = () => {
    setChanged(false);
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title="Your account"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onSignOut}>
            Sign out
          </Button>
        </div>
      )}
    >
      <div className="grid gap-6">
        <div className="flex min-w-0 items-center gap-4">
          <Avatar name={user.username} size="lg" decorative />
          <dl className="grid min-w-0 gap-1.5">
            <dt className="sr-only">Username</dt>
            <dd className="break-all text-title text-ink">{user.username}</dd>
            {user.email ? <>
              <dt className="sr-only">Email</dt>
              <dd className="break-all text-body-ui text-ink-muted">{user.email}</dd>
            </> : null}
          </dl>
        </div>
        <section className="grid gap-4 border-t border-line pt-5">
          <SectionHeading as="h3" title="Change password" description="Changing it signs you out everywhere else." />
          <ChangePasswordForm
            username={user.username}
            request={staffRequest}
            onChanged={() => {
              setChanged(true);
              onPasswordChanged();
            }}
          />
          {changed ? <Callout tone="success">Password updated.</Callout> : null}
        </section>
      </div>
    </Modal>
  );
}

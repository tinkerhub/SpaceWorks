import { useState } from "react";

import { Button, Callout, EmptyState, ErrorText, Field, Input, Spinner } from "../../components/ui";
import { AccountCard } from "../account/AccountCard";


export type ClaimableInvitation = {
  id: number;
  makerspace: { slug: string; name: string };
  inviter: string | null;
  auto_activates: boolean;
  role: string | null;
};

type Props = {
  canRefer: boolean;
  referralsEnabled: boolean;
  emailVerified: boolean | undefined;
  invitations: ClaimableInvitation[];
  invitationsLoading: boolean;
  invitationError?: Error | null;
  onRefer: (email: string) => Promise<unknown>;
  onClaim: (id: number) => void;
  isReferring?: boolean;
  claimingId?: number | null;
  referralError?: Error | null;
  referralSuccess?: string | null;
  claimError?: Error | null;
  claimSuccess?: string | null;
};


export function MemberReferrals({
  canRefer, referralsEnabled, emailVerified, invitations, invitationsLoading, invitationError,
  onRefer, onClaim, isReferring = false, claimingId, referralError, referralSuccess, claimError,
  claimSuccess,
}: Props) {
  const [email, setEmail] = useState("");
  const canSubmitReferral = referralsEnabled && canRefer;

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await onRefer(email);
      setEmail("");
    } catch {
      // The mutation state renders the user-facing error below.
    }
  }

  return <div className="flex flex-col gap-5">
    {canSubmitReferral ? <AccountCard title="Refer someone" description="Invite someone by email to join as a member.">
      <form className="flex flex-col gap-3 sm:flex-row sm:items-start" onSubmit={submit}>
        <Field className="flex-1" label="Invite email" hideLabel id="member-referral-email">
          <Input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="friend@example.com" />
        </Field>
        <Button type="submit" loading={isReferring} loadingLabel="Sending…">Send referral</Button>
      </form>
      {referralSuccess ? <Callout className="mt-4" tone="success" role="status">{referralSuccess}</Callout> : null}
      {referralError ? <div className="mt-4"><ErrorText message={referralError.message} /></div> : null}
    </AccountCard> : null}

    <AccountCard title="Pending invitations" description="Invitations from staff to join this makerspace.">
      <div className="flex flex-col gap-3">
        {emailVerified === false ? <Callout tone="warning">Verify your email to discover and claim invitations.</Callout> : null}
        {invitationsLoading ? <p className="inline-flex items-center gap-2 text-body-ui text-ink-muted"><Spinner decorative className="size-4" />Checking pending invitations…</p> : null}
        <ErrorText message={invitationError?.message} />
        {emailVerified !== false && !invitationsLoading && invitations.length === 0 ? <EmptyState title="No pending invitations for this makerspace." description="When a manager invites you, it shows up here to claim." /> : null}
        {emailVerified !== false && invitations.length ? <ul className="divide-y divide-line rounded-lg border border-line">
          {invitations.map((invitation) => <li className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between" key={invitation.id}>
            <div className="min-w-0">
              <p className="font-semibold text-ink">{invitation.makerspace.name}</p>
              <p className="mt-0.5 text-body-ui text-ink-muted">{invitation.inviter ? `Invited by ${invitation.inviter}` : "You have been invited."}{invitation.auto_activates ? " Claiming activates your membership." : " Claiming sends this to a manager for approval."}</p>
            </div>
            <Button variant="primary" size="sm" className="self-start sm:self-auto" loading={claimingId === invitation.id} loadingLabel="Claiming…" onClick={() => onClaim(invitation.id)}>
              Claim invitation
            </Button>
          </li>)}
        </ul> : null}
        {claimSuccess ? <Callout tone="success" role="status">{claimSuccess}</Callout> : null}
        {claimError ? <ErrorText message={claimError.message} /> : null}
      </div>
    </AccountCard>
  </div>;
}

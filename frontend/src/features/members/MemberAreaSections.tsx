import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { MailCheck, MailWarning } from "lucide-react";

import { Avatar, Button, Callout, Chip, StatusChip, buttonClasses } from "../../components/ui";
import { AccountCard } from "../account/AccountCard";
import { statusLabel, statusTone } from "./memberUi";

export type Membership = {
  makerspace: { slug: string; name: string };
  membership_status: string;
  role: string;
  waiver_acceptance_required: boolean;
  can_refer: boolean;
  can_verify: boolean;
  verified_at: string | null;
  referrals_enabled: boolean;
};
export type Waiver = { has_waiver: boolean; body?: string; version?: string };
export type Presence = { active: boolean; session: { expires_at: string } | null };

/** The account-area header card: who is signed in, where, and their standing. */
export function MemberHeaderCard({ spaceName, username, membership, emailVerified, action }: {
  spaceName?: string;
  username?: string;
  membership?: Membership;
  emailVerified?: boolean;
  action?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-4 rounded-2xl border border-line bg-canvas p-5 sm:flex-row sm:items-center sm:gap-5 sm:p-6">
      <Avatar name={username ?? spaceName} size="lg" tone="secondary" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <p className="text-body-ui text-ink-muted">Member area</p>
        <h1 className="break-words text-h1 text-ink">{spaceName ?? "Your makerspace access"}</h1>
        {username ? <p className="truncate text-body-ui text-ink-secondary">Signed in as {username}</p> : null}
        {membership || emailVerified !== undefined ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {membership ? (
              <StatusChip size="sm" tone={statusTone(membership.membership_status)}>
                {statusLabel(membership.membership_status)} member
              </StatusChip>
            ) : null}
            {emailVerified === true ? <Chip size="sm" tone="success" icon={<MailCheck />}>Email verified</Chip> : null}
            {emailVerified === false ? <Chip size="sm" tone="warning" icon={<MailWarning />}>Email not verified</Chip> : null}
          </div>
        ) : null}
      </div>
      {action ? <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div> : null}
    </header>
  );
}

/** Receipts and charges of closed makerspaces stay reachable from here, signed in or not. */
export function ArchivedPaymentsNotice({ known }: { known: boolean }) {
  const link = <Link className={buttonClasses({ variant: "secondary", size: "sm" })} to="/member/archived">View archived payments</Link>;
  return known ? (
    <Callout tone="info" title="Payments from closed makerspaces" action={link}>
      Receipts and outstanding charges remain available after a makerspace closes.
    </Callout>
  ) : (
    <Callout tone="info" title="Closed makerspace?" action={link}>
      If a makerspace you belonged to has closed, its receipts and any outstanding charges are still reachable. You may need to sign in there.
    </Callout>
  );
}

/** Membership standing, the current waiver and presence: the first tab of the member area. */
export function MembershipCards({ membership, waiver, presence, accepting, presenceBusy, canStartPresence, onAccept, onTogglePresence }: {
  membership: Membership;
  waiver?: Waiver;
  presence?: Presence;
  accepting: boolean;
  presenceBusy: boolean;
  canStartPresence: boolean;
  onAccept: () => void;
  onTogglePresence: () => void;
}) {
  const active = Boolean(presence?.active);
  return (
    <>
      <AccountCard
        title="Membership"
        description={`${membership.makerspace.name} · ${statusLabel(membership.role)}`}
        action={<StatusChip tone={statusTone(membership.membership_status)}>{statusLabel(membership.membership_status)}</StatusChip>}
      >
        {waiver?.has_waiver ? (
          <div className="flex flex-col gap-3">
            <h3 className="text-label text-ink">
              Current waiver <span className="font-mono text-ink-muted">({waiver.version})</span>
            </h3>
            <div className="max-h-60 overflow-y-auto whitespace-pre-wrap rounded-md border border-line bg-subtle p-3 text-body-ui text-ink-secondary">
              {waiver.body}
            </div>
            <Button variant="primary" className="self-start" loading={accepting} onClick={onAccept}>
              Accept waiver
            </Button>
          </div>
        ) : null}
      </AccountCard>
      <AccountCard
        title="Presence"
        description={active
          ? <>Active until <span className="font-mono">{new Date(presence?.session?.expires_at ?? "").toLocaleTimeString()}</span></>
          : "No active session."}
        action={(
          <Button disabled={presenceBusy || (!active && !canStartPresence)} loading={presenceBusy} onClick={onTogglePresence}>
            {active ? "End presence" : "Start 2-hour presence"}
          </Button>
        )}
      />
    </>
  );
}

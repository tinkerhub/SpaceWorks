import { Avatar, Button, CheckboxField, Dropdown, EmptyState, SkeletonRows, StatusChip, Table, TBody, TD, TH, THead, TR } from "../../components/ui";
import type { AdminMembership, PatchedMembershipCapabilities } from "../../generated/api";
import { PaymentReconcileActions } from "./PaymentReconcileActions";

export type MemberRole = { id: number; name: string; granted_actions: string[]; legacy_role?: string | null };

export type MemberRowHandlers = {
  onChangeRole: (member: AdminMembership, roleId: number) => void;
  onCapability: (member: AdminMembership, next: PatchedMembershipCapabilities) => void;
  onVerify: (member: AdminMembership) => void;
  onWitness: (member: AdminMembership) => void;
  onRevoke: (member: AdminMembership) => void;
};

type Pending = { role: boolean; capabilities: boolean; verification: boolean; witness: boolean };

/**
 * What the actor may do with one row, decided by the panel: the row's effective role (a
 * legacy row with no assigned role resolves through its legacy enum), and whether the role
 * is read-only -- the actor's own row, or a manage_makerspace row for a non-superadmin. The
 * backend refuses changing or revoking either, so neither gets a control.
 */
export type MemberRowAccess = { role: MemberRole | null; roleName: string; locked: "own" | "platform" | null };

/** The roster: one row per membership, with the actions the actor may take on it. */
export function MembersRoster({ makerspaceId, rows, loading, roles, access, pending, handlers }: {
  makerspaceId: number;
  rows: AdminMembership[];
  loading: boolean;
  roles: MemberRole[];
  access: (member: AdminMembership) => MemberRowAccess;
  pending: Pending;
  handlers: MemberRowHandlers;
}) {
  if (!loading && !rows.length) {
    return <EmptyState title="No members yet" description="Invite someone from the Invitations tab, or approve a membership request." />;
  }
  return (
    <Table label="Members" className="min-w-[880px]">
      <THead>
        <tr>
          <TH>Member</TH>
          <TH>Role</TH>
          <TH>Status</TH>
          <TH><span className="sr-only">Actions</span></TH>
        </tr>
      </THead>
      <TBody>
        {loading ? <SkeletonRows rows={3} cols={4} /> : rows.map((member) => (
          <MemberRow
            key={member.id}
            makerspaceId={makerspaceId}
            member={member}
            roles={roles}
            access={access(member)}
            pending={pending}
            handlers={handlers}
          />
        ))}
      </TBody>
    </Table>
  );
}

function MemberRow({ makerspaceId, member, roles, access, pending, handlers }: {
  makerspaceId: number;
  member: AdminMembership;
  roles: MemberRole[];
  access: MemberRowAccess;
  pending: Pending;
  handlers: MemberRowHandlers;
}) {
  const active = member.status === "active";
  const displayName = member.user.display_name || member.user.username;
  const currentRole = access.role;
  const currentAssignable = !currentRole || roles.some((role) => role.id === currentRole.id);
  const status = member.status ?? "active";
  return (
    <TR>
      <TD className="align-top">
        <div className="flex min-w-0 items-start gap-3">
          <span aria-hidden="true"><Avatar name={displayName} size="sm" /></span>
          <div className="grid min-w-0 gap-1">
            <span className="font-semibold text-ink">{displayName}</span>
            <PaymentReconcileActions makerspaceId={makerspaceId} payment={member.payment} invalidateKeys={[["members", makerspaceId]]} />
          </div>
        </div>
      </TD>
      <TD className="align-top">
        {!active ? <span className="text-ink-secondary">{access.roleName}</span>
          : access.locked ? (
            <div className="grid gap-0.5">
              <span className="text-ink">{access.roleName}</span>
              {access.locked === "platform" ? <span className="text-caption text-ink-muted">Managed by a platform admin</span> : null}
            </div>
          ) : (
            <Dropdown
              aria-label={`Role for ${displayName}`}
              className="min-w-44"
              value={currentRole ? String(currentRole.id) : ""}
              disabled={pending.role}
              onChange={(event) => handlers.onChangeRole(member, Number(event.target.value))}
            >
              {currentRole ? null : <option value="" disabled>Choose a role</option>}
              {currentAssignable ? null : <option value={currentRole?.id} disabled>{currentRole?.name}</option>}
              {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
            </Dropdown>
          )}
      </TD>
      <TD className="align-top">
        <div className="flex flex-wrap gap-1.5">
          <StatusChip size="sm" tone={active ? "success" : "neutral"}>{status.charAt(0).toUpperCase() + status.slice(1)}</StatusChip>
          {member.waiver_required ? (
            <StatusChip size="sm" tone={member.waiver_current ? "success" : "warning"}>{member.waiver_current ? "Waiver current" : "Waiver needed"}</StatusChip>
          ) : null}
          <StatusChip size="sm" tone={member.verified_at ? "success" : "neutral"}>{member.verified_at ? "Verified" : "Not verified"}</StatusChip>
        </div>
      </TD>
      <TD className="align-top">
        {active ? (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {member.waiver_required && !member.waiver_current ? (
              <Button size="sm" disabled={pending.witness} onClick={() => handlers.onWitness(member)}>Record witnessed acceptance</Button>
            ) : null}
            <CheckboxField label="Can refer" checked={Boolean(member.can_refer)} disabled={pending.capabilities} onCheckedChange={(checked) => handlers.onCapability(member, { can_refer: checked === true })} />
            <CheckboxField label="Can verify" checked={Boolean(member.can_verify)} disabled={pending.capabilities} onCheckedChange={(checked) => handlers.onCapability(member, { can_verify: checked === true })} />
            <Button size="sm" disabled={pending.verification} onClick={() => handlers.onVerify(member)}>{member.verified_at ? "Unverify" : "Verify"}</Button>
            {access.locked === "own" ? <span className="text-caption text-ink-muted">You</span>
              : access.locked ? null : <Button size="sm" variant="danger-quiet" onClick={() => handlers.onRevoke(member)}>Revoke…</Button>}
          </div>
        ) : null}
      </TD>
    </TR>
  );
}

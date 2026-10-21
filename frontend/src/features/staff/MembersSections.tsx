import type { ReactNode } from "react";

import {
  Button,
  Card,
  CardHeader,
  Dropdown,
  EmptyState,
  Field,
  Input,
  SkeletonRows,
  StatusChip,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  Textarea,
  type StatusTone,
} from "../../components/ui";
import type { MembershipRequest } from "../../generated/api";
import type { MemberRole } from "./MembersRoster";

export type Presence = { display_name: string; role_label: string; started_at: string; expires_at: string };

const requestTones: Record<string, StatusTone> = { requested: "warning", approved: "success", active: "success", revoked: "neutral", rejected: "danger" };

export function MembersInvitations({
  membershipEnabled, roles, selectedRole, onRoleChange, inviteEmail, onInviteEmailChange, inviting, onInvite,
  requests, requestsLoading, approving, revoking, onApprove, onRevoke,
}: {
  membershipEnabled: boolean;
  roles: MemberRole[];
  selectedRole: number | null;
  onRoleChange: (roleId: number) => void;
  inviteEmail: string;
  onInviteEmailChange: (email: string) => void;
  inviting: boolean;
  onInvite: () => void;
  requests: MembershipRequest[];
  requestsLoading: boolean;
  approving: boolean;
  revoking: boolean;
  onApprove: (id: number) => void;
  onRevoke: (id: number) => void;
}) {
  return (
    <div className="grid gap-5">
      <Card as="section">
        <CardHeader title="Invite someone" description="We'll email them a link to join with the role you pick." />
        <form
          className="grid gap-3 sm:grid-cols-[minmax(0,220px)_minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(event) => { event.preventDefault(); if (inviteEmail && selectedRole) onInvite(); }}
        >
          <Field label="Invite role">
            <Dropdown value={String(selectedRole ?? "")} onChange={(event) => onRoleChange(Number(event.target.value))}>
              {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
            </Dropdown>
          </Field>
          <Field label="Invite email">
            <Input type="email" value={inviteEmail} onChange={(event) => onInviteEmailChange(event.target.value)} />
          </Field>
          <Button type="submit" variant="secondary" disabled={!inviteEmail || !selectedRole} loading={inviting} loadingLabel="Sending…">
            Send invite
          </Button>
        </form>
      </Card>
      {membershipEnabled ? (
        <section className="grid gap-3" aria-label="Membership requests">
          <h2 className="text-h4 text-ink">Membership requests</h2>
          {!requestsLoading && !requests.length ? (
            <EmptyState title="No requests" description="New requests to join show up here for approval." />
          ) : (
            <Table label="Membership requests">
              <THead>
                <tr><TH>Person</TH><TH>Kind</TH><TH>State</TH><TH><span className="sr-only">Actions</span></TH></tr>
              </THead>
              <TBody>
                {requestsLoading ? <SkeletonRows rows={2} cols={4} /> : requests.map((row) => (
                  <TR key={row.id}>
                    <TD className="font-semibold">{row.user?.username ?? row.invite_email}</TD>
                    <TD className="text-ink-secondary">{humanize(row.kind)}</TD>
                    <TD><StatusChip size="sm" tone={requestTones[row.state] ?? "neutral"}>{humanize(row.state)}</StatusChip></TD>
                    <TD>
                      {row.state === "requested" ? (
                        <div className="flex justify-end gap-2">
                          <Button size="sm" variant="primary" disabled={!selectedRole || approving} onClick={() => onApprove(row.id)}>Approve</Button>
                          <Button size="sm" variant="danger-quiet" disabled={revoking} onClick={() => onRevoke(row.id)}>Revoke</Button>
                        </div>
                      ) : null}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </section>
      ) : null}
    </div>
  );
}

export function MembersPresence({ rows, loading }: { rows: Presence[]; loading: boolean }) {
  if (!loading && !rows.length) {
    return <EmptyState title="No one is checked in" description="Members appear here while they have an active presence session." />;
  }
  return (
    <Table label="Present now">
      <THead><tr><TH>Name</TH><TH>Role</TH><TH>Until</TH></tr></THead>
      <TBody>
        {loading ? <SkeletonRows rows={2} cols={3} /> : rows.map((row) => (
          <TR key={`${row.display_name}-${row.started_at}`}>
            <TD className="font-semibold">{row.display_name}</TD>
            <TD className="text-ink-secondary">{row.role_label}</TD>
            <TD className="text-ink-secondary">{new Date(row.expires_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function MembersWaiver({ waiver, onChange, action }: {
  waiver: { version: string; body: string };
  onChange: (waiver: { version: string; body: string }) => void;
  action: ReactNode;
}) {
  return (
    <div className="grid gap-4">
      <Field label="Waiver version" helperText="A short label such as 2026-10 or v3.">
        <Input value={waiver.version} onChange={(event) => onChange({ ...waiver, version: event.target.value })} />
      </Field>
      <Field label="Waiver text">
        <Textarea rows={8} value={waiver.body} onChange={(event) => onChange({ ...waiver, body: event.target.value })} />
      </Field>
      {action}
    </div>
  );
}

function humanize(value: string) {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Card,
  CardHeader,
  Dropdown,
  EmptyState,
  ErrorText,
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
  useToast,
} from "../../../components/ui";
import type { MembershipRequest, PaginatedMembershipRequestList } from "../../../generated/api";
import { staffRequest } from "../../../lib/api";
import { errorText, useStaffGet } from "./shared";
import type { StaffRole } from "./rolesApi";

// Staff invitations, shown on Users only while the `membership` module is off (with it on,
// the Members tab owns every invitation). They survive that module by design: a role that
// grants actions makes an invitation core RBAC (`invite_membership`). The invitee signs in
// with the invited email to claim it; once the invitation is tied to an account (claimed, or
// invited by an address that already had one) it waits here for approval -- with the module
// off the queue lists staff invitations only, so this is where it stays findable.
export function UsersInvitations({ msId, roles, onApproved }: {
  msId: number;
  roles: StaffRole[];
  onApproved: () => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState<number | null>(null);
  const selectedRole = roleId ?? roles[0]?.id ?? null;
  const key = ["staff", "invitations", msId];
  const list = useStaffGet<PaginatedMembershipRequestList>(key, `/admin/membership-requests?makerspace_id=${msId}&state=invited`);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });
  const failed = (fallback: string) => (error: Error) => showToast(errorText(error, fallback), { tone: "error" });

  const invite = useMutation({
    mutationFn: () => staffRequest(`/admin/makerspace/${msId}/membership-invitations`, {
      method: "POST", body: JSON.stringify({ invite_email: email.trim(), role_id: selectedRole }),
    }),
    onSuccess: () => { setEmail(""); refresh(); showToast("Invitation sent", { tone: "success" }); },
    onError: failed("Couldn't send the invitation"),
  });
  const approve = useMutation({
    mutationFn: (row: MembershipRequest) => staffRequest(`/admin/membership-requests/${row.id}/approve`, {
      method: "POST", body: JSON.stringify({ role_id: row.assigned_role?.id }),
    }),
    onSuccess: () => { refresh(); onApproved(); showToast("Invitation approved", { tone: "success" }); },
    onError: failed("Couldn't approve the invitation"),
  });
  const revoke = useMutation({
    mutationFn: (row: MembershipRequest) => staffRequest(`/admin/membership-requests/${row.id}/revoke`, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: () => { refresh(); showToast("Invitation withdrawn", { tone: "success" }); },
    onError: failed("Couldn't withdraw the invitation"),
  });
  const rows = list.data?.results ?? [];

  return (
    <div className="grid gap-5">
      <Card as="section">
        <CardHeader title="Invite by email" description="They sign in with this email to claim the invitation, then you approve it here." />
        <form
          className="grid gap-3 sm:grid-cols-[minmax(0,220px)_minmax(0,1fr)_auto] sm:items-end"
          onSubmit={(event) => { event.preventDefault(); if (email.trim() && selectedRole) invite.mutate(); }}
        >
          <Field label="Role">
            <Dropdown value={String(selectedRole ?? "")} onChange={(event) => setRoleId(Number(event.target.value))}>
              {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
            </Dropdown>
          </Field>
          <Field label="Email">
            <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
          </Field>
          <Button type="submit" variant="secondary" disabled={!email.trim() || !selectedRole} loading={invite.isPending} loadingLabel="Sending…">
            Send invite
          </Button>
        </form>
      </Card>
      <section className="grid gap-3" aria-label="Open invitations">
        <h2 className="text-h4 text-ink">Open invitations</h2>
        <ErrorText message={list.error?.message} />
        {!list.isLoading && !rows.length ? (
          <EmptyState title="No open invitations" description="Invitations you send show up here until they are approved or withdrawn." />
        ) : (
          <Table label="Open invitations">
            <THead>
              <tr><TH>Email</TH><TH>Role</TH><TH>State</TH><TH><span className="sr-only">Actions</span></TH></tr>
            </THead>
            <TBody>
              {list.isLoading ? <SkeletonRows rows={2} cols={4} /> : rows.map((row) => (
                <TR key={row.id}>
                  <TD className="font-semibold">{row.invite_email || row.user?.username}</TD>
                  <TD className="text-ink-secondary">{row.assigned_role?.name ?? ""}</TD>
                  <TD>
                    <StatusChip size="sm" tone={row.user ? "warning" : "neutral"}>{row.user ? "Ready to approve" : "Waiting for them to sign in"}</StatusChip>
                  </TD>
                  <TD>
                    <div className="flex justify-end gap-2">
                      {row.user ? <Button size="sm" variant="primary" disabled={approve.isPending} onClick={() => approve.mutate(row)}>Approve</Button> : null}
                      <Button size="sm" variant="danger-quiet" disabled={revoke.isPending} onClick={() => revoke.mutate(row)}>Withdraw</Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </section>
    </div>
  );
}

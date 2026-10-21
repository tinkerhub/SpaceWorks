import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Button,
  Card,
  CardHeader,
  ConfirmDialog,
  ErrorText,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  useToast,
} from "../../components/ui";
import type {
  AdminMembership,
  PaginatedAdminMembershipList,
  PaginatedMembershipRequestList,
  PatchedMembershipCapabilities,
} from "../../generated/api";
import { StructuredApiError, staffRequest } from "../../lib/api";
import { Panel } from "./panels/shared";
import { assignableRolesFor, roleManagesMakerspace } from "./panels/rolesApi";
import { MembersRoster, type MemberRole } from "./MembersRoster";
import { MembersInvitations, MembersPresence, MembersWaiver, type Presence } from "./MembersSections";

export const membershipErrorText = (error: unknown) =>
  error instanceof StructuredApiError ? error.detail ?? error.message : "Unable to update membership.";

// `membership` gates the COMMUNITY side only. The staff roster, role assignment and
// revoke are core RBAC state and are never gated -- gating them would let a makerspace
// lock itself out of its own administration (plan A7). So the module hides exactly the
// surfaces the backend refuses: the request queue and verification/referral capabilities.
// Waiver management and witnessed acceptance are core liability controls. Invitation stays,
// because a STAFF invitation keeps working with
// the module off (`invite_membership` discriminates on the role's granted actions).
// Role selects offer only roles under the actor's ceiling (assignableRolesFor), and a
// non-superadmin never gets Revoke on a manage_makerspace row -- the backend refuses both.
export function MembersPanel({ makerspaceId, membershipEnabled, actorActions, isSuperadmin }: {
  makerspaceId: number;
  membershipEnabled: boolean;
  actorActions: readonly string[];
  isSuperadmin: boolean;
}) {
  const client = useQueryClient();
  const { showToast } = useToast();
  const key = ["members", makerspaceId];
  const roster = useQuery({
    queryKey: [...key, "roster"],
    queryFn: () => staffRequest<PaginatedAdminMembershipList>(`/admin/memberships?makerspace_id=${makerspaceId}`),
  });
  const requests = useQuery({
    queryKey: [...key, "requests"],
    queryFn: () => staffRequest<PaginatedMembershipRequestList>(`/admin/membership-requests?makerspace_id=${makerspaceId}`),
    enabled: membershipEnabled,
  });
  const presence = useQuery({ queryKey: [...key, "presence"], queryFn: () => staffRequest<Presence[]>(`/admin/makerspace/${makerspaceId}/presence-sessions/current`) });
  const roles = useQuery({ queryKey: [...key, "roles"], queryFn: () => staffRequest<MemberRole[]>(`/admin/makerspaces/${makerspaceId}/roles`) });
  const [roleId, setRoleId] = useState<number | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [waiver, setWaiver] = useState({ version: "", body: "" });
  const [revokeTarget, setRevokeTarget] = useState<AdminMembership | null>(null);
  const refresh = () => client.invalidateQueries({ queryKey: key });
  // Every mutation refreshes the page's queries and confirms in a toast; failures also stay
  // visible in the panel's error line below the header.
  const notify = (message: string) => ({
    onSuccess: () => { refresh(); showToast(message, { tone: "success" }); },
    onError: (error: unknown) => showToast(membershipErrorText(error), { tone: "error" }),
  });
  const revoke = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/memberships/${id}/revoke`, { method: "POST", body: JSON.stringify({}) }), ...notify("Membership revoked") });
  const revokeRequest = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/membership-requests/${id}/revoke`, { method: "POST", body: JSON.stringify({}) }), ...notify("Request revoked") });
  const approve = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/membership-requests/${id}/approve`, { method: "POST", body: JSON.stringify({ role_id: roleId }) }), ...notify("Request approved") });
  const changeRole = useMutation({ mutationFn: ({ id, nextRoleId }: { id: number; nextRoleId: number }) => staffRequest(`/admin/memberships/${id}/role`, { method: "PATCH", body: JSON.stringify({ role_id: nextRoleId }) }), ...notify("Role changed") });
  const capabilities = useMutation({
    mutationFn: ({ id, next }: { id: number; next: PatchedMembershipCapabilities }) =>
      staffRequest<AdminMembership>(`/admin/memberships/${id}/capabilities`, {
        method: "PATCH",
        body: JSON.stringify(next),
      }),
    ...notify("Member updated"),
  });
  const verify = useMutation({
    mutationFn: ({ id, verified }: { id: number; verified: boolean }) =>
      staffRequest<AdminMembership>(`/admin/memberships/${id}/${verified ? "verify" : "unverify"}`, {
        method: "POST",
      }),
    ...notify("Verification updated"),
  });
  const invite = useMutation({
    mutationFn: () => staffRequest(`/admin/makerspace/${makerspaceId}/membership-invitations`, { method: "POST", body: JSON.stringify({ invite_email: inviteEmail, role_id: roleId }) }),
    onSuccess: () => { setInviteEmail(""); refresh(); showToast("Invitation sent", { tone: "success" }); },
    onError: (error: unknown) => showToast(membershipErrorText(error), { tone: "error" }),
  });
  const publishWaiver = useMutation({ mutationFn: () => staffRequest(`/admin/makerspaces/${makerspaceId}/waiver`, { method: "PUT", body: JSON.stringify(waiver) }), ...notify("Waiver published") });
  const witnessWaiver = useMutation({ mutationFn: (id: number) => staffRequest(`/admin/memberships/${id}/waiver/witness`, { method: "POST", body: JSON.stringify({}) }), ...notify("Waiver acceptance recorded") });
  const error = revoke.error ?? revokeRequest.error ?? approve.error ?? changeRole.error ?? capabilities.error ?? verify.error ?? invite.error ?? publishWaiver.error ?? witnessWaiver.error;
  const assignableRoles = assignableRolesFor(roles.data ?? [], actorActions, isSuperadmin);
  const selectedRole = roleId ?? assignableRoles[0]?.id ?? null;

  return (
    <Panel title="Members" description="Membership, referral and verification delegation, waiver compliance, and who is in the space right now.">
      <div className="grid gap-4">
        {error ? <ErrorText message={membershipErrorText(error)} /> : null}
        <Tabs defaultValue="roster">
          <TabsList aria-label="Member sections">
            <TabsTrigger value="roster">Members</TabsTrigger>
            <TabsTrigger value="requests">{membershipEnabled ? "Requests" : "Invitations"}</TabsTrigger>
            <TabsTrigger value="presence">Present now</TabsTrigger>
            <TabsTrigger value="waiver">Waiver</TabsTrigger>
          </TabsList>
          <TabsContent value="roster" className="grid gap-3">
            {roster.isError ? <ErrorText message={membershipErrorText(roster.error)} /> : null}
            <MembersRoster
              makerspaceId={makerspaceId}
              rows={roster.data?.results ?? []}
              loading={roster.isLoading}
              roles={assignableRoles}
              membershipEnabled={membershipEnabled}
              managedByPlatform={(row) => !isSuperadmin && roleManagesMakerspace(roles.data ?? [], row.assigned_role?.id)}
              pending={{ role: changeRole.isPending, capabilities: capabilities.isPending, verification: verify.isPending, witness: witnessWaiver.isPending }}
              handlers={{
                onChangeRole: (row, nextRoleId) => changeRole.mutate({ id: row.id, nextRoleId }),
                onCapability: (row, next) => capabilities.mutate({ id: row.id, next }),
                onVerify: (row) => verify.mutate({ id: row.id, verified: !row.verified_at }),
                onWitness: (row) => witnessWaiver.mutate(row.id),
                onRevoke: setRevokeTarget,
              }}
            />
          </TabsContent>
          <TabsContent value="requests">
            <MembersInvitations
              membershipEnabled={membershipEnabled}
              roles={assignableRoles}
              selectedRole={selectedRole}
              onRoleChange={setRoleId}
              inviteEmail={inviteEmail}
              onInviteEmailChange={setInviteEmail}
              inviting={invite.isPending}
              onInvite={() => invite.mutate()}
              requests={requests.data?.results ?? []}
              requestsLoading={membershipEnabled && requests.isLoading}
              approving={approve.isPending}
              revoking={revokeRequest.isPending}
              onApprove={(id) => approve.mutate(id)}
              onRevoke={(id) => revokeRequest.mutate(id)}
            />
          </TabsContent>
          <TabsContent value="presence">
            <MembersPresence rows={presence.data ?? []} loading={presence.isLoading} />
          </TabsContent>
          <TabsContent value="waiver">
            <Card as="section">
              <CardHeader title="Current waiver" description="Members accept the latest version. Publishing a new version asks everyone to accept again." />
              <MembersWaiver
                waiver={waiver}
                onChange={setWaiver}
                action={(
                  <Button variant="primary" className="w-fit" disabled={!waiver.version || !waiver.body} loading={publishWaiver.isPending} loadingLabel="Publishing…" onClick={() => publishWaiver.mutate()}>
                    Publish waiver
                  </Button>
                )}
              />
            </Card>
          </TabsContent>
        </Tabs>
      </div>
      <ConfirmDialog
        open={revokeTarget !== null}
        title="Revoke membership?"
        tone="danger"
        message={revokeTarget ? `${revokeTarget.user.display_name || revokeTarget.user.username} loses their membership here. Their account is not deleted.` : ""}
        confirmLabel="Revoke membership"
        pending={revoke.isPending}
        onCancel={() => setRevokeTarget(null)}
        onConfirm={() => { if (revokeTarget) revoke.mutate(revokeTarget.id, { onSuccess: () => setRevokeTarget(null) }); }}
      />
    </Panel>
  );
}

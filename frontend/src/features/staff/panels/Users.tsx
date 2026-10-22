import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";

import { Button, ConfirmDialog, Dropdown, EmptyState, ErrorText, Field, Tabs, TabsContent, TabsList, TabsTrigger, useToast } from "../../../components/ui";
import { staffRequest, type StaffAuthUser } from "../../../lib/api";
import { moduleEnabled } from "../../../lib/modules";
import { Panel, errorText, useStaffGet, type Makerspace } from "./shared";
import { RoleManager } from "./RoleManager";
import { UsersInvitations } from "./UsersInvitations";
import { roleLabel, UsersTable } from "./UsersTable";
import {
  AddStaffModal,
  CreateMakerspaceModal,
  ResetPasswordModal,
  RestrictUserModal,
  type MakerspaceForm,
  type ResetPasswordForm,
  type ResetPasswordResult,
  type RestrictForm,
  type StaffForm,
} from "./UsersModals";
import { emptyMakerspaceForm, emptyResetPasswordForm, emptyRestrictForm, emptyStaffForm, makerspacePayload, staffPayload } from "./usersForms";
import { assignableRolesFor, assignRole, capabilitiesPath, createMembership, isStaffMembership, liveActions, type Capability, type StaffMembershipRow, type StaffRole } from "./rolesApi";

export function Users({ makerspaces, isSuperadmin, currentUser, onAuthRefresh }: {
  makerspaces: Makerspace[];
  isSuperadmin: boolean;
  currentUser: StaffAuthUser;
  onAuthRefresh: () => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [msId, setMsId] = useState<number>(makerspaces[0]?.id ?? 0);
  const [roleFilter, setRoleFilter] = useState("all");
  const [addOpen, setAddOpen] = useState(false);
  const [makerspaceOpen, setMakerspaceOpen] = useState(false);
  const [staffForm, setStaffForm] = useState<StaffForm>(emptyStaffForm);
  const [makerspaceForm, setMakerspaceForm] = useState<MakerspaceForm>(emptyMakerspaceForm);
  const [restrictTarget, setRestrictTarget] = useState<StaffMembershipRow | null>(null);
  const [restrictForm, setRestrictForm] = useState<RestrictForm>(emptyRestrictForm);
  const [restoreTarget, setRestoreTarget] = useState<StaffMembershipRow | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<StaffMembershipRow | null>(null);
  const [resetPasswordTarget, setResetPasswordTarget] = useState<StaffMembershipRow | null>(null);
  const [resetPasswordForm, setResetPasswordForm] = useState<ResetPasswordForm>(emptyResetPasswordForm);
  const [resetPasswordResult, setResetPasswordResult] = useState<ResetPasswordResult | null>(null);

  // makerspaces may arrive after first mount (async load); the useState initializer only runs
  // once, so reconcile msId to a valid makerspace whenever the list changes or msId is stale.
  useEffect(() => {
    if (makerspaces.length && !makerspaces.some((space) => space.id === msId)) {
      setMsId(makerspaces[0].id);
    }
  }, [makerspaces, msId]);

  const memberships = useStaffGet<StaffMembershipRow[]>(["staff", "memberships", msId], `/admin/makerspaces/${msId}/memberships`, msId > 0);
  const rolesList = useStaffGet<StaffRole[]>(["staff", "roles", msId], `/admin/makerspaces/${msId}/roles`, msId > 0);

  const makerspaceNames = useMemo(() => new Map(makerspaces.map((space) => [space.id, space.name])), [makerspaces]);
  const actorActions = useMemo(
    () => currentUser.makerspaces.find((item) => item.id === msId)?.actions ?? [],
    [currentUser, msId],
  );
  const canManageRoles = isSuperadmin || actorActions.includes("manage_makerspace");
  // Staff invitations live here only while Members (membership) is off, and only when the
  // invitee can sign in to claim one -- with member_accounts off nobody can.
  const modules = makerspaces.find((space) => space.id === msId)?.enabled_modules;
  const showInvitations = !moduleEnabled(modules, "membership") && moduleEnabled(modules, "member_accounts");
  // Shares RoleManager's cache entry: the catalog of actions this space's modules offer.
  const capabilities = useStaffGet<Capability[]>(["staff", "capabilities", msId], capabilitiesPath(msId), msId > 0);
  const assignableRoles = useMemo(
    // Staff roles only: a role granting no actions (Member) is a community membership, and
    // one granting only switched-off modules' actions would hand over an empty console.
    () => assignableRolesFor(rolesList.data ?? [], actorActions, isSuperadmin).filter((role) => liveActions(role, capabilities.data).length > 0),
    [rolesList.data, isSuperadmin, actorActions, capabilities.data],
  );

  const staffRows = useMemo(
    () => (memberships.data ?? []).filter((row) => isStaffMembership(row, rolesList.data ?? [])),
    [memberships.data, rolesList.data],
  );
  const roleFilterOptions = useMemo(() => Array.from(new Set(staffRows.map(roleLabel))).sort(), [staffRows]);
  const rows = useMemo(
    () => (roleFilter === "all" ? staffRows : staffRows.filter((row) => roleLabel(row) === roleFilter)),
    [staffRows, roleFilter],
  );

  // A role edit / assignment / revoke can change the CURRENT actor's own effective actions,
  // so refetch /auth/me (onAuthRefresh) in addition to invalidating the makerspace-scoped lists.
  const afterStaffChange = () => {
    queryClient.invalidateQueries({ queryKey: ["staff", "memberships", msId] });
    queryClient.invalidateQueries({ queryKey: ["staff", "roles", msId] });
    onAuthRefresh();
  };
  const succeeded = (message: string) => showToast(message, { tone: "success" });
  // `Error`, not `unknown`: an `unknown` onError parameter widens the mutation's error type.
  const failed = (fallback: string) => (error: Error) => showToast(errorText(error, fallback), { tone: "error" });

  const createStaff = useMutation({
    mutationFn: () => createMembership(msId, staffPayload(staffForm)),
    onSuccess: () => { setAddOpen(false); setStaffForm(emptyStaffForm); afterStaffChange(); succeeded("Staff member added"); },
    onError: failed("Couldn't add the staff member"),
  });
  const changeRole = useMutation({
    mutationFn: ({ membership, roleId }: { membership: StaffMembershipRow; roleId: number }) => assignRole(msId, membership.id, roleId),
    onSuccess: () => { afterStaffChange(); succeeded("Role changed"); },
    onError: failed("Couldn't change the role"),
  });
  const restrict = useMutation({
    mutationFn: () =>
      restrictTarget
        ? staffRequest(`/admin/users/${restrictTarget.user.id}/restrict`, {
            method: "POST",
            body: JSON.stringify({ status: restrictForm.status, reason: restrictForm.reason.trim() }),
          })
        : Promise.resolve(),
    onSuccess: () => { setRestrictTarget(null); setRestrictForm(emptyRestrictForm); afterStaffChange(); succeeded("Access restricted"); },
    onError: failed("Couldn't restrict access"),
  });
  const restore = useMutation({
    mutationFn: (membership: StaffMembershipRow) => staffRequest(`/admin/users/${membership.user.id}/restore-access`, { method: "POST" }),
    onSuccess: () => { setRestoreTarget(null); afterStaffChange(); succeeded("Access restored"); },
    onError: failed("Couldn't restore access"),
  });
  const revoke = useMutation({
    mutationFn: (membership: StaffMembershipRow) => staffRequest(`/admin/memberships/${membership.id}`, { method: "DELETE" }),
    onSuccess: () => { setRevokeTarget(null); afterStaffChange(); succeeded("Role revoked"); },
    onError: failed("Couldn't revoke the role"),
  });
  const resetPassword = useMutation({
    mutationFn: () => {
      if (!resetPasswordTarget) throw new Error("No user selected");
      const password = resetPasswordForm.password;
      return staffRequest<ResetPasswordResult>(`/admin/users/${resetPasswordTarget.user.id}/reset-password`, {
        method: "POST",
        body: JSON.stringify(password ? { password } : {}),
      });
    },
    onSuccess: (result) => { setResetPasswordResult(result); succeeded("Temporary password set"); },
    onError: failed("Couldn't reset the password"),
  });
  const createMakerspace = useMutation({
    mutationFn: () => staffRequest("/admin/makerspaces", { method: "POST", body: JSON.stringify(makerspacePayload(makerspaceForm)) }),
    onSuccess: () => {
      setMakerspaceOpen(false);
      setMakerspaceForm(emptyMakerspaceForm);
      queryClient.invalidateQueries({ queryKey: ["staff", "makerspaces"] });
      succeeded("Makerspace created");
    },
    onError: failed("Couldn't create the makerspace"),
  });

  const openAdd = () => { setStaffForm({ ...emptyStaffForm, makerspace_id: String(msId) }); setAddOpen(true); };
  const openRestrict = (membership: StaffMembershipRow) => { setRestrictTarget(membership); setRestrictForm(emptyRestrictForm); };
  // Opening (a row) and closing (null) both start from a clean reset-password state.
  const selectResetPasswordTarget = (membership: StaffMembershipRow | null) => {
    resetPassword.reset();
    setResetPasswordTarget(membership);
    setResetPasswordForm(emptyResetPasswordForm);
    setResetPasswordResult(null);
  };

  const description = "Staff accounts and the roles that decide what each person can do.";
  if (!makerspaces.length) {
    return <Panel title="Users" description={description}><EmptyState title="No makerspaces yet" description="This account isn't linked to a makerspace. Ask a platform admin to add you to one." /></Panel>;
  }

  const panelError = memberships.error?.message ?? rolesList.error?.message ?? restore.error?.message;
  const people = (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Role" className="w-full sm:w-60">
          <Dropdown value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
            <option value="all">All roles</option>
            {roleFilterOptions.map((name) => <option key={name} value={name}>{name}</option>)}
          </Dropdown>
        </Field>
      </div>
      <ErrorText message={panelError} />
      <UsersTable
        rows={rows}
        makerspaceNames={makerspaceNames}
        loading={memberships.isLoading || rolesList.isLoading}
        assignableRoles={assignableRoles}
        roles={rolesList.data ?? []}
        currentUsername={currentUser.username}
        isSuperadmin={isSuperadmin}
        onRestrict={openRestrict}
        onRestore={setRestoreTarget}
        onResetPassword={selectResetPasswordTarget}
        onRevoke={setRevokeTarget}
        onChangeRole={(membership, roleId) => changeRole.mutateAsync({ membership, roleId })}
      />
    </div>
  );

  return (
    <Panel
      title="Users"
      description={description}
      actions={<>
        {isSuperadmin ? <Button variant="secondary" onClick={() => setMakerspaceOpen(true)}>Create makerspace</Button> : null}
        <Button variant="primary" startIcon={<UserPlus />} onClick={openAdd} disabled={!assignableRoles.length}>Add staff</Button>
      </>}
    >
      <div className="grid gap-5">
        {makerspaces.length > 1 ? (
          <Field label="Makerspace" className="w-full sm:w-72">
            <Dropdown value={String(msId)} onChange={(event) => { setMsId(Number(event.target.value)); setRoleFilter("all"); }}>
              {makerspaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
            </Dropdown>
          </Field>
        ) : null}
        {canManageRoles ? (
          <Tabs defaultValue="people">
            <TabsList aria-label="Users sections">
              <TabsTrigger value="people">People</TabsTrigger>
              <TabsTrigger value="roles">Roles</TabsTrigger>
              {showInvitations ? <TabsTrigger value="invitations">Invitations</TabsTrigger> : null}
            </TabsList>
            <TabsContent value="people">{people}</TabsContent>
            {showInvitations ? (
              <TabsContent value="invitations">
                <UsersInvitations msId={msId} roles={assignableRoles} onApproved={afterStaffChange} />
              </TabsContent>
            ) : null}
            <TabsContent value="roles">
              <RoleManager msId={msId} actorActions={actorActions} isSuperadmin={isSuperadmin} membershipOn={moduleEnabled(modules, "membership")} onRolesChanged={afterStaffChange} />
            </TabsContent>
          </Tabs>
        ) : people}
      </div>

      <AddStaffModal
        open={addOpen}
        form={staffForm}
        makerspaceName={makerspaceNames.get(msId) ?? ""}
        pending={createStaff.isPending}
        error={createStaff.error}
        roles={assignableRoles}
        onChange={setStaffForm}
        onClose={() => setAddOpen(false)}
        onSubmit={() => createStaff.mutate()}
      />
      <RestrictUserModal
        open={Boolean(restrictTarget)}
        userLabel={restrictTarget?.user.username ?? ""}
        form={restrictForm}
        pending={restrict.isPending}
        error={restrict.error}
        onChange={setRestrictForm}
        onClose={() => setRestrictTarget(null)}
        onSubmit={() => restrict.mutate()}
      />
      <CreateMakerspaceModal
        open={makerspaceOpen}
        form={makerspaceForm}
        pending={createMakerspace.isPending}
        error={createMakerspace.error}
        onChange={setMakerspaceForm}
        onClose={() => setMakerspaceOpen(false)}
        onSubmit={() => createMakerspace.mutate()}
      />
      <ResetPasswordModal
        open={Boolean(resetPasswordTarget)}
        userLabel={resetPasswordTarget?.user.username ?? ""}
        form={resetPasswordForm}
        pending={resetPassword.isPending}
        error={resetPassword.error}
        result={resetPasswordResult}
        onChange={setResetPasswordForm}
        onClose={() => selectResetPasswordTarget(null)}
        onSubmit={() => resetPassword.mutate()}
      />
      <ConfirmDialog
        open={Boolean(restoreTarget)}
        title="Restore access?"
        message={restoreTarget ? `${restoreTarget.user.username} can sign in and use the console again.` : ""}
        confirmLabel="Restore access"
        pending={restore.isPending}
        onCancel={() => setRestoreTarget(null)}
        onConfirm={() => { if (restoreTarget) restore.mutate(restoreTarget); }}
      />
      <ConfirmDialog
        open={Boolean(revokeTarget)}
        title="Revoke role?"
        tone="danger"
        message={
          revokeTarget
            ? `Remove ${revokeTarget.user.username}'s "${revokeTarget.assigned_role?.name ?? revokeTarget.role.replace(/_/g, " ")}" role in ${makerspaceNames.get(revokeTarget.makerspace_id) ?? revokeTarget.makerspace_slug}? Their account is not deleted.`
            : ""
        }
        confirmLabel="Revoke role"
        pending={revoke.isPending}
        onCancel={() => setRevokeTarget(null)}
        onConfirm={() => { if (revokeTarget) revoke.mutate(revokeTarget); }}
      />
    </Panel>
  );
}

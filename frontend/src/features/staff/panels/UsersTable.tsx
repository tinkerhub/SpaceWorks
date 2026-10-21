import { useEffect, useState } from "react";

import {
  Avatar,
  Button,
  Dropdown,
  EmptyState,
  ErrorText,
  Field,
  Modal,
  SkeletonRows,
  StatusChip,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  type StatusTone,
} from "../../../components/ui";
import { roleManagesMakerspace, type StaffMembershipRow, type StaffRole } from "./rolesApi";

// Only the actions the backend would accept are offered: a non-superadmin cannot touch their
// own row or a row whose role holds manage_makerspace, restrict/restore is superadmin-only,
// and nobody resets their own password here (that is the account dialog's Change password).
export function UsersTable({ rows, makerspaceNames, loading, assignableRoles, roles, currentUsername, isSuperadmin, onRestrict, onRestore, onResetPassword, onRevoke, onChangeRole }: {
  rows: StaffMembershipRow[];
  makerspaceNames: Map<number, string>;
  loading: boolean;
  assignableRoles: StaffRole[];
  roles: StaffRole[];
  currentUsername: string;
  isSuperadmin: boolean;
  onRestrict: (membership: StaffMembershipRow) => void;
  onRestore: (membership: StaffMembershipRow) => void;
  onResetPassword: (membership: StaffMembershipRow) => void;
  onRevoke: (membership: StaffMembershipRow) => void;
  onChangeRole: (membership: StaffMembershipRow, roleId: number) => Promise<unknown>;
}) {
  const [changeTarget, setChangeTarget] = useState<StaffMembershipRow | null>(null);
  const [roleId, setRoleId] = useState<number | "">("");
  const [assignPending, setAssignPending] = useState(false);
  const [assignError, setAssignError] = useState("");
  const openChange = (membership: StaffMembershipRow) => {
    setAssignError("");
    setChangeTarget(membership);
    setRoleId(membership.assigned_role?.id ?? "");
  };
  const submitChange = () => {
    if (!changeTarget || roleId === "") return;
    setAssignError("");
    setAssignPending(true);
    onChangeRole(changeTarget, roleId)
      .then(() => setChangeTarget(null))
      .catch((error) => setAssignError(error instanceof Error ? error.message : "Unable to change role"))
      .finally(() => setAssignPending(false));
  };
  if (!loading && !rows.length) {
    return <EmptyState title="No staff here yet" description="No one matches this filter. Try another role, or add a staff member." />;
  }
  return (
    <>
      <Table label="Staff" className="min-w-[860px]">
        <THead>
          <tr>
            <TH>Person</TH>
            <TH>Role</TH>
            <TH>Makerspace</TH>
            <TH>Access</TH>
            <TH><span className="sr-only">Actions</span></TH>
          </tr>
        </THead>
        <TBody>
          {loading ? <SkeletonRows rows={4} cols={5} /> : rows.map((membership) => {
            const own = membership.user.username === currentUsername;
            const isProtected = !isSuperadmin && (own || roleManagesMakerspace(roles, membership.assigned_role?.id, membership.role));
            return (
              <TR key={membership.id}>
                <TD>
                  <div className="flex min-w-0 items-center gap-3">
                    <span aria-hidden="true"><Avatar name={membership.user.username} size="sm" /></span>
                    <div className="min-w-0">
                      <span className="block max-w-48 break-words font-semibold text-ink">{membership.user.username}</span>
                      {membership.user.email ? <span className="block max-w-56 break-all text-caption text-ink-muted">{membership.user.email}</span> : null}
                    </div>
                  </div>
                </TD>
                <TD>{roleLabel(membership)}</TD>
                <TD className="text-ink-secondary">{makerspaceNames.get(membership.makerspace_id) ?? membership.makerspace_slug}</TD>
                <TD><AccessChip status={membership.user.access_status} /></TD>
                <TD>
                  <div className="flex flex-wrap justify-end gap-2">
                    {isProtected ? <span className="text-caption text-ink-muted">{own ? "You" : "Managed by a platform admin"}</span> : <>
                      <Button size="sm" disabled={!assignableRoles.length} onClick={() => openChange(membership)}>Change role</Button>
                      {isSuperadmin ? <Button size="sm" variant="danger" onClick={() => onRestrict(membership)}>Restrict…</Button> : null}
                      {own ? null : <Button size="sm" onClick={() => onResetPassword(membership)}>Reset password</Button>}
                      {isSuperadmin ? <Button size="sm" disabled={membership.user.access_status === "active"} onClick={() => onRestore(membership)}>Restore</Button> : null}
                      <Button size="sm" variant="danger-quiet" onClick={() => onRevoke(membership)}>Revoke…</Button>
                    </>}
                  </div>
                </TD>
              </TR>
            );
          })}
        </TBody>
      </Table>
      <ChangeRoleModal target={changeTarget} roleId={roleId} roles={assignableRoles} pending={assignPending} error={assignError} onClose={() => setChangeTarget(null)} onChange={setRoleId} onSubmit={submitChange} />
    </>
  );
}

function ChangeRoleModal({ target, roleId, roles, pending, error, onClose, onChange, onSubmit }: {
  target: StaffMembershipRow | null;
  roleId: number | "";
  roles: StaffRole[];
  pending: boolean;
  error: string;
  onClose: () => void;
  onChange: (roleId: number) => void;
  onSubmit: () => void;
}) {
  useEffect(() => { if (target && roleId === "" && roles[0]) onChange(roles[0].id); }, [target, roleId, roles, onChange]);
  return (
    <Modal
      open={Boolean(target)}
      onClose={onClose}
      title={target ? `Change role for ${target.user.username}` : "Change role"}
      size="sm"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={pending} onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={roleId === ""} loading={pending} loadingLabel="Saving…" onClick={onSubmit}>Save role</Button>
        </div>
      )}
    >
      <div className="grid gap-3">
        <Field label="Role" helperText="Their console changes the next time they load it.">
          <Dropdown value={String(roleId)} onChange={(event) => onChange(Number(event.target.value))}>
            {roleId === "" ? <option value="" disabled>Select a role</option> : null}
            {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
          </Dropdown>
        </Field>
        <ErrorText message={error} />
      </div>
    </Modal>
  );
}

const accessTones: Record<string, StatusTone> = { active: "success", restricted: "warning" };

function AccessChip({ status }: { status: string }) {
  const words = status.replace(/_/g, " ");
  return <StatusChip size="sm" tone={accessTones[status] ?? "danger"}>{words.charAt(0).toUpperCase() + words.slice(1)}</StatusChip>;
}

function roleLabel(membership: StaffMembershipRow) {
  return membership.assigned_role?.name ?? membership.role.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

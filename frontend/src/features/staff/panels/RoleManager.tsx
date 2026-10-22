import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import {
  Button,
  Card,
  CardHeader,
  Chip,
  ConfirmDialog,
  EmptyState,
  ErrorText,
  SkeletonRows,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
  useToast,
} from "../../../components/ui";
import { capabilitiesPath, deleteRole, listCapabilities, type Capability, type StaffRole } from "./rolesApi";
import { RoleEditor } from "./RoleEditor";
import { errorText, useStaffGet } from "./shared";

export function RoleManager({ msId, actorActions, isSuperadmin, onRolesChanged }: {
  msId: number;
  actorActions: readonly string[];
  isSuperadmin: boolean;
  onRolesChanged: () => void;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const roles = useStaffGet<StaffRole[]>(["staff", "roles", msId], `/admin/makerspaces/${msId}/roles`);
  // The plain catalog labels the table and seeds a NEW role.
  const capabilities = useStaffGet<Capability[]>(["staff", "capabilities", msId], capabilitiesPath(msId));
  const [editing, setEditing] = useState<StaffRole | null | undefined>();
  const [deleteError, setDeleteError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<StaffRole | null>(null);
  // Editing an existing role reads the role-scoped catalog, which still lists the grants it
  // holds for a switched-off module; the plain catalog would hide (and so drop) them.
  const editingId = editing ? editing.id : null;
  const roleCatalog = useQuery({
    queryKey: ["staff", "capabilities", msId, editingId],
    queryFn: () => listCapabilities(msId, editingId),
    enabled: editingId !== null,
  });
  const editorCapabilities = editing
    ? roleCatalog.data ?? (roleCatalog.isError ? capabilities.data : undefined)
    : capabilities.data;
  const labels = new Map((capabilities.data ?? []).map((item) => [item.value, item.label]));
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["staff", "roles", msId] });
    onRolesChanged();
  };
  const remove = useMutation({
    mutationFn: (role: StaffRole) => deleteRole(msId, role.id),
    onSuccess: (_data, role) => {
      showToast(`${role.name} deleted`, { tone: "success" });
      refresh();
    },
    onError: (error) => {
      const message = errorText(error, "Couldn't delete the role");
      setDeleteError(message);
      showToast(message, { tone: "error" });
    },
  });
  const openEditor = (role: StaffRole | null) => {
    setDeleteError("");
    setEditing(role);
  };

  return (
    <Card as="section" aria-labelledby={`roles-${msId}-title`}>
      <CardHeader
        title={<span id={`roles-${msId}-title`}>Roles</span>}
        description="Each role is a set of capabilities. Assign one to every staff member."
        action={<Button size="sm" startIcon={<Plus />} onClick={() => openEditor(null)}>New role</Button>}
      />
      <div className="grid gap-3">
        <ErrorText message={roles.error?.message ?? deleteError} />
        {!roles.isLoading && !roles.error && !roles.data?.length ? (
          <EmptyState
            title="No roles yet"
            description="Create a role, then assign it to staff."
            action={<Button size="sm" onClick={() => openEditor(null)}>New role</Button>}
          />
        ) : (
          <Table label="Roles" className="min-w-[720px]">
            <THead>
              <tr>
                <TH>Role</TH>
                <TH>Members</TH>
                <TH>Capabilities</TH>
                <TH><span className="sr-only">Actions</span></TH>
              </tr>
            </THead>
            <TBody>
              {roles.isLoading ? <SkeletonRows rows={3} cols={4} /> : null}
              {roles.data?.map((role) => (
                <TR key={role.id}>
                  <TD>
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="font-semibold text-ink">{role.name}</span>
                      <Chip size="sm" tone={role.is_default ? "neutral" : "info"}>{role.is_default ? "Default" : "Custom"}</Chip>
                      {role.is_protected ? <Chip size="sm" tone="outline">Protected</Chip> : null}
                    </div>
                  </TD>
                  <TD className="whitespace-nowrap text-ink-secondary">{memberCount(role.member_count)}</TD>
                  <TD className="max-w-md text-caption text-ink-muted">
                    {role.granted_actions.map((action) => labels.get(action) ?? action).join(", ") || "No capabilities"}
                  </TD>
                  <TD>
                    <div className="flex justify-end gap-2">
                      <Button size="sm" onClick={() => openEditor(role)}>Edit</Button>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={role.is_protected || role.member_count > 0 || remove.isPending}
                        title={role.is_protected ? "Protected defaults can't be deleted" : role.member_count > 0 ? "Reassign its members first" : undefined}
                        onClick={() => setPendingDelete(role)}
                      >
                        Delete…
                      </Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>
      {editing !== undefined ? (
        <RoleEditor
          msId={msId}
          role={editing}
          capabilities={editorCapabilities ?? []}
          loading={editorCapabilities === undefined}
          actorActions={actorActions}
          isSuperadmin={isSuperadmin}
          onClose={() => setEditing(undefined)}
          onSaved={() => { setEditing(undefined); refresh(); }}
        />
      ) : null}
      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete role?"
        message={pendingDelete ? `${pendingDelete.name} will be removed from this makerspace. This can't be undone.` : "Delete this role?"}
        confirmLabel="Delete role"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => {
          if (pendingDelete) remove.mutate(pendingDelete, { onSuccess: () => setPendingDelete(null) });
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </Card>
  );
}

function memberCount(count: number) {
  return count === 1 ? "1 member" : `${count} members`;
}

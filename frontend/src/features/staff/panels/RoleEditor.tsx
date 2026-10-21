import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { Button, Callout, CheckboxCard, Field, FilterChip, Input, Modal, Skeleton, useToast } from "../../../components/ui";
import { StructuredApiError } from "../../../lib/api";
import { createRole, updateRole, type Capability, type StaffRole } from "./rolesApi";
import { RoleMachineScopeEditor } from "./RoleMachineScopeEditor";
import { errorText } from "./shared";

const presets: { label: string; actions: string[] }[] = [
  { label: "Space Manager", actions: ["view_inventory", "edit_inventory", "manage_qr", "accept_request", "reject_request", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence", "manage_printing", "manage_machines", "view_audit", "manage_events", "manage_bookings", "manage_makerspace"] },
  { label: "Inventory Manager", actions: ["view_inventory", "edit_inventory", "manage_qr", "accept_request", "reject_request", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence", "view_audit"] },
  { label: "Machine Manager", actions: ["manage_machines"] },
  { label: "Front Desk", actions: ["view_inventory", "assign_box", "issue_request", "issue_direct_loan", "return_request", "upload_evidence"] },
];

export function RoleEditor({ msId, role, capabilities, loading = false, actorActions, isSuperadmin, onClose, onSaved }: {
  msId: number;
  role: StaffRole | null;
  capabilities: Capability[];
  /** The catalog for this role is still loading. */
  loading?: boolean;
  actorActions: readonly string[];
  isSuperadmin: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { showToast } = useToast();
  const [name, setName] = useState("");
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [preset, setPreset] = useState("");
  const canManageRoles = isSuperadmin || actorActions.includes("manage_makerspace");
  const grouped = useMemo(() => {
    const groups = new Map<string, Capability[]>();
    capabilities.forEach((capability) => groups.set(capability.group, [...(groups.get(capability.group) ?? []), capability]));
    return groups;
  }, [capabilities]);

  useEffect(() => {
    setName(role?.name ?? "");
    setChecked(new Set(role?.granted_actions ?? []));
  }, [role?.id, role?.name, role?.granted_actions]);

  // An edit PATCHes only what changed. Re-sending an unchanged name or action list makes the
  // server re-validate fields the actor did not touch (a protected role's locked name, an
  // action this actor cannot grant but the role already holds) and refuse the whole save.
  const patch = role ? rolePatch(role, name.trim(), checked) : {};
  const unchanged = Boolean(role) && Object.keys(patch).length === 0;
  const save = useMutation({
    mutationFn: () => {
      if (role) return updateRole(msId, role.id, patch);
      const granted_actions = capabilities.filter((item) => item.grantable && checked.has(item.value)).map((item) => item.value);
      return createRole(msId, { name: name.trim(), granted_actions });
    },
    onSuccess: () => {
      showToast(role ? "Role saved" : "Role created", { tone: "success" });
      onSaved();
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the role"), { tone: "error" }),
  });
  const errorBody: Record<string, unknown> = save.error instanceof StructuredApiError ? save.error.body : {};
  const nameError = fieldError(errorBody.name);
  const actionsError = fieldError(errorBody.granted_actions);
  const disabled = save.isPending || loading || !name.trim() || !canManageRoles || unchanged;

  const applyPreset = (label: string, actions: string[]) => {
    setPreset(label);
    setChecked(new Set(actions.filter((action) => capabilities.some((item) => item.value === action && item.grantable))));
  };
  const toggle = (value: string, enabled: boolean) => {
    if (!enabled) return;
    setPreset("");
    setChecked((current) => {
      const next = new Set(current);
      if (next.has(value)) next.delete(value); else next.add(value);
      return next;
    });
  };

  return (
    <Modal
      open
      onClose={onClose}
      title={role ? `Edit ${role.name}` : "New role"}
      description="Pick what people with this role can do."
      size="xl"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={save.isPending} onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={disabled} loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>Save role</Button>
        </div>
      )}
    >
      <div className="grid gap-5">
        {role?.is_protected ? (
          <Callout tone="info" title="Protected default role">It can&apos;t be deleted, and its core capabilities are locked.</Callout>
        ) : null}
        {!role ? (
          <div className="grid gap-2">
            <span className="text-label text-ink">Start from</span>
            <div className="flex flex-wrap gap-2">
              {presets.map((item) => (
                <FilterChip key={item.label} selected={preset === item.label} onClick={() => applyPreset(item.label, item.actions)}>
                  {item.label}
                </FilterChip>
              ))}
            </div>
          </div>
        ) : null}
        <Field label="Name" error={nameError || undefined}>
          <Input value={name} onChange={(event) => setName(event.target.value)} />
        </Field>
        {actionsError ? <p className="text-caption text-danger-fg" role="alert">{actionsError}</p> : null}
        {loading ? (
          <div className="grid gap-3" aria-busy="true">
            <Skeleton className="h-5 w-40" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : Array.from(grouped.entries()).map(([group, items]) => (
          <fieldset key={group} className="grid gap-2">
            <legend className="mb-2 text-title text-ink">{group}</legend>
            <div className="grid gap-2 md:grid-cols-2">
              {items.map((item) => (
                <CheckboxCard
                  key={item.value}
                  checked={checked.has(item.value)}
                  disabled={!item.grantable}
                  onCheckedChange={() => toggle(item.value, item.grantable)}
                  label={item.label}
                  description={(
                    <>
                      {item.description}
                      {!item.grantable ? (
                        <span className="block text-danger-fg">{item.lock_reason ?? "Your role can't grant this capability."}</span>
                      ) : null}
                    </>
                  )}
                />
              ))}
            </div>
          </fieldset>
        ))}
        {role ? (
          <RoleMachineScopeEditor msId={msId} roleId={role.id} />
        ) : checked.has("manage_machines") ? (
          <Callout tone="info" title="Machine access is set per role">
            Save this role, then reopen it to choose which machines it can manage. Until then it can manage none.
          </Callout>
        ) : null}
        {save.error && !nameError && !actionsError ? <p className="text-caption text-danger-fg" role="alert">{save.error.message}</p> : null}
      </div>
    </Modal>
  );
}

function rolePatch(role: StaffRole, name: string, checked: Set<string>) {
  const patch: { name?: string; granted_actions?: string[] } = {};
  if (name !== role.name) patch.name = name;
  const original = new Set(role.granted_actions);
  if (original.size !== checked.size || [...checked].some((action) => !original.has(action))) {
    patch.granted_actions = [...checked];
  }
  return patch;
}

function fieldError(value: unknown) {
  if (Array.isArray(value)) return value.join(" ");
  return typeof value === "string" ? value : "";
}

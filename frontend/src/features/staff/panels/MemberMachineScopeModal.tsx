import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, CheckboxField, ErrorText, Modal, Skeleton, useToast } from "../../../components/ui";
import { getMemberMachineScope, setMemberMachineScope, type MemberMachineScope, type StaffMembershipRow } from "./rolesApi";
import { errorText } from "./shared";

const scopeKey = (msId: number, membershipId: number) => ["staff", "member-machine-scope", msId, membershipId] as const;

/**
 * The machine types one staff member manages on top of their role's.
 *
 * Personal types only widen a role that already has the Machines capability; the server
 * never lets them grant it. So the role's own types are shown ticked and locked ("via
 * role"), and a member whose role covers everything, or lacks Machines, gets an
 * explanation instead of boxes that would do nothing.
 */
export function MemberMachineScopeModal({ target, onClose }: { target: StaffMembershipRow | null; onClose: () => void }) {
  const msId = target?.makerspace_id ?? 0;
  const membershipId = target?.id ?? 0;
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const scope = useQuery({
    queryKey: scopeKey(msId, membershipId),
    queryFn: () => getMemberMachineScope(msId, membershipId),
    enabled: target !== null,
  });
  const [selected, setSelected] = useState<Set<number>>(new Set());

  useEffect(() => {
    if (scope.data) setSelected(new Set(scope.data.machine_type_ids));
  }, [scope.data]);

  const save = useMutation({
    mutationFn: () => setMemberMachineScope(msId, membershipId, { machine_type_ids: [...selected] }),
    onSuccess: (data) => {
      queryClient.setQueryData(scopeKey(msId, membershipId), data);
      showToast("Machine types saved", { tone: "success" });
      onClose();
    },
    onError: (error) => showToast(errorText(error, "Couldn't save machine types"), { tone: "error" }),
  });

  const editable = scope.data?.scoping_applies === true;
  return (
    <Modal
      open={target !== null}
      onClose={onClose}
      title={target ? `Machine types for ${target.user.username}` : "Machine types"}
      size="sm"
      footer={(
        <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
          <Button variant="secondary" disabled={save.isPending} onClick={onClose}>{editable ? "Cancel" : "Close"}</Button>
          {editable ? <Button variant="primary" loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>Save machine types</Button> : null}
        </div>
      )}
    >
      {scope.isLoading ? (
        <div className="grid gap-2" aria-busy="true">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-12 w-full" />
        </div>
      ) : scope.error ? (
        <ErrorText message={scope.error.message} />
      ) : scope.data ? (
        <ScopeBody scope={scope.data} selected={selected} onToggle={(id) => setSelected((current) => {
          const next = new Set(current);
          if (next.has(id)) next.delete(id); else next.add(id);
          return next;
        })} />
      ) : null}
    </Modal>
  );
}

function ScopeBody({ scope, selected, onToggle }: { scope: MemberMachineScope; selected: Set<number>; onToggle: (id: number) => void }) {
  if (scope.role_covers_all) {
    return <Callout tone="info" title="Covers every machine">Their role already manages every machine type in this makerspace.</Callout>;
  }
  if (!scope.scoping_applies) {
    return (
      <Callout tone="warning" title="Their role has no Machines capability">
        Personal machine types only work on top of a role that includes Machines. Give them such a role first.
      </Callout>
    );
  }
  const viaRole = new Set(scope.role_machine_type_ids);
  return (
    <fieldset className="grid gap-3">
      <legend className="mb-1 text-body-ui text-ink-muted">
        They can manage only the types ticked here, plus any their role covers. Ticking a type also covers machines of that type added later.
      </legend>
      {!scope.available_machine_types.length ? (
        <span className="text-caption text-ink-muted">No machine types yet.</span>
      ) : (
        <div className="grid gap-2">
          {scope.available_machine_types.map((option) => (
            <CheckboxField
              key={option.id}
              checked={viaRole.has(option.id) || selected.has(option.id)}
              disabled={viaRole.has(option.id)}
              onCheckedChange={() => onToggle(option.id)}
              label={option.label}
              description={viaRole.has(option.id) ? "Via role" : undefined}
            />
          ))}
        </div>
      )}
    </fieldset>
  );
}

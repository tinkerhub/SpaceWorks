import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import { Button, Callout, CheckboxField, ErrorText, Skeleton, useToast } from "../../../components/ui";
import { getRoleMachineScope, setRoleMachineScope, type MachineScopeOption } from "./rolesApi";
import { errorText } from "./shared";

/**
 * Which machines a role's "Machines" capability actually reaches.
 *
 * Machine scoping fails closed on the server, so a role granted `manage_machines` with
 * nothing ticked here can manage nothing. That is deliberate, but it makes this editor
 * load-bearing rather than optional — without it the only ways to grant machine access
 * would be the Django `/control/` console (which staff cannot reach) or the shell.
 *
 * Saved separately from the role's capabilities because it needs a role id: a role that
 * does not exist yet has nothing to link to.
 */
export function RoleMachineScopeEditor({ msId, roleId }: { msId: number; roleId: number }) {
  const scope = useQuery({
    queryKey: ["staff", "role-machine-scope", msId, roleId],
    queryFn: () => getRoleMachineScope(msId, roleId),
  });
  const [types, setTypes] = useState<Set<number>>(new Set());
  const [machines, setMachines] = useState<Set<number>>(new Set());
  const [saved, setSaved] = useState(false);
  const { showToast } = useToast();

  useEffect(() => {
    if (!scope.data) return;
    setTypes(new Set(scope.data.machine_type_ids));
    setMachines(new Set(scope.data.machine_ids));
  }, [scope.data]);

  const save = useMutation({
    mutationFn: () => setRoleMachineScope(msId, roleId, {
      machine_type_ids: [...types],
      machine_ids: [...machines],
    }),
    onSuccess: () => {
      setSaved(true);
      showToast("Machine scope saved", { tone: "success" });
      void scope.refetch();
    },
    onError: (error) => showToast(errorText(error, "Couldn't save the machine scope"), { tone: "error" }),
  });

  if (scope.isLoading) {
    return (
      <div className="grid gap-2" aria-busy="true">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-12 w-full" />
      </div>
    );
  }
  if (scope.error) return <ErrorText message={scope.error.message} />;
  if (!scope.data) return null;

  if (!scope.data.scoping_applies) {
    return (
      <section className="grid gap-1 rounded-lg border border-line bg-subtle p-4">
        <h3 className="text-title text-ink">Machine scope</h3>
        <p className="text-body-ui text-ink-muted">
          This role either administers the whole makerspace or grants no machine capability,
          so it is not limited to particular machines.
        </p>
      </section>
    );
  }

  const toggle = (set: Set<number>, apply: (next: Set<number>) => void, id: number) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    setSaved(false);
    apply(next);
  };
  const nothingSelected = types.size === 0 && machines.size === 0;

  return (
    <section className="grid gap-4 rounded-lg border border-line p-4">
      <div className="grid gap-1">
        <h3 className="text-title text-ink">Machine scope</h3>
        <p className="text-body-ui text-ink-muted">
          This role can only manage the machine types and machines ticked here. Ticking a
          type also covers machines of that type added later.
        </p>
      </div>
      {nothingSelected ? (
        <Callout tone="warning" title="Nothing selected">This role currently can't manage any machine.</Callout>
      ) : null}
      <OptionList
        title="Machine types"
        options={scope.data.available_machine_types}
        selected={types}
        onToggle={(id) => toggle(types, setTypes, id)}
        describe={(option) => (option.is_builtin ? "Built-in" : "This makerspace")}
      />
      <OptionList
        title="Individual machines"
        options={scope.data.available_machines}
        selected={machines}
        onToggle={(id) => toggle(machines, setMachines, id)}
        describe={(option) => (option.is_active === false ? "Retired" : "")}
      />
      <div className="flex flex-wrap items-center justify-end gap-3">
        {saved && !save.isPending ? <span className="text-caption text-ink-muted" role="status">Saved</span> : null}
        {save.error ? <span className="text-caption text-danger-fg">{save.error.message}</span> : null}
        <Button variant="secondary" loading={save.isPending} loadingLabel="Saving…" onClick={() => save.mutate()}>
          Save machine scope
        </Button>
      </div>
    </section>
  );
}

function OptionList({ title, options, selected, onToggle, describe }: {
  title: string;
  options: MachineScopeOption[];
  selected: Set<number>;
  onToggle: (id: number) => void;
  describe: (option: MachineScopeOption) => string;
}) {
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-label text-ink">{title}</legend>
      {!options.length ? (
        <span className="text-caption text-ink-muted">None available.</span>
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          {options.map((option) => (
            <CheckboxField
              key={option.id}
              checked={selected.has(option.id)}
              onCheckedChange={() => onToggle(option.id)}
              label={option.label}
              description={describe(option) || undefined}
            />
          ))}
        </div>
      )}
    </fieldset>
  );
}

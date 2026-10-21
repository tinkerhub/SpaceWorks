import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  Avatar,
  Button,
  Chip,
  ConfirmDialog,
  Dropdown,
  EmptyState,
  Field,
  SectionHeading,
  SkeletonRows,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from "../../../../components/ui";
import {
  addMachineOperator,
  collectionResults,
  deleteMachineOperator,
  getMachineOperators,
  getOperatorCandidates,
  machineKeys,
  updateMachineOperator,
  type MachineAccessLevel,
  type MachineOperator,
} from "../../machinesApi";
import { humanize, useNotify, When } from "./machineUi";

const ACCESS_LEVELS: MachineAccessLevel[] = ["operate", "manage", "full"];

export function OperatorsTab({ machineId, canDelegate, retired = false }: { machineId: number; canDelegate: boolean; retired?: boolean }) {
  const queryClient = useQueryClient();
  const notify = useNotify();
  const [userId, setUserId] = useState("");
  const [accessLevel, setAccessLevel] = useState<MachineAccessLevel>("operate");
  const [removing, setRemoving] = useState<MachineOperator | null>(null);
  // The server refuses operator changes on a retired machine.
  const canChange = canDelegate && !retired;
  const operators = useQuery({
    queryKey: machineKeys.operators(machineId),
    queryFn: () => getMachineOperators(machineId),
  });
  const candidates = useQuery({
    queryKey: machineKeys.operatorCandidates(machineId),
    queryFn: () => getOperatorCandidates(machineId),
    enabled: canDelegate,
  });
  const items = collectionResults(operators.data);
  const assignedUsers = new Set(items.map((operator) => operator.user));
  const eligibleCandidates = (candidates.data ?? []).filter((candidate) => !assignedUsers.has(candidate.user_id));
  const refresh = () => queryClient.invalidateQueries({ queryKey: machineKeys.operators(machineId) });
  const add = useMutation({
    mutationFn: () => addMachineOperator(machineId, { user_id: Number(userId), access_level: accessLevel }),
    onSuccess: async (operator) => {
      notify.success(`${operator?.username ?? "Operator"} added`);
      setUserId("");
      await refresh();
    },
    onError: (error) => notify.failure("Couldn't add the operator.", error),
  });
  const changeLevel = useMutation({
    mutationFn: ({ user, level }: { user: number; level: MachineAccessLevel }) => updateMachineOperator(machineId, user, level),
    onSuccess: async (operator) => {
      notify.success(`${operator?.username ?? "Operator"} now has ${operator?.access_level ?? "new"} access`);
      await refresh();
    },
    onError: (error) => notify.failure("Couldn't change the access level.", error),
  });
  const remove = useMutation({
    mutationFn: (userPk: number) => deleteMachineOperator(machineId, userPk),
    onSuccess: async () => {
      notify.success(`${removing?.username ?? "Operator"} removed`);
      setRemoving(null);
      await refresh();
    },
    onError: (error) => notify.failure("Couldn't remove the operator.", error),
  });

  return (
    <section className="grid gap-4">
      <SectionHeading as="h3" title="Operators" description="People who can run this machine, and how much they can change." />
      {canChange ? (
        <form className="grid gap-3 rounded-lg border border-line bg-subtle p-4 sm:grid-cols-[minmax(0,1fr)_12rem_auto] sm:items-end"
          onSubmit={(event) => { event.preventDefault(); add.mutate(); }}>
          <Field label="Member">
            <Dropdown value={userId} disabled={candidates.isLoading} onChange={(event) => setUserId(event.target.value)} required>
              <option value="" disabled>{candidates.isLoading ? "Loading members…" : eligibleCandidates.length ? "Select a member" : "No one else to add"}</option>
              {eligibleCandidates.map((candidate) => (
                <option key={candidate.user_id} value={String(candidate.user_id)}>
                  {candidate.display_name ? `${candidate.display_name} (${candidate.username})` : candidate.username}
                </option>
              ))}
            </Dropdown>
          </Field>
          <Field label="Access level">
            <Dropdown value={accessLevel} onChange={(event) => setAccessLevel(event.target.value as MachineAccessLevel)}>
              {ACCESS_LEVELS.map((level) => <option key={level} value={level}>{humanize(level)}</option>)}
            </Dropdown>
          </Field>
          <Button variant="primary" type="submit" loading={add.isPending} loadingLabel="Adding…" disabled={!userId}>Add operator</Button>
        </form>
      ) : null}
      {canDelegate && retired ? <p className="text-caption text-ink-muted">Operators can't be changed while the machine is retired.</p> : null}
      {[candidates.error, add.error, changeLevel.error, remove.error].map((error, index) => error instanceof Error
        ? <p key={index} className="text-caption text-danger-fg">{error.message}</p> : null)}
      {operators.error instanceof Error ? <EmptyState tone="error" title="Couldn't load operators" description={operators.error.message} /> : null}
      {!operators.isLoading && !operators.error && !items.length ? (
        <EmptyState title="No operators assigned" description={canChange ? "Add a member above to let them run this machine." : "No one has been given access to this machine yet."} />
      ) : null}
      {operators.isLoading || items.length ? (
        <Table label="Operators">
          <THead>
            <tr><TH>Member</TH><TH>Access</TH><TH>Assigned</TH>{canChange ? <TH><span className="sr-only">Actions</span></TH> : null}</tr>
          </THead>
          <TBody>
            {operators.isLoading ? <SkeletonRows rows={2} cols={canChange ? 4 : 3} /> : null}
            {items.map((operator) => (
              <TR key={operator.id}>
                <TD>
                  <span className="flex min-w-0 items-center gap-2.5">
                    <span aria-hidden="true" className="inline-flex"><Avatar name={operator.username} size="sm" /></span>
                    <span className="truncate font-semibold">{operator.username}</span>
                  </span>
                </TD>
                <TD className="min-w-36">
                  {canChange ? (
                    <Dropdown
                      aria-label={`Access level for ${operator.username}`}
                      value={operator.access_level}
                      disabled={changeLevel.isPending}
                      onChange={(event) => changeLevel.mutate({ user: operator.user, level: event.target.value as MachineAccessLevel })}
                    >
                      {ACCESS_LEVELS.map((level) => <option key={level} value={level}>{humanize(level)}</option>)}
                    </Dropdown>
                  ) : <Chip size="sm">{humanize(operator.access_level)}</Chip>}
                </TD>
                <TD className="whitespace-nowrap text-caption text-ink-muted">
                  <When value={operator.assigned_at} />
                  {operator.assigned_by_username ? <span className="block">by {operator.assigned_by_username}</span> : null}
                </TD>
                {canChange ? (
                  <TD className="text-right">
                    <Button variant="danger-quiet" size="sm" onClick={() => setRemoving(operator)}>Remove…</Button>
                  </TD>
                ) : null}
              </TR>
            ))}
          </TBody>
        </Table>
      ) : null}
      <ConfirmDialog
        open={removing !== null}
        title={`Remove ${removing?.username ?? "this operator"}?`}
        message="They lose access to this machine straight away. You can add them again later."
        confirmLabel="Remove operator"
        tone="danger"
        pending={remove.isPending}
        onConfirm={() => { if (removing) remove.mutate(removing.user); }}
        onCancel={() => setRemoving(null)}
      />
    </section>
  );
}

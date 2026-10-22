import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Dropdown, ErrorText, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { ScopePicker, type ScopeOptions } from "./NotificationScopePicker";
import {
  type DestinationScope,
  type RecipientKind,
  type RecipientRule,
  type RecipientRulesResponse,
  EMPTY_SCOPE,
} from "./notificationDestinationTypes";

type Draft = {
  kind: RecipientKind;
  role_id: number | null;
  user_id: number | null;
  scope: DestinationScope;
};

export function EventRecipients({
  data,
  delegated,
  event,
  feature,
  makerspaceId,
  options,
  path,
}: {
  data: RecipientRulesResponse;
  delegated: boolean;
  event: string;
  feature: string;
  makerspaceId: number;
  options: ScopeOptions;
  path: string;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const saved = useMemo(
    () => data.rules.filter((rule) => rule.feature === feature && rule.event === event),
    [data.rules, event, feature],
  );
  const [drafts, setDrafts] = useState<Draft[] | null>(null);
  const [error, setError] = useState("");
  const rules = drafts ?? saved.map(toDraft);
  const marker = data.managed_policy_markers.find(
    (item) => item.feature === feature && item.event === event,
  );
  const hasUnscopedRule = delegated && rules.some((rule) => scopeCount(rule.scope) === 0);

  const save = useMutation({
    mutationFn: (next: Draft[]) =>
      staffRequest<RecipientRulesResponse>(path, {
        method: "PUT",
        body: JSON.stringify({ feature, event, rules: next }),
      }),
    onSuccess: () => {
      setDrafts(null);
      showToast("Recipients saved", { tone: "success" });
      queryClient.invalidateQueries({
        queryKey: ["notification-recipient-rules", makerspaceId],
      });
    },
    onError: (err: unknown) => {
      const message = err instanceof Error && err.message ? err.message : "Couldn't save recipients.";
      setError(message);
      showToast(message, { tone: "error" });
    },
  });

  const update = (next: Draft[]) => {
    setDrafts(next);
    setError("");
  };

  return (
    <div className="grid gap-3 rounded-lg border border-line bg-subtle p-4">
      {rules.length === 0 ? (
        <p className="text-body-ui text-ink-muted">
          {delegated
            ? "No recipient is selected in your scoped partition."
            : "Nobody selected — everyone whose role covers this area is notified."}
        </p>
      ) : null}
      {marker ? (
        <p className="text-body-ui text-ink-muted">
          {/* Deliberately names no author. A hidden remainder used to be a Space
              Manager's row by construction; a shared requester/members row can now hold
              another maintainer's links too, so claiming a manager wrote it would be a
              statement about a colleague that is often false. */}
          Another policy also applies to this event, scoped outside your machines. Its
          recipients and scope are hidden; your changes will not replace it.
        </p>
      ) : null}

      {rules.map((rule, index) => (
        <div className="grid gap-3 border-b border-line pb-3 last:border-0 last:pb-0" key={index}>
          <RecipientTarget
            data={data}
            index={index}
            rule={rule}
            rules={rules}
            update={update}
          />
          <ScopePicker
            onChange={(scope) =>
              update(rules.map((item, position) => position === index ? { ...item, scope } : item))
            }
            options={options}
            scopeRequired={delegated}
            scope={rule.scope}
          />
        </div>
      ))}

      <ErrorText message={error} />
      {hasUnscopedRule ? (
        <p className="text-sm text-danger-fg">
          Each delegated rule needs at least one machine or machine type.
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2.5">
        <Button
          variant="primary"
          disabled={drafts === null || hasUnscopedRule}
          loading={save.isPending}
          loadingLabel="Saving…"
          onClick={() => save.mutate(rules)}
        >
          Save recipients
        </Button>
        <Button
          variant="secondary"
          onClick={() => update([
            ...rules,
            { kind: "role", role_id: null, user_id: null, scope: EMPTY_SCOPE },
          ])}
        >
          Add recipient
        </Button>
        {drafts !== null ? (
          <Button variant="quiet" onClick={() => setDrafts(null)}>
            Discard changes
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function RecipientTarget({ data, index, rule, rules, update }: {
  data: RecipientRulesResponse;
  index: number;
  rule: Draft;
  rules: Draft[];
  update: (next: Draft[]) => void;
}) {
  const replace = (fields: Partial<Draft>) =>
    update(rules.map((item, position) => position === index ? { ...item, ...fields } : item));
  return (
    <div className="flex flex-wrap items-center gap-2.5">
      <div className="w-full sm:w-56">
        <Dropdown
          aria-label={`Recipient ${index + 1} type`}
          onChange={(changed) => replace({
            kind: changed.target.value as RecipientKind,
            role_id: null,
            user_id: null,
          })}
          value={rule.kind}
        >
          <option value="role">A role</option>
          <option value="user">A named member</option>
          <option value="members">All members</option>
          <option value="requester">The person it is about</option>
        </Dropdown>
      </div>
      {rule.kind === "role" ? (
        <div className="w-full sm:w-56">
          <Dropdown
            aria-label={`Recipient ${index + 1} role`}
            onChange={(changed) => replace({ role_id: Number(changed.target.value) })}
            value={rule.role_id == null ? "" : String(rule.role_id)}
          >
            <option value="" disabled>Choose a role…</option>
            {data.roles.map((role) => <option key={role.id} value={String(role.id)}>{role.name}</option>)}
          </Dropdown>
        </div>
      ) : null}
      {rule.kind === "user" ? (
        <div className="w-full sm:w-56">
          <Dropdown
            aria-label={`Recipient ${index + 1} member`}
            onChange={(changed) => replace({ user_id: Number(changed.target.value) })}
            value={rule.user_id == null ? "" : String(rule.user_id)}
          >
            <option value="" disabled>Choose a member…</option>
            {data.members.map((member) => (
              <option key={member.id} value={String(member.id)}>{member.username}</option>
            ))}
          </Dropdown>
        </div>
      ) : null}
      <Button
        className="ml-auto"
        size="sm"
        variant="danger-quiet"
        aria-label={`Remove recipient ${index + 1}`}
        onClick={() => update(rules.filter((_, position) => position !== index))}
      >
        Remove
      </Button>
    </div>
  );
}

function toDraft(rule: RecipientRule): Draft {
  return {
    kind: rule.kind,
    role_id: rule.role_id,
    user_id: rule.user_id,
    scope: rule.scope ?? EMPTY_SCOPE,
  };
}

function scopeCount(scope: DestinationScope) {
  return scope.machine_type_ids.length + scope.machine_ids.length + scope.category_ids.length;
}

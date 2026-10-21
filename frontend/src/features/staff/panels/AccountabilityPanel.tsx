import { useId, useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Callout, Card, CardHeader, Dialog, ErrorText, Field, Skeleton, Textarea, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { invalidateInventoryViews } from "../queryInvalidation";
import { ProblemReportCard } from "./AccountabilityPanelProblemReport";
import { AnonymousTotals, OverdueList, RepeatOffendersTable, RestrictionsList } from "./AccountabilityPanelSections";
import type { AccountabilityResponse, RestrictionTarget } from "./AccountabilityPanelTypes";
import { errorText, Panel, type Makerspace, useStaffGet } from "./shared";

export function AccountabilityPanel({ makerspace, isSuperadmin }: { makerspace: Makerspace; isSuperadmin: boolean }) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const restrictionFormId = useId();
  const [restrictionTarget, setRestrictionTarget] = useState<RestrictionTarget | null>(null);
  const [restrictionReason, setRestrictionReason] = useState("");
  const report = useStaffGet<AccountabilityResponse>(["accountability", makerspace.id], `/admin/makerspace/${makerspace.id}/accountability`);
  const data = report.data;
  const anonymous = data?.anonymous_accountability;
  const hasAnonymous = Boolean(anonymous && anonymous.total_issues > 0);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["accountability", makerspace.id] });
  };
  const refreshAfterTriage = () => {
    refresh();
    invalidateInventoryViews(queryClient, makerspace.id, makerspace.slug);
    queryClient.invalidateQueries({ queryKey: ["needs-fix-shelf", makerspace.id] });
  };
  const closeRestrictionDialog = () => {
    setRestrictionTarget(null);
    setRestrictionReason("");
  };
  const restrict = useMutation({
    mutationFn: ({ userId, reason }: { userId: number; reason: string; username: string }) =>
      staffRequest(`/admin/users/${userId}/restrict`, {
        method: "POST",
        body: JSON.stringify({ status: "restricted", reason }),
      }),
    // The dialog stays open until the server agrees, so a failure is shown where the
    // reason was typed instead of after the dialog has already gone.
    onSuccess: (_result, vars) => {
      closeRestrictionDialog();
      showToast(`${vars.username} is restricted.`, { tone: "success" });
      refresh();
    },
    onError: (error) => showToast(errorText(error, "Could not restrict requester."), { tone: "error" }),
  });
  const restore = useMutation({
    mutationFn: (target: RestrictionTarget) => staffRequest(`/admin/users/${target.requester_id}/restore-access`, { method: "POST" }),
    onSuccess: (_result, target) => {
      showToast(`Access restored for ${target.username}.`, { tone: "success" });
      refresh();
    },
    onError: (error) => showToast(errorText(error, "Could not restore access."), { tone: "error" }),
  });
  const openRestriction = (target: RestrictionTarget) => {
    restrict.reset();
    setRestrictionReason("");
    setRestrictionTarget(target);
  };
  const submitRestriction = (event: FormEvent) => {
    event.preventDefault();
    const reason = restrictionReason.trim();
    if (restrictionTarget && reason && !restrict.isPending) {
      restrict.mutate({ userId: restrictionTarget.requester_id, reason, username: restrictionTarget.username });
    }
  };

  return (
    <Panel title="Accountability" description="Overdue loans, problem reports from returns, and who keeps damaging or losing hardware.">
      <div className="grid gap-5">
        {report.error ? <Callout tone="danger" role="alert" title="Could not load accountability">{errorText(report.error, "Try again in a moment.")}</Callout> : null}
        <Section title="Overdue loans" loading={report.isLoading}>
          {data ? <OverdueList rows={data.overdue} truncated={data.truncated.overdue} /> : null}
        </Section>

        <Section title="Reported problems" description="Open problem reports from public returns." loading={report.isLoading}>
          {data && !data.problem_reports.length ? <p className="text-body-ui text-ink-muted">No open problem reports from public returns.</p> : null}
          {data?.problem_reports.length ? (
            <div className="grid gap-3">
              {data.problem_reports.map((row) => (
                <ProblemReportCard key={row.id} row={row} makerspace={makerspace} onTriaged={refreshAfterTriage} />
              ))}
              {data.truncated.problem_reports ? <p className="text-caption text-ink-muted">Showing the oldest open reports only.</p> : null}
            </div>
          ) : null}
        </Section>

        <Section title="Repeat offenders" loading={report.isLoading}>
          {data ? (
            <div className="grid gap-3">
              {anonymous && hasAnonymous ? <AnonymousTotals anonymous={anonymous} /> : null}
              <RepeatOffendersTable
                rows={data.repeat_offenders}
                truncated={data.truncated.repeat_offenders}
                isSuperadmin={isSuperadmin}
                hasAnonymous={hasAnonymous}
                restorePending={restore.isPending}
                onRestrict={openRestriction}
                onRestore={(target) => restore.mutate(target)}
              />
            </div>
          ) : null}
        </Section>

        <Section title="Restricted requesters" loading={report.isLoading}>
          {data ? (
            <RestrictionsList rows={data.restrictions} isSuperadmin={isSuperadmin} restorePending={restore.isPending} onRestore={(target) => restore.mutate(target)} />
          ) : null}
          {restore.error ? <ErrorText message={errorText(restore.error, "Could not restore access.")} /> : null}
        </Section>
      </div>
      <Dialog
        open={restrictionTarget !== null}
        onClose={() => { if (!restrict.isPending) closeRestrictionDialog(); }}
        title={`Restrict ${restrictionTarget?.username ?? "requester"}?`}
        description="They won't be able to make new requests until access is restored."
        size="sm"
        footer={(
          <div className="flex flex-col-reverse gap-2.5 sm:flex-row sm:justify-end">
            <Button disabled={restrict.isPending} onClick={closeRestrictionDialog}>Cancel</Button>
            {/* Submit no-ops on a blank reason, so leaving it enabled renders a dead button that
                reports nothing. Disabling states the requirement instead of failing silently. */}
            <Button variant="danger" type="submit" form={restrictionFormId} loading={restrict.isPending} loadingLabel="Restricting…" disabled={!restrictionReason.trim()}>
              Restrict requester
            </Button>
          </div>
        )}
      >
        <form id={restrictionFormId} className="grid gap-3" onSubmit={submitRestriction}>
          <Field label="Reason for restriction" helperText="Shown to staff alongside the restriction.">
            <Textarea rows={4} required value={restrictionReason} onChange={(event) => setRestrictionReason(event.target.value)} />
          </Field>
          {restrict.error ? <ErrorText message={errorText(restrict.error, "Could not restrict requester.")} /> : null}
        </form>
      </Dialog>
    </Panel>
  );
}

function Section({ title, description, loading, children }: { title: string; description?: string; loading: boolean; children: ReactNode }) {
  return (
    <Card as="section">
      <CardHeader title={title} description={description} />
      {loading ? (
        <div className="grid gap-2" aria-busy="true">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : children}
    </Card>
  );
}

import { Button, Callout, EmptyState, StatusChip, Table, TBody, TD, TH, THead, TR } from "../../../components/ui";
import type { AnonymousAccountability, Offender, Overdue, Restriction, RestrictionTarget } from "./AccountabilityPanelTypes";
import { StatusWord } from "./shared";

const plural = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;

function accessTone(status: string) {
  return status === "active" ? "success" : status === "suspended" ? "danger" : "warning";
}

export function OverdueList({ rows, truncated }: { rows: Overdue[]; truncated: boolean }) {
  if (!rows.length) return <EmptyState title="No overdue loans" description="Everything that is out is still within its due date." />;
  return (
    <div className="grid gap-2">
      <Table label="Overdue loans">
        <THead>
          <tr>
            <TH>Item</TH>
            <TH>Borrower</TH>
            <TH>Source</TH>
            <TH>Due</TH>
            <TH className="text-right">Overdue by</TH>
          </tr>
        </THead>
        <TBody>
          {rows.map((row) => (
            <TR key={`${row.type}-${row.reference_id}`}>
              <TD className="font-semibold">{row.label || "(unnamed)"}</TD>
              <TD>{row.requester_username}</TD>
              <TD className="text-ink-secondary">{row.type === "direct" ? "Direct handout" : "Request"}</TD>
              <TD className="whitespace-nowrap text-ink-muted">{new Date(row.due_at).toLocaleDateString(undefined, { dateStyle: "medium" })}</TD>
              <TD className="text-right"><StatusChip tone="danger" size="sm">{plural(row.days_overdue, "day", "days")}</StatusChip></TD>
            </TR>
          ))}
        </TBody>
      </Table>
      {truncated ? <p className="text-caption text-ink-muted">Showing the earliest overdue loans only.</p> : null}
    </div>
  );
}

export function AnonymousTotals({ anonymous }: { anonymous: AnonymousAccountability }) {
  return (
    <Callout tone="warning" title={`Account-less loans: ${plural(anonymous.total_issues, "incident", "incidents")} (${plural(anonymous.total_quantity, "item", "items")})`}>
      {anonymous.damaged} damaged, {anonymous.missing} missing. These have no person to rank or restrict, so they are reported as a total rather than as a row below.
    </Callout>
  );
}

export function RepeatOffendersTable({ rows, truncated, isSuperadmin, hasAnonymous, restorePending, onRestrict, onRestore }: {
  rows: Offender[];
  truncated: boolean;
  isSuperadmin: boolean;
  hasAnonymous: boolean;
  restorePending: boolean;
  onRestrict: (target: RestrictionTarget) => void;
  onRestore: (target: RestrictionTarget) => void;
}) {
  if (!rows.length) {
    return <EmptyState title={hasAnonymous ? "No damage or loss recorded against a named person." : "No damage or loss on record."} />;
  }
  return (
    <div className="grid gap-2">
      <Table label="Repeat offenders" className="min-w-[36rem]">
        <THead>
          <tr>
            <TH>Requester</TH>
            <TH className="text-right">Damaged</TH>
            <TH className="text-right">Missing</TH>
            <TH className="text-right">Total issues</TH>
            <TH>Status</TH>
            {isSuperadmin ? <TH><span className="sr-only">Action</span></TH> : null}
          </tr>
        </THead>
        <TBody>
          {rows.map((row) => (
            <TR key={row.requester_id}>
              <TD className="font-semibold">{row.username}</TD>
              <TD className="text-right tabular-nums">{row.damaged}</TD>
              <TD className="text-right tabular-nums">{row.missing}</TD>
              <TD className="text-right tabular-nums">{row.total_issues} <span className="text-ink-muted">({row.total_quantity} units)</span></TD>
              <TD><StatusWord status={row.access_status} tone={accessTone(row.access_status)} /></TD>
              {isSuperadmin ? (
                <TD className="text-right">
                  {row.access_status === "active" ? (
                    <Button size="sm" variant="danger" onClick={() => onRestrict({ requester_id: row.requester_id, username: row.username })}>
                      Restrict…
                    </Button>
                  ) : (
                    <Button size="sm" disabled={restorePending} onClick={() => onRestore({ requester_id: row.requester_id, username: row.username })}>
                      Restore
                    </Button>
                  )}
                </TD>
              ) : null}
            </TR>
          ))}
        </TBody>
      </Table>
      {truncated ? <p className="text-caption text-ink-muted">Showing the top offenders only.</p> : null}
    </div>
  );
}

export function RestrictionsList({ rows, isSuperadmin, restorePending, onRestore }: {
  rows: Restriction[];
  isSuperadmin: boolean;
  restorePending: boolean;
  onRestore: (target: RestrictionTarget) => void;
}) {
  if (!rows.length) return <EmptyState title="No restricted requesters with accountability records here." />;
  return (
    <ul className="grid gap-2">
      {rows.map((row) => (
        <li key={row.requester_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-canvas px-4 py-3">
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-2 font-semibold text-ink">
              {row.username}
              <StatusWord status={row.access_status} tone={accessTone(row.access_status)} />
            </p>
            {row.restriction_reason ? <p className="mt-1 text-body-ui text-ink-muted">{row.restriction_reason}</p> : null}
          </div>
          {isSuperadmin ? (
            <Button size="sm" disabled={restorePending} onClick={() => onRestore({ requester_id: row.requester_id, username: row.username })}>
              Restore access
            </Button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

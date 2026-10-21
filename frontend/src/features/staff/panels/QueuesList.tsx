import type React from "react";
import { useState } from "react";

import { Button, Chip, EmptyState, Table, TBody, TD, TH, THead, TR } from "../../../components/ui";
import type { HardwareRequest } from "./Queues";
import { formatWhen, hasItemIssues, RequestDetailDrawer, RequestStatus } from "./QueuesRequestDetail";

const ON_LOAN = new Set(["issued", "partially_returned"]);

/**
 * One request per table row: who, what (with the shelf to fetch from), status, due and
 * the row's actions. "Details" opens a drawer with progress, contact, evidence and timeline.
 */
export function RequestList({
  rows,
  actions,
  canViewAudit = false,
  label,
  emptyTitle = "No requests",
  emptyDescription,
}: {
  rows: HardwareRequest[];
  actions: (row: HardwareRequest) => React.ReactNode;
  canViewAudit?: boolean;
  /** Names the table's scroll region. */
  label?: string;
  emptyTitle?: string;
  emptyDescription?: string;
}) {
  const [detailId, setDetailId] = useState<number | null>(null);
  const detail = rows.find((row) => row.id === detailId) ?? null;

  if (!rows.length) return <EmptyState title={emptyTitle} description={emptyDescription} />;
  return (
    <>
      <Table label={label} className="min-w-[720px]">
        <THead>
          <tr>
            <TH>Request</TH>
            <TH>Items</TH>
            <TH>Status</TH>
            <TH>Return due</TH>
            <TH className="text-right">Actions</TH>
          </tr>
        </THead>
        <TBody>
          {rows.map((row) => {
            const overdue = Boolean(row.return_due_at && ON_LOAN.has(row.status) && new Date(row.return_due_at).getTime() < Date.now());
            return (
              <TR key={row.id}>
                <TD className="max-w-[260px] align-top">
                  <p className="font-semibold text-ink [overflow-wrap:anywhere]">
                    <span className="font-mono text-ink-muted">#{row.id}</span> {row.requester_display || row.requester_username}
                  </p>
                  <p className="mt-0.5 line-clamp-2 text-caption text-ink-muted">{row.requested_for || "No note"}</p>
                </TD>
                <TD className="align-top">
                  <ul className="grid gap-1">
                    {row.items.map((item) => (
                      <li key={item.id} className="min-w-0">
                        <span className="text-ink">{item.product_name}</span> <span className="text-ink-muted">×{item.requested_quantity}</span>
                        {item.storage_location ? <span className="block text-caption text-ink-muted">Shelf: {item.storage_location}</span> : null}
                      </li>
                    ))}
                  </ul>
                </TD>
                <TD className="align-top">
                  <div className="flex flex-wrap gap-1.5">
                    <RequestStatus status={row.status} />
                    {row.items.some(hasItemIssues) ? <Chip tone="danger" size="sm">Has issues</Chip> : null}
                  </div>
                </TD>
                <TD className="whitespace-nowrap align-top">
                  {row.return_due_at ? (
                    <span className={overdue ? "font-semibold text-danger-fg" : "text-ink"}>
                      {formatWhen(row.return_due_at)}
                      {overdue ? <span className="block text-caption">Overdue</span> : null}
                    </span>
                  ) : (
                    <span className="text-ink-muted">Not set</span>
                  )}
                </TD>
                <TD className="align-top">
                  <div className="flex flex-wrap justify-end gap-2">
                    {actions(row)}
                    <Button size="sm" variant="quiet" aria-label={`Details for request #${row.id}`} onClick={() => setDetailId(row.id)}>Details</Button>
                  </div>
                </TD>
              </TR>
            );
          })}
        </TBody>
      </Table>
      <RequestDetailDrawer row={detail} canViewAudit={canViewAudit} onClose={() => setDetailId(null)} />
    </>
  );
}

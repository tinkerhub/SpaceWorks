import type { ReactNode } from "react";

import { Button, Chip, ErrorBlock, Pagination, SectionHeading } from "../../../components/ui";
import type { HardwareRequest } from "./Queues";
import { RequestList } from "./QueuesList";
import { RequestListSkeleton } from "./QueuesSkeleton";

type QueuePage = {
  isLoading: boolean;
  error: unknown;
  results: HardwareRequest[];
  page: number;
  totalPages: number;
  count: number;
  pageSize: number;
  setPage: (page: number) => void;
};

/** One queue: heading with its count, the request table (or skeleton/empty state), errors and paging. */
export function QueueSection({
  title,
  description,
  query,
  emptyDescription,
  canViewAudit,
  actions,
  headingAction,
  collapsed = false,
}: {
  title: string;
  description?: string;
  query: QueuePage;
  emptyDescription: string;
  canViewAudit: boolean;
  actions: (row: HardwareRequest) => ReactNode;
  headingAction?: ReactNode;
  /** Heading only; the list is neither shown nor counted. */
  collapsed?: boolean;
}) {
  return (
    <section className="grid gap-3">
      <SectionHeading
        title={title}
        description={description}
        action={(
          <div className="flex flex-wrap items-center gap-2">
            {!collapsed && !query.isLoading && query.count > 0 ? <Chip size="sm">{query.count}</Chip> : null}
            {headingAction}
          </div>
        )}
      />
      {collapsed ? null : (
        <>
          {query.isLoading ? (
            <RequestListSkeleton />
          ) : (
            <RequestList rows={query.results} canViewAudit={canViewAudit} label={title} emptyTitle={`Nothing in ${title.toLowerCase()}`} emptyDescription={emptyDescription} actions={actions} />
          )}
          <ErrorBlock error={query.error} />
          <Pagination page={query.page} totalPages={query.totalPages} onChange={query.setPage} count={query.count} pageSize={query.pageSize} />
        </>
      )}
    </section>
  );
}

type Setter = (row: HardwareRequest | null) => void;
type QueueActionProps = { row: HardwareRequest; disabled: boolean; openModal: (setter: Setter, row: HardwareRequest) => void };

export function PendingActions({ row, disabled, openModal, setAcceptRow, setRejectRow, setDueRow }: QueueActionProps & { setAcceptRow: Setter; setRejectRow: Setter; setDueRow: Setter }) {
  return (
    <>
      <Button size="sm" variant="secondary" disabled={disabled} onClick={() => openModal(setAcceptRow, row)}>Accept</Button>
      <Button size="sm" variant="danger-quiet" disabled={disabled} onClick={() => openModal(setRejectRow, row)}>Reject…</Button>
      <Button size="sm" variant="quiet" disabled={disabled} onClick={() => openModal(setDueRow, row)}>Set due</Button>
    </>
  );
}

export function AcceptedActions({ row, disabled, openModal, setAssignIssueRow, setDueRow }: QueueActionProps & { setAssignIssueRow: Setter; setDueRow: Setter | null }) {
  return (
    <>
      <Button size="sm" variant="secondary" disabled={disabled} onClick={() => openModal(setAssignIssueRow, row)}>Assign + issue</Button>
      {setDueRow ? <Button size="sm" variant="quiet" disabled={disabled} onClick={() => openModal(setDueRow, row)}>Set due</Button> : null}
    </>
  );
}

export function ActiveActions({ row, disabled, openModal, setDueRow, setReturnRow }: QueueActionProps & { setDueRow: Setter | null; setReturnRow: Setter | null }) {
  return (
    <>
      {setReturnRow ? <Button size="sm" variant="secondary" disabled={disabled} onClick={() => openModal(setReturnRow, row)}>Return</Button> : null}
      {setDueRow ? <Button size="sm" variant="quiet" disabled={disabled} onClick={() => openModal(setDueRow, row)}>Set due</Button> : null}
    </>
  );
}

/** Closed requests are fetched only once someone asks for them. */
export function HistoryToggle({ show, onToggle }: { show: boolean; onToggle: () => void }) {
  return (
    <Button size="sm" variant="secondary" aria-expanded={show} onClick={onToggle}>
      {show ? "Hide history" : "Show history"}
    </Button>
  );
}

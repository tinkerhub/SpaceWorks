import { useEffect, useState } from "react";

import { Field, SearchInput } from "../../../components/ui";
import { getSessionGeneration } from "../../../lib/apiSession";
import { useDebouncedValue } from "../../../lib/useDebouncedValue";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";
import { Panel, type Makerspace } from "./shared";
import { useQueueActions } from "./useQueueActions";
import { QueueFormEditContext } from "./QueuesModalShared";
import {
  AssignIssueModal,
  RejectRequestModal,
  ReturnDueModal,
  ReturnRequestModal,
  type RejectRequestValues,
  type ReturnDueValues,
  type ReturnRequestValues,
} from "./QueuesModals";
import { AcceptRequestModal } from "./QueuesAcceptModal";
import { CancelRequestModal } from "./QueuesCancelModal";
import { AcceptedActions, ActiveActions, HistoryToggle, PendingActions, QueueSection } from "./QueuesSections";

export type RequestItem = {
  id: number;
  product_id: number;
  product_name: string;
  storage_location: string;
  tracking_mode: string;
  requires_asset_qr: boolean;
  requested_quantity: number;
  accepted_quantity: number;
  issued_quantity: number;
  returned_quantity: number;
  damaged_quantity: number;
  missing_quantity: number;
  needs_fix_quantity: number;
  issued_assets?: Array<{ asset_id: number; asset_tag: string; serial_number: string }>;
};
export type HardwareRequest = {
  id: number;
  status: string;
  requester_username: string;
  requester_display?: string;
  requester_contact_email?: string;
  requester_contact_phone?: string;
  // Verified upstream check-in context, present only on a `checked_in` submission.
  checkin_purpose?: string;
  checkin_project_name?: string;
  checkin_verified_at?: string | null;
  rejection_reason?: string;
  cancellation_reason?: string;
  closed_by?: { username: string; role: string } | null;
  closed_at?: string | null;
  issue_evidence_id?: number | null;
  return_evidence_ids?: number[];
  requested_for: string;
  return_due_at: string | null;
  return_reminder_sent_at: string | null;
  items: RequestItem[];
  assigned_box_id?: number | null;
  // Label and legacy object support older staff API responses.
  assigned_box_label?: string | null;
  assigned_box?: { code: string; label: string };
};

// Handover hides review and cancellation; each action keeps its own backend permission.
type QueuesProps = {
  makerspace: Makerspace; guestOnly: boolean; canViewAudit?: boolean; canReturnRequest: boolean; canReviewRequests: boolean;
  canIssueRequest?: boolean; canCancelRequests?: boolean;
};
export function Queues(props: QueuesProps) {
  return <QueueVisit key={`${props.makerspace.id}:${getSessionGeneration()}:${Boolean(props.canCancelRequests)}:${props.guestOnly}`} {...props} />;
}
function QueueVisit({ makerspace, guestOnly, canViewAudit = false, canReturnRequest, canReviewRequests, canIssueRequest = false, canCancelRequests = false }: QueuesProps) {
  const showActiveLoans = canIssueRequest;
  const canCancel = (row: HardwareRequest) => !guestOnly && canCancelRequests && row.status === "accepted" && row.items.every((item) => item.issued_quantity === 0);
  const {
    acceptRow, setAcceptRow, dueRow, setDueRow, rejectRow, setRejectRow, cancelRow, setCancelRow, assignIssueRow, setAssignIssueRow,
    returnRow, setReturnRow, assignedContainerCode, modalError, visit, openModal, closeModals, runAction,
    submitAssignIssue, editable, pending: actionPending,
  } = useQueueActions(makerspace);
  const [defaultLoanDays, setDefaultLoanDays] = useState(String(makerspace.default_loan_days ?? 7));
  const [showHistory, setShowHistory] = useState(false);
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedValue(search);
  const queue = (key: string, path: string, enabled = true) => ({
    key: [key, makerspace.id],
    path: `/admin/makerspace/${makerspace.id}/${path}`,
    enabled,
    search: debouncedSearch,
    resetKey: String(makerspace.id),
  });

  const pending = usePaginatedQuery<HardwareRequest>(queue("pending", "pending-requests", !guestOnly));
  const accepted = usePaginatedQuery<HardwareRequest>(queue("accepted", "accepted-requests"));
  const active = usePaginatedQuery<HardwareRequest>(queue("active", "active-loans", showActiveLoans));
  const history = usePaginatedQuery<HardwareRequest>(queue("request-history", "request-history", showHistory));

  useEffect(() => {
    setDefaultLoanDays(String(makerspace.default_loan_days ?? 7));
  }, [makerspace.default_loan_days, makerspace.id]);
  const submitReturnDue = (values: ReturnDueValues) => {
    if (dueRow) void runAction(`/admin/requests/${dueRow.id}/return-due`, { return_due_at: values.returnDueAt ? new Date(values.returnDueAt).toISOString() : null }, values.returnDueAt ? "Due date saved." : "Due date cleared.", "Could not save the due date.");
  };
  const submitAccept = (acceptedQuantities: { item_id: number; quantity: number }[]) => {
    if (acceptRow) void runAction(`/admin/requests/${acceptRow.id}/accept`, { accepted_quantities: acceptedQuantities }, `Request #${acceptRow.id} accepted.`, "Could not accept the request.");
  };
  const submitReject = (values: RejectRequestValues) => {
    if (rejectRow) void runAction(`/admin/requests/${rejectRow.id}/reject`, { reason: values.reason }, `Request #${rejectRow.id} rejected.`, "Could not reject the request.");
  };
  const openCancel = (row: HardwareRequest) => {
    if (canCancel(row)) openModal(setCancelRow, row);
  };
  const submitCancel = ({ reason }: { reason: string }) => {
    const clean = reason.trim();
    if (cancelRow && canCancel(cancelRow) && clean && clean.length <= 500) {
      void runAction(`/admin/requests/${cancelRow.id}/cancel`, { reason: clean }, `Request #${cancelRow.id} cancelled.`, "Could not cancel the request.");
    }
  };
  const submitReturn = (values: ReturnRequestValues) => {
    if (returnRow) void runAction(`/admin/requests/${returnRow.id}/return`, { evidence_id: values.evidenceId, box_code: values.boxCode, remark: values.remark, resolutions: values.resolutions }, `Return recorded for request #${returnRow.id}.`, "Could not record the return.");
  };
  const searching = debouncedSearch.trim().length > 0;
  const emptyText = (idle: string) => (searching ? `No requests match "${debouncedSearch.trim()}".` : idle);

  return (
    <Panel
      title="Requests"
      description={guestOnly ? "Hand over accepted requests and take hardware back." : "Review requests, hand hardware over and take it back."}
    >
      <div className="grid gap-8">
        <Field label="Search requests" hideLabel className="max-w-xl">
          <SearchInput placeholder="Search requester name, email, phone or purpose" value={search} onChange={(event) => setSearch(event.target.value)} onClear={() => setSearch("")} />
        </Field>
        {!guestOnly ? (
          <QueueSection title="Pending review" query={pending} canViewAudit={canViewAudit} emptyDescription={emptyText("New requests from the public page land here.")}
            actions={(row) => <PendingActions row={row} disabled={actionPending} openModal={openModal} setAcceptRow={canReviewRequests ? setAcceptRow : null} setRejectRow={canCancelRequests && !guestOnly ? setRejectRow : null} setDueRow={canReviewRequests ? setDueRow : null} />} />
        ) : null}
        <QueueSection title="Ready for handover" query={accepted} canViewAudit={canViewAudit} emptyDescription={emptyText("Accepted requests wait here until someone hands them over.")}
          actions={(row) => <AcceptedActions row={row} disabled={actionPending} openModal={openModal} setAssignIssueRow={canIssueRequest ? setAssignIssueRow : null} setDueRow={canReviewRequests ? setDueRow : null} onCancel={canCancel(row) ? () => openCancel(row) : null} />} />
        {showActiveLoans ? (
          <QueueSection title="Active loans" query={active} canViewAudit={canViewAudit} emptyDescription={emptyText("Hardware that's out on loan shows up here.")}
            actions={(row) => <ActiveActions row={row} disabled={actionPending} openModal={openModal} setDueRow={canReviewRequests ? setDueRow : null} setReturnRow={canReturnRequest ? setReturnRow : null} />} />
        ) : null}
        <QueueSection
          title="History"
          description={showHistory ? undefined : "Returned, rejected, cancelled and closed requests."}
          query={history}
          collapsed={!showHistory}
          canViewAudit={canViewAudit}
          emptyDescription={emptyText("Returned, rejected, cancelled and closed requests show up here.")}
          headingAction={<HistoryToggle show={showHistory} onToggle={() => setShowHistory((value) => !value)} />}
          actions={() => null}
        />
      </div>
      <QueueFormEditContext.Provider value={editable}>
      <div onSubmitCapture={(event) => { if (!editable()) { event.preventDefault(); event.stopPropagation(); } }} onChangeCapture={(event) => { if (!editable()) event.stopPropagation(); }} onClickCapture={(event) => { if (!editable()) { event.preventDefault(); event.stopPropagation(); } }}>
      <AcceptRequestModal key={`AcceptRequestModal-${visit}`} row={acceptRow} open={Boolean(acceptRow)} pending={actionPending} error={modalError} onClose={closeModals} onSubmit={submitAccept} />
      <ReturnDueModal key={`ReturnDueModal-${visit}`} row={dueRow} defaultValue={dueRow?.return_due_at ? localDateTimeValue(dueRow.return_due_at) : localDateTimeValue(defaultDueDate(Number(defaultLoanDays) || 7).toISOString())} open={Boolean(dueRow)} pending={actionPending} error={modalError} onClose={closeModals} onSubmit={submitReturnDue} />
      <RejectRequestModal key={`RejectRequestModal-${visit}`} row={rejectRow} open={Boolean(rejectRow)} pending={actionPending} error={modalError} onClose={closeModals} onSubmit={submitReject} />
      <CancelRequestModal key={`CancelRequestModal-${visit}`} row={cancelRow} open={Boolean(cancelRow)} pending={actionPending} error={modalError} onClose={closeModals} onSubmit={submitCancel} />
      <AssignIssueModal key={`AssignIssueModal-${visit}`} row={assignIssueRow} assignedContainerCode={assignedContainerCode} canEdit={editable} open={Boolean(assignIssueRow)} pending={actionPending} error={modalError} onClose={closeModals} onSubmit={submitAssignIssue} makerspaceId={makerspace.id} />
      <ReturnRequestModal key={`ReturnRequestModal-${visit}`} row={returnRow} open={Boolean(returnRow)} pending={actionPending} error={modalError} onClose={closeModals} onSubmit={submitReturn} makerspaceId={makerspace.id} />
      </div>
      </QueueFormEditContext.Provider>
    </Panel>
  );
}

function defaultDueDate(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date;
}

function localDateTimeValue(value: string) {
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

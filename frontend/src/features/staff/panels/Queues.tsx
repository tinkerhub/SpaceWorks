import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Field, SearchInput, useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { useDebouncedValue } from "../../../lib/useDebouncedValue";
import { usePaginatedQuery } from "../../../lib/usePaginatedQuery";
import { errorText, Panel, type Makerspace } from "./shared";
import { actionInvalidationScope, invalidateRequestQueues } from "./QueuesInvalidation";
import {
  AssignIssueModal,
  RejectRequestModal,
  ReturnDueModal,
  ReturnRequestModal,
  type AssignIssueValues,
  type RejectRequestValues,
  type ReturnDueValues,
  type ReturnRequestValues,
} from "./QueuesModals";
import { AcceptRequestModal } from "./QueuesAcceptModal";
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
  issue_evidence_id?: number | null;
  return_evidence_ids?: number[];
  requested_for: string;
  return_due_at: string | null;
  return_reminder_sent_at: string | null;
  items: RequestItem[];
  // AdminRequestSerializer serializes the assigned container as the flat `assigned_box_label`.
  assigned_box_label?: string | null;
  assigned_box?: { code: string; label: string };
};

// `guestOnly` (the handover surface) hides review. Active loans are listed with ISSUE_REQUEST,
// returned with RETURN_REQUEST and re-dated with ACCEPT_REQUEST, so a handover role that holds
// `return_request` still gets Active loans -> Return, without the Set due it cannot use.
export function Queues({ makerspace, guestOnly, canViewAudit = false, canReturnRequest, canReviewRequests }: {
  makerspace: Makerspace; guestOnly: boolean; canViewAudit?: boolean; canReturnRequest: boolean; canReviewRequests: boolean;
}) {
  const showActiveLoans = !guestOnly || canReturnRequest;
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [acceptRow, setAcceptRow] = useState<HardwareRequest | null>(null);
  const [dueRow, setDueRow] = useState<HardwareRequest | null>(null);
  const [rejectRow, setRejectRow] = useState<HardwareRequest | null>(null);
  const [assignIssueRow, setAssignIssueRow] = useState<HardwareRequest | null>(null);
  const [returnRow, setReturnRow] = useState<HardwareRequest | null>(null);
  const [modalError, setModalError] = useState("");
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

  const action = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: object }) => staffRequest(path, { method: "POST", body: JSON.stringify(body ?? {}) }),
    onSuccess: (_data, { path }) => invalidateRequestQueues(queryClient, makerspace.id, actionInvalidationScope(path), makerspace.slug),
  });
  useEffect(() => {
    setDefaultLoanDays(String(makerspace.default_loan_days ?? 7));
  }, [makerspace.default_loan_days, makerspace.id]);

  const openModal = (setter: (row: HardwareRequest | null) => void, row: HardwareRequest) => {
    setModalError("");
    setter(row);
  };
  const closeModals = () => {
    if (action.isPending) return;
    setAcceptRow(null);
    setDueRow(null);
    setRejectRow(null);
    setAssignIssueRow(null);
    setReturnRow(null);
    setModalError("");
  };
  const clearModals = () => {
    setAcceptRow(null);
    setDueRow(null);
    setRejectRow(null);
    setAssignIssueRow(null);
    setReturnRow(null);
    setModalError("");
  };
  const runAction = async (path: string, body: object, done: string, failed: string) => {
    setModalError("");
    try {
      await action.mutateAsync({ path, body });
      clearModals();
      showToast(done, { tone: "success" });
    } catch (error) {
      const message = errorText(error, failed);
      setModalError(message);
      showToast(message, { tone: "error" });
    }
  };
  const submitReturnDue = (values: ReturnDueValues) => {
    if (dueRow) void runAction(`/admin/requests/${dueRow.id}/return-due`, { return_due_at: values.returnDueAt ? new Date(values.returnDueAt).toISOString() : null }, values.returnDueAt ? "Due date saved." : "Due date cleared.", "Could not save the due date.");
  };
  const submitAccept = (acceptedQuantities: { item_id: number; quantity: number }[]) => {
    if (acceptRow) void runAction(`/admin/requests/${acceptRow.id}/accept`, { accepted_quantities: acceptedQuantities }, `Request #${acceptRow.id} accepted.`, "Could not accept the request.");
  };
  const submitReject = (values: RejectRequestValues) => {
    if (rejectRow) void runAction(`/admin/requests/${rejectRow.id}/reject`, { reason: values.reason }, `Request #${rejectRow.id} rejected.`, "Could not reject the request.");
  };
  const submitReturn = (values: ReturnRequestValues) => {
    if (returnRow) void runAction(`/admin/requests/${returnRow.id}/return`, { evidence_id: values.evidenceId, box_code: values.boxCode, remark: values.remark, resolutions: values.resolutions }, `Return recorded for request #${returnRow.id}.`, "Could not record the return.");
  };
  const submitAssignIssue = async (values: AssignIssueValues) => {
    if (!assignIssueRow) return;
    setModalError("");
    let boxAssigned = false;
    try {
      await action.mutateAsync({ path: `/admin/requests/${assignIssueRow.id}/assign-box`, body: { box_code: values.boxCode } });
      boxAssigned = true;
      await action.mutateAsync({
        path: `/admin/requests/${assignIssueRow.id}/issue`,
        body: { evidence_id: values.evidenceId, remark: values.remark, rejects: values.rejects, asset_qr_payloads: values.assetQrPayloads },
      });
      showToast(`Request #${assignIssueRow.id} issued.`, { tone: "success" });
      clearModals();
    } catch (error) {
      const message = errorText(error, "Could not issue the request.");
      setModalError(boxAssigned ? `Box assigned, but issue failed: ${message} The request still needs the issue step; retry with the assigned box.` : message);
      showToast(boxAssigned ? "Box assigned, but the issue step failed." : message, { tone: "error" });
    }
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
            actions={(row) => <PendingActions row={row} disabled={action.isPending} openModal={openModal} setAcceptRow={setAcceptRow} setRejectRow={setRejectRow} setDueRow={setDueRow} />} />
        ) : null}
        <QueueSection title="Ready for handover" query={accepted} canViewAudit={canViewAudit} emptyDescription={emptyText("Accepted requests wait here until someone hands them over.")}
          actions={(row) => <AcceptedActions row={row} disabled={action.isPending} openModal={openModal} setAssignIssueRow={setAssignIssueRow} setDueRow={canReviewRequests ? setDueRow : null} />} />
        {showActiveLoans ? (
          <QueueSection title="Active loans" query={active} canViewAudit={canViewAudit} emptyDescription={emptyText("Hardware that's out on loan shows up here.")}
            actions={(row) => <ActiveActions row={row} disabled={action.isPending} openModal={openModal} setDueRow={canReviewRequests ? setDueRow : null} setReturnRow={canReturnRequest ? setReturnRow : null} />} />
        ) : null}
        <QueueSection
          title="History"
          description={showHistory ? undefined : "Returned, rejected and closed requests."}
          query={history}
          collapsed={!showHistory}
          canViewAudit={canViewAudit}
          emptyDescription={emptyText("Returned, rejected and closed requests show up here.")}
          headingAction={<HistoryToggle show={showHistory} onToggle={() => setShowHistory((value) => !value)} />}
          actions={() => null}
        />
      </div>
      <AcceptRequestModal row={acceptRow} open={Boolean(acceptRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitAccept} />
      <ReturnDueModal row={dueRow} defaultValue={dueRow?.return_due_at ? localDateTimeValue(dueRow.return_due_at) : localDateTimeValue(defaultDueDate(Number(defaultLoanDays) || 7).toISOString())} open={Boolean(dueRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitReturnDue} />
      <RejectRequestModal row={rejectRow} open={Boolean(rejectRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitReject} />
      <AssignIssueModal row={assignIssueRow} open={Boolean(assignIssueRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitAssignIssue} makerspaceId={makerspace.id} />
      <ReturnRequestModal row={returnRow} open={Boolean(returnRow)} pending={action.isPending} error={modalError} onClose={closeModals} onSubmit={submitReturn} makerspaceId={makerspace.id} />
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

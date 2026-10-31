import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "../../../components/ui";
import { staffRequest } from "../../../lib/api";
import { useAuthActionOwner, type AuthAction } from "../../auth/useAuthActionOwner";
import { invalidateContainerViews } from "../queryInvalidation";
import { actionInvalidationScope, invalidateRequestQueues } from "./QueuesInvalidation";
import { errorText, type Makerspace } from "./shared";
import type { HardwareRequest } from "./Queues";
import type { AssignIssueValues } from "./QueuesModalTypes";

type QueueCommand = { owner: AuthAction; path: string; body: string; makerId: number; slug: string };

// A visit owns the complete assign → issue sequence, including time spent paused by Query.
export function useQueueActions(makerspace: Makerspace) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [acceptRow, setAcceptRow] = useState<HardwareRequest | null>(null);
  const [dueRow, setDueRow] = useState<HardwareRequest | null>(null);
  const [rejectRow, setRejectRow] = useState<HardwareRequest | null>(null);
  const [cancelRow, setCancelRow] = useState<HardwareRequest | null>(null);
  const [assignIssueRow, setAssignIssueRow] = useState<HardwareRequest | null>(null);
  const [returnRow, setReturnRow] = useState<HardwareRequest | null>(null);
  const [assignedContainerCode, setAssignedContainerCode] = useState("");
  const committedContainer = useRef("");
  const [modalError, setModalError] = useState("");
  const [visit, setVisit] = useState(0);
  const subject = acceptRow ? `accept:${acceptRow.id}` : dueRow ? `due:${dueRow.id}` : rejectRow ? `reject:${rejectRow.id}` :
    cancelRow ? `cancel:${cancelRow.id}` : assignIssueRow ? `issue:${assignIssueRow.id}` : returnRow ? `return:${returnRow.id}` : "closed";
  const owner = useAuthActionOwner(`${makerspace.id}:${subject}:${visit}`);
  const action = useMutation({
    mutationFn: async (command: QueueCommand) => {
      if (!owner.isCurrent(command.owner)) throw new Error("Request visit changed.");
      // Even a rejected stale response may follow a committed assignment. Refresh only its origin.
      try {
        return await staffRequest(command.path, { method: "POST", body: command.body });
      } finally {
        if (command.path.endsWith("/assign-box")) invalidateContainerViews(queryClient, command.makerId);
      }
    },
  });
  const editable = () => owner.isIntentCurrent() && !owner.isPending();
  const clearRows = () => {
    setAcceptRow(null); setDueRow(null); setRejectRow(null); setCancelRow(null); setAssignIssueRow(null); setReturnRow(null);
    committedContainer.current = "";
    setAssignedContainerCode(""); setModalError("");
  };
  const clearModals = () => {
    owner.cancel();
    clearRows();
    setVisit((value) => value + 1);
    action.reset();
  };
  const openModal = (setter: (row: HardwareRequest | null) => void, row: HardwareRequest) => {
    if (!editable()) return;
    clearModals();
    setter(row);
  };
  const closeModals = () => { if (editable()) clearModals(); };
  const command = (token: AuthAction, path: string, body: object): QueueCommand => ({
    owner: token, path, body: JSON.stringify(body), makerId: makerspace.id, slug: makerspace.slug,
  });
  const refresh = (request: QueueCommand) => {
    if (owner.isCurrent(request.owner)) {
      invalidateRequestQueues(queryClient, request.makerId, actionInvalidationScope(request.path), request.slug);
    }
  };
  const runAction = async (path: string, body: object, done: string, failed: string) => {
    if (!editable()) return;
    const token = owner.begin();
    if (!token) return;
    const request = command(token, path, body);
    setModalError("");
    try {
      await action.mutateAsync(request);
      if (!owner.isCurrent(token)) return;
      refresh(request);
      showToast(done, { tone: "success" });
      clearModals();
    } catch (error) {
      if (!owner.isCurrent(token)) return;
      const message = errorText(error, failed);
      setModalError(message);
      showToast(message, { tone: "error" });
    } finally {
      owner.finish(token);
    }
  };
  const submitAssignIssue = async (values: AssignIssueValues) => {
    if (!assignIssueRow || !editable()) return;
    const token = owner.begin();
    if (!token) return;
    const rowId = assignIssueRow.id;
    const code = values.boxCode;
    // Serialize BOTH stages before the first mutation can be queued or any live field changes.
    const assign = code && !committedContainer.current ? command(token, `/admin/requests/${rowId}/assign-box`, { box_code: code }) : null;
    const issue = command(token, `/admin/requests/${rowId}/issue`, {
      evidence_id: values.evidenceId, remark: values.remark, rejects: values.rejects, asset_qr_payloads: values.assetQrPayloads,
    });
    let boxAssigned = Boolean(committedContainer.current);
    setModalError("");
    try {
      if (assign) {
        await action.mutateAsync(assign);
        if (!owner.isCurrent(token)) return;
        committedContainer.current = code;
        setAssignedContainerCode(code);
        boxAssigned = true;
        refresh(assign);
      }
      if (!owner.isCurrent(token)) return;
      await action.mutateAsync(issue);
      if (!owner.isCurrent(token)) return;
      refresh(issue);
      showToast(`Request #${rowId} issued.`, { tone: "success" });
      clearModals();
    } catch (error) {
      if (!owner.isCurrent(token)) return;
      const message = errorText(error, "Could not issue the request.");
      setModalError(boxAssigned ? `Container assigned, but issue failed: ${message} Retry to issue with the assigned container.` : message);
      showToast(boxAssigned ? "Container assigned, but the issue step failed." : message, { tone: "error" });
    } finally {
      owner.finish(token);
    }
  };
  return {
    acceptRow, setAcceptRow, dueRow, setDueRow, rejectRow, setRejectRow, cancelRow, setCancelRow, assignIssueRow, setAssignIssueRow,
    returnRow, setReturnRow, assignedContainerCode, modalError, visit, openModal, closeModals, runAction,
    submitAssignIssue, editable, pending: owner.isPending(),
  };
}

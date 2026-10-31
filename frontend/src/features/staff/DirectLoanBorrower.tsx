import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Dropdown, ErrorText, Field, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";
import type { DirectLoanMember } from "./DirectLoanTypes";
import { errorText } from "./panels/shared";
import { WalkInMemberForm } from "./WalkInMemberForm";

type WaiverCommand = { owner: AuthAction; path: string; body: string; makerId: number; editable: () => boolean };

/** The selected membership owns a waiver; a borrower choice also ends any older walk-in selection. */
export function DirectLoanBorrower({
  makerspaceId, members, loading, error, borrowerId, onBorrowerChange, membershipOn,
  disabled = false, canEdit = () => !disabled,
}: {
  makerspaceId: number;
  members: DirectLoanMember[];
  loading: boolean;
  error: Error | null;
  borrowerId: string;
  onBorrowerChange: (userId: string) => void;
  membershipOn: boolean;
  disabled?: boolean;
  canEdit?: () => boolean;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [choice, setChoice] = useState(0);
  const selectedMember = members.find((member) => String(member.user_id) === borrowerId);
  const owner = useAuthActionOwner(`${makerspaceId}:${borrowerId}:${selectedMember?.membership_id}:${choice}`);
  const latestEdit = useRef(canEdit);
  latestEdit.current = canEdit;
  const current = (request: WaiverCommand) => owner.isCurrent(request.owner) && request.editable() && latestEdit.current();
  const witnessWaiver = useMutation({
    mutationFn: (request: WaiverCommand) => {
      if (!current(request)) throw new Error("Borrower selection changed.");
      return staffRequest(request.path, { method: "POST", body: request.body });
    },
    onSuccess: (_data, request) => {
      if (!current(request)) return;
      queryClient.invalidateQueries({ queryKey: ["members", request.makerId] });
      showToast("Waiver acceptance recorded.", { tone: "success" });
    },
    onError: (failure, request) => {
      if (current(request)) showToast(errorText(failure, "Could not record the waiver."), { tone: "error" });
    },
    onSettled: (_data, _error, request) => { owner.finish(request.owner); },
  });
  const editable = () => owner.isIntentCurrent() && !owner.isPending() && !disabled && canEdit() && latestEdit.current();
  const choose = (userId: string) => {
    if (!editable()) return;
    owner.cancel();
    setChoice((value) => value + 1);
    onBorrowerChange(userId);
    witnessWaiver.reset();
  };
  const witness = () => {
    if (!editable() || !selectedMember) return;
    const token = owner.begin();
    if (!token) return;
    witnessWaiver.mutate({ owner: token, path: `/admin/memberships/${selectedMember.membership_id}/waiver/witness`, body: "{}", makerId: makerspaceId, editable: canEdit });
  };
  const waiverCurrent = Boolean(witnessWaiver.variables && current(witnessWaiver.variables));
  const pending = waiverCurrent && witnessWaiver.isPending;

  return (
    <div className="grid gap-3">
      <Field label={membershipOn ? "Borrowing member" : "Borrower"} helperText={loading ? "Loading people…" : undefined}>
        <Dropdown id="direct-loan-borrower" value={borrowerId} disabled={disabled || loading || pending} onChange={(event) => choose(event.target.value)}>
          <option value="">{membershipOn ? "Select an active member" : "Select a borrower"}</option>
          {members.map((member) => <option key={member.user_id} value={member.user_id}>{member.display_name || member.username}</option>)}
        </Dropdown>
      </Field>
      <ErrorText message={error?.message} />
      {membershipOn && selectedMember ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" disabled={disabled} loading={pending} onClick={witness}>Record witnessed waiver acceptance</Button>
          {waiverCurrent && witnessWaiver.isSuccess ? <p className="text-caption text-success-fg">Waiver acceptance recorded.</p> : null}
        </div>
      ) : null}
      <ErrorText message={waiverCurrent ? witnessWaiver.error?.message : undefined} />
      <WalkInMemberForm key={`${borrowerId}:${choice}`} makerspaceId={makerspaceId} disabled={disabled || pending} canEdit={editable} onCreated={(userId) => choose(String(userId))} />
    </div>
  );
}

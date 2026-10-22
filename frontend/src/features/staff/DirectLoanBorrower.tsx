import { useMutation, useQueryClient } from "@tanstack/react-query";

import { Button, Dropdown, ErrorText, Field, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import type { DirectLoanMember } from "./DirectLoanTypes";
import { errorText } from "./panels/shared";
import { WalkInMemberForm } from "./WalkInMemberForm";

/**
 * Who the handout is for: someone already on the roster, or a walk-in named at the counter.
 * Waivers are part of the membership module, so the witnessed-waiver control and the
 * "member" wording only appear while that module is on.
 */
export function DirectLoanBorrower({
  makerspaceId,
  members,
  loading,
  error,
  borrowerId,
  onBorrowerChange,
  membershipOn,
}: {
  makerspaceId: number;
  members: DirectLoanMember[];
  loading: boolean;
  error: Error | null;
  borrowerId: string;
  onBorrowerChange: (userId: string) => void;
  membershipOn: boolean;
}) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const selectedMember = members.find((member) => String(member.user_id) === borrowerId);
  const witnessWaiver = useMutation({
    mutationFn: () => {
      if (!selectedMember) throw new Error("Select a member first.");
      return staffRequest(`/admin/memberships/${selectedMember.membership_id}/waiver/witness`, {
        method: "POST",
        body: JSON.stringify({}),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["members", makerspaceId] });
      showToast("Waiver acceptance recorded.", { tone: "success" });
    },
    onError: (failure) => showToast(errorText(failure, "Could not record the waiver."), { tone: "error" }),
  });
  const choose = (userId: string) => {
    onBorrowerChange(userId);
    witnessWaiver.reset();
  };

  return (
    <div className="grid gap-3">
      <Field label={membershipOn ? "Borrowing member" : "Borrower"} helperText={loading ? "Loading people…" : undefined}>
        <Dropdown
          id="direct-loan-borrower"
          value={borrowerId}
          disabled={loading}
          onChange={(event) => choose(event.target.value)}
        >
          <option value="">{membershipOn ? "Select an active member" : "Select a borrower"}</option>
          {members.map((member) => (
            <option key={member.user_id} value={member.user_id}>
              {member.display_name || member.username}
            </option>
          ))}
        </Dropdown>
      </Field>
      <ErrorText message={error?.message} />
      {membershipOn && selectedMember ? (
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" loading={witnessWaiver.isPending} onClick={() => witnessWaiver.mutate()}>
            Record witnessed waiver acceptance
          </Button>
          {witnessWaiver.isSuccess ? <p className="text-caption text-success-fg">Waiver acceptance recorded.</p> : null}
        </div>
      ) : null}
      <ErrorText message={witnessWaiver.error?.message} />
      <WalkInMemberForm makerspaceId={makerspaceId} onCreated={(userId) => choose(String(userId))} />
    </div>
  );
}

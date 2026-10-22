import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { UserPlus } from "lucide-react";

import { Button, ErrorText, Field, Input, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { errorText } from "./panels/shared";

type WalkInMember = { user_id: number; display_name: string; username: string };

/**
 * Name the person at the counter so a handout can be recorded against them.
 *
 * This is the identity path a deployment running without member accounts lives on, so
 * it sits inside the handout flow rather than relying on self-service enrolment.
 *
 * Collapsed by default. The normal case is picking an existing member, and an always-open
 * creation form next to a dropdown invites creating a duplicate of the person already in it.
 */
export function WalkInMemberForm({
  makerspaceId,
  onCreated,
}: {
  makerspaceId: number;
  onCreated: (userId: number) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const { showToast } = useToast();

  const create = useMutation({
    mutationFn: () =>
      staffRequest<WalkInMember>(`/admin/makerspaces/${makerspaceId}/walk-in-members`, {
        method: "POST",
        body: JSON.stringify({
          display_name: displayName.trim(),
          email: email.trim(),
          phone: phone.trim(),
        }),
      }),
    onSuccess: (member) => {
      // The dropdown reads this query, so it has to be refetched before the new member
      // can be selected — selecting an id the options don't contain leaves the select blank.
      void queryClient
        .invalidateQueries({ queryKey: ["direct-loan-members", makerspaceId] })
        .then(() => onCreated(member.user_id));
      setDisplayName("");
      setEmail("");
      setPhone("");
      setOpen(false);
      showToast(`${member.display_name} added`, { tone: "success" });
    },
    onError: (error) => showToast(errorText(error, "Couldn't add the walk-in"), { tone: "error" }),
  });

  if (!open) {
    return (
      <Button variant="quiet" size="sm" className="mt-2 px-0" startIcon={<UserPlus />} onClick={() => setOpen(true)}>
        Not in the list? Add a walk-in
      </Button>
    );
  }

  return (
    <div className="mt-3 grid gap-4 rounded-lg border border-line bg-subtle p-4">
      <div>
        <p className="text-label text-ink">Add a walk-in</p>
        <p className="mt-0.5 text-caption text-ink-muted">
          Creates a person record for the handover trail. It is not an account and cannot sign in.
        </p>
      </div>
      <Field label="Name" id="walk-in-name">
        <Input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
      </Field>
      <div className="grid gap-4 md:grid-cols-2">
        <Field label="Email" optional id="walk-in-email">
          <Input type="email" value={email} onChange={(event) => setEmail(event.target.value)} />
        </Field>
        <Field label="Phone" optional id="walk-in-phone">
          <Input type="tel" value={phone} onChange={(event) => setPhone(event.target.value)} />
        </Field>
      </div>
      {create.error ? (
        <ErrorText message={create.error instanceof Error ? create.error.message : "Unable to add the walk-in."} />
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="secondary"
          disabled={!displayName.trim()}
          loading={create.isPending}
          loadingLabel="Adding…"
          onClick={() => create.mutate()}
        >
          Add walk-in
        </Button>
        <Button variant="quiet" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

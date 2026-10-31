import { useLayoutEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";

import { Button, ErrorText, Field, Input, useToast } from "../../components/ui";
import { staffRequest } from "../../lib/api";
import { useAuthActionOwner, type AuthAction } from "../auth/useAuthActionOwner";
import { errorText } from "./panels/shared";
import { refreshWalkInRoster } from "./refreshWalkInRoster";

type WalkInMember = { user_id: number; display_name: string; username: string };
type Creation = { owner: AuthAction; path: string; body: string; makerId: number; editable: () => boolean; created: (id: number) => void };
type Receipt = { member: WalkInMember; request: Creation };
type RefreshAttempt = { retire: () => void };

/** Naming a walk-in creates a person record, without provisioning a login. */
export function WalkInMemberForm({ makerspaceId, onCreated, disabled = false, canEdit = () => !disabled }: {
  makerspaceId: number;
  onCreated: (userId: number) => void;
  disabled?: boolean;
  canEdit?: () => boolean;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [visit, setVisit] = useState(0);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const receiptRef = useRef<Receipt | null>(null);
  const attemptRef = useRef<RefreshAttempt | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const { showToast } = useToast();
  const owner = useAuthActionOwner(`${makerspaceId}:${visit}`);
  const latestEdit = useRef(canEdit);
  latestEdit.current = canEdit;
  const current = (request: Creation) => owner.isCurrent(request.owner) && request.editable() && latestEdit.current();
  const retire = () => {
    receiptRef.current = null;
    const attempt = attemptRef.current;
    attemptRef.current = null;
    attempt?.retire();
  };
  useLayoutEffect(() => () => { retire(); }, []);
  useLayoutEffect(() => {
    if (receiptRef.current && !current(receiptRef.current.request)) {
      retire();
      setReceipt(null);
      setRefreshing(false);
    }
  });
  async function refresh(saved: Receipt) {
    // Retry keeps the original creation owner. begin() would invalidate its receipt.
    if (attemptRef.current || receiptRef.current !== saved || !current(saved.request)) return;
    const attempt: RefreshAttempt = { retire: () => {} };
    attemptRef.current = attempt; // Synchronous lock also guards forced same-tick retry clicks.
    setRefreshing(true);
    const ownsAttempt = () => attemptRef.current === attempt && receiptRef.current === saved && current(saved.request);
    try {
      const read = refreshWalkInRoster(queryClient, saved.request.makerId, saved.member.user_id, ownsAttempt);
      attempt.retire = read.retire;
      const found = await read.result;
      if (!ownsAttempt() || !found || !read.canSelect()) return;
      setDisplayName(""); setEmail(""); setPhone(""); setOpen(false);
      showToast(`${saved.member.display_name} added`, { tone: "success" });
      saved.request.created(saved.member.user_id);
      owner.cancel();
      retire();
      setReceipt(null);
      setRefreshing(false);
      setVisit((value) => value + 1);
    } catch {
      // The person is already committed. A selection failure must never enter creation's error path.
    } finally {
      if (attemptRef.current === attempt) {
        attemptRef.current = null;
        attempt.retire();
        if (current(saved.request)) setRefreshing(false);
        else retire();
      }
    }
  }
  const create = useMutation({
    mutationFn: (request: Creation) => {
      if (receiptRef.current || !current(request)) throw new Error("Walk-in form changed.");
      return staffRequest<WalkInMember>(request.path, { method: "POST", body: request.body });
    },
    onSuccess: async (member, request) => {
      if (!current(request)) return;
      const saved = { member, request };
      // Record the actual POST result before any refresh can fail, pause, or find no option.
      receiptRef.current = saved;
      setReceipt(saved);
      setDisplayName(""); setEmail(""); setPhone("");
      await refresh(saved);
    },
    onError: (error, request) => {
      if (!receiptRef.current && current(request)) showToast(errorText(error, "Couldn't add the walk-in"), { tone: "error" });
    },
    onSettled: (_data, _error, request) => { owner.finish(request.owner); },
  });
  const editable = () => owner.isIntentCurrent() && !owner.isPending() && !disabled && canEdit() && latestEdit.current();
  const saved = receipt && receiptRef.current === receipt && current(receipt.request) ? receipt : null;
  const pending = Boolean((create.isPending && create.variables && current(create.variables)) || (saved && refreshing));
  const creationEditable = () => !receiptRef.current && editable();
  const toggle = (next: boolean) => {
    if ((next && receiptRef.current) || !editable()) return;
    owner.cancel();
    retire();
    setReceipt(null);
    setRefreshing(false);
    setVisit((value) => value + 1);
    setOpen(next);
    create.reset();
  };
  const submit = () => {
    if (!open || !displayName.trim() || !creationEditable()) return;
    const token = owner.begin();
    if (!token) return;
    create.mutate({
      owner: token, path: `/admin/makerspaces/${makerspaceId}/walk-in-members`, makerId: makerspaceId,
      body: JSON.stringify({ display_name: displayName.trim(), email: email.trim(), phone: phone.trim() }),
      editable: canEdit, created: onCreated,
    });
  };

  if (!open) return (
    <Button variant="quiet" size="sm" className="mt-2 px-0" startIcon={<UserPlus />} disabled={disabled} onClick={() => toggle(true)}>
      Not in the list? Add a walk-in
    </Button>
  );
  return (
    <div className="mt-3 grid gap-4 rounded-lg border border-line bg-subtle p-4">
      <div>
        <p className="text-label text-ink">Add a walk-in</p>
        <p className="mt-0.5 text-caption text-ink-muted">Creates a person record for the handover trail. It is not an account and cannot sign in.</p>
      </div>
      {saved ? (
        <p role="status" className="text-caption text-ink">
          {saved.member.display_name} was added. {refreshing ? "Checking the borrower list…" : "Refresh the borrower list to select them."}
        </p>
      ) : <>
        <Field label="Name" id="walk-in-name">
          <Input value={displayName} disabled={disabled || pending} onChange={(event) => { if (creationEditable()) setDisplayName(event.target.value); }} />
        </Field>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Email" optional id="walk-in-email">
            <Input type="email" value={email} disabled={disabled || pending} onChange={(event) => { if (creationEditable()) setEmail(event.target.value); }} />
          </Field>
          <Field label="Phone" optional id="walk-in-phone">
            <Input type="tel" value={phone} disabled={disabled || pending} onChange={(event) => { if (creationEditable()) setPhone(event.target.value); }} />
          </Field>
        </div>
      </>}
      <ErrorText message={!saved && create.variables && current(create.variables) ? create.error?.message : undefined} />
      <div className="flex flex-wrap gap-2">
        {saved ? (
          <Button variant="secondary" disabled={disabled || pending} loading={refreshing} loadingLabel="Refreshing…" onClick={() => { if (editable()) void refresh(saved); }}>
            Refresh borrower list
          </Button>
        ) : <Button variant="secondary" disabled={disabled || !displayName.trim()} loading={pending} loadingLabel="Adding…" onClick={submit}>Add walk-in</Button>}
        <Button variant="quiet" disabled={disabled || pending} onClick={() => toggle(false)}>Cancel</Button>
      </div>
    </div>
  );
}

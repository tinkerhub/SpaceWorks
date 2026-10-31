import { useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { useToast } from "../../components/ui";
import type { RequestCartItem, RequestSubmitResponse } from "../../types/inventory";
import type { AuthAction, useAuthActionOwner } from "../auth/useAuthActionOwner";
import { saveRequestCapability, type CapabilityOutcome } from "../requests/requestCapabilities";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import { submitPublicRequest, type CheckinMatch } from "./api";
import { BorrowRequestCard } from "./BorrowRequestCard";
import type { DeskIdentity } from "./PublicRequestHeader";

type Props = {
  owner: ReturnType<typeof useAuthActionOwner>;
  slug: string;
  items: RequestCartItem[];
  identity: DeskIdentity;
  accountLess: boolean;
  checkedIn: boolean;
  confirmed: CheckinMatch | null;
  ready: boolean;
  onClear: (admitted?: RequestCartItem[]) => void;
  onComplete: (response: RequestSubmitResponse, tokenOnly: boolean, persistence?: CapabilityOutcome) => void;
  onNewDraft: () => void;
  onPending: (pending: boolean) => void;
};
type Submission = {
  slug: string;
  body: Parameters<typeof submitPublicRequest>[1];
  key?: string;
  action: AuthAction;
  items: RequestCartItem[];
  tokenOnly: boolean;
};

function newKey() {
  return globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

/** Draft state lasts for one person visit; completion is owned by the enclosing desk. */
export function PublicBorrowRequestForm({
  owner, slug, items, identity, accountLess, checkedIn, confirmed, ready,
  onClear, onComplete, onNewDraft, onPending,
}: Props) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [draft, setDraft] = useState({ requestedFor: "", contactName: "", contactEmail: "", contactPhone: "", website: "" });
  const [stored, setView] = useState<{ action: AuthAction; pending: boolean; error?: string } | null>(null);
  const view = stored && owner.isCurrent(stored.action) ? stored : null;
  const pending = view?.pending ?? false;
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null);
  const mutation = useMutation({
    mutationFn: (input: Submission) => {
      // TanStack can defer mutationFn until after a route/person/session transition.
      if (!owner.isCurrent(input.action)) throw new Error("Request context changed.");
      return submitPublicRequest(input.slug, input.body, input.key);
    },
    onSuccess: (response, input) => {
      if (!owner.isCurrent(input.action)) return;
      const persistence = response.public_token ? saveRequestCapability(input.slug, "hardware", response.public_token) : undefined;
      invalidatePublicInventory(queryClient, input.slug);
      onClear(input.items);
      attempt.current = null;
      onComplete(response, input.tokenOnly, persistence);
      showToast("Request submitted", { tone: "success" });
    },
    onError: (error, input) => {
      if (!owner.isCurrent(input.action)) return;
      setView({ action: input.action, pending: false, error: error.message });
      showToast("Your request was not submitted", { tone: "error" });
    },
    onSettled: (_data, _error, input) => {
      if (!owner.isCurrent(input.action)) return;
      setView((current) => current?.action === input.action ? { ...current, pending: false } : current);
      onPending(false);
      owner.finish(input.action);
    },
  });
  const canSubmit = ready && draft.requestedFor.trim().length > 0 && items.length > 0 &&
    (!accountLess || Boolean(draft.contactName.trim() && draft.contactEmail.trim())) &&
    (!checkedIn || confirmed !== null) && !pending;

  function edit(field: keyof typeof draft, value: string) {
    if (!owner.isContextCurrent() || owner.isPending()) return;
    onNewDraft();
    setDraft((current) => ({ ...current, [field]: value }));
  }
  function submit() {
    if (!canSubmit) return;
    const action = owner.begin();
    if (!action) return;
    const body: Submission["body"] = {
      requested_for: draft.requestedFor.trim(),
      items: items.map((item) => ({ product_id: item.productId, quantity: item.quantity })),
      website: draft.website,
      ...(accountLess ? {
        contact_name: draft.contactName.trim(), contact_email: draft.contactEmail.trim(), contact_phone: draft.contactPhone.trim(),
      } : {}),
      ...(checkedIn && confirmed ? { name: confirmed.name, checkin_mid: confirmed.mid } : {}),
    };
    const fingerprint = JSON.stringify(body);
    const previous = attempt.current;
    const submittedAttempt = previous?.fingerprint === fingerprint ? previous : { fingerprint, key: newKey() };
    attempt.current = submittedAttempt;
    const input: Submission = {
      slug, body, action, key: accountLess || checkedIn ? submittedAttempt.key : undefined,
      items: items.map((item) => ({ ...item })), tokenOnly: accountLess || checkedIn,
    };
    onNewDraft();
    onPending(true);
    setView({ action, pending: true });
    mutation.mutate(input);
  }

  return (
    <BorrowRequestCard
      canSubmit={canSubmit} items={items} requestedFor={draft.requestedFor}
      submitError={view?.error} submitPending={pending} submitted={false}
      totalItems={items.reduce((total, item) => total + item.quantity, 0)}
      onClear={() => {
        if (!owner.isContextCurrent() || owner.isPending()) return;
        onNewDraft(); onClear();
      }}
      onRequestedForChange={(value) => edit("requestedFor", value)} onSubmit={submit} identity={identity}
      contactName={draft.contactName} contactEmail={draft.contactEmail} contactPhone={draft.contactPhone}
      onContactNameChange={(value) => edit("contactName", value)}
      onContactEmailChange={(value) => edit("contactEmail", value)}
      onContactPhoneChange={(value) => edit("contactPhone", value)}
      website={draft.website} onWebsiteChange={(value) => edit("website", value)}
    />
  );
}

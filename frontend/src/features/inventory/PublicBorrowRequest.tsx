import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, Callout } from "../../components/ui";
import type { RequestCartItem, RequestSubmitResponse } from "../../types/inventory";
import { useAuthActionOwner } from "../auth/useAuthActionOwner";
import type { CapabilityOutcome } from "../requests/requestCapabilities";
import type { CheckinMatch } from "./api";
import { CheckinIdentityStep } from "./CheckinIdentityStep";
import { PublicBorrowRequestForm } from "./PublicBorrowRequestForm";
import type { DeskIdentity } from "./PublicRequestHeader";

type Props = {
  slug: string;
  items: RequestCartItem[];
  identity: DeskIdentity;
  checkedIn: boolean;
  accountLess: boolean;
  ready: boolean;
  onClear: (admitted?: RequestCartItem[]) => void;
  onComplete: (response: RequestSubmitResponse, tokenOnly: boolean, persistence?: CapabilityOutcome) => void;
  onNewDraft: () => void;
};

/** Each person gets a fresh draft without clearing the desk-owned completion. */
export function PublicBorrowRequest({ slug, items, identity, checkedIn, accountLess, ready, onClear, onComplete, onNewDraft }: Props) {
  const [confirmed, setConfirmed] = useState<CheckinMatch | null>(null);
  const [visit, setVisit] = useState(0);
  const [identityKey, setIdentityKey] = useState(0);
  const [pending, setPending] = useState(false);
  const owner = useAuthActionOwner(JSON.stringify([slug, visit, confirmed?.mid, confirmed?.name]));
  function changePerson(match: CheckinMatch | null) {
    // A synchronous admission lock also fences old event handlers before React remounts.
    const transition = owner.begin();
    if (!transition) return;
    onNewDraft();
    if (confirmed?.mid !== match?.mid || confirmed?.name !== match?.name) {
      setConfirmed(match);
      setVisit((current) => current + 1);
    } else {
      owner.finish(transition);
    }
  }

  return (
    <div onFocusCapture={() => { if (owner.isContextCurrent() && !owner.isPending()) onNewDraft(); }}>
      {checkedIn ? (
        <div className="mb-4">
          <CheckinIdentityStep key={identityKey} makerspaceSlug={slug} confirmed={confirmed}
            onConfirm={changePerson} disabled={pending} />
        </div>
      ) : null}
      <PublicBorrowRequestForm key={visit} owner={owner} slug={slug} items={items} identity={identity}
        checkedIn={checkedIn} accountLess={accountLess} confirmed={confirmed} ready={ready}
        onClear={onClear} onNewDraft={onNewDraft} onPending={setPending}
        onComplete={(response, tokenOnly, persistence) => {
          onComplete(response, tokenOnly, persistence);
          setConfirmed(null);
          setIdentityKey((current) => current + 1);
          setVisit((current) => current + 1);
          setPending(false);
        }} />
    </div>
  );
}

export type BorrowCompletion = { response: RequestSubmitResponse; tokenOnly: boolean; persistence?: CapabilityOutcome };

/** Completion stays with the Maker/auth desk, including while its draft tab is unmounted. */
export function PublicBorrowCompletion({ completion, statusHref, onStart }: {
  completion: BorrowCompletion; statusHref?: string; onStart: () => void;
}) {
  return (
    <Callout className="mt-4" tone="success" role="status" title="Request submitted">
      <p>{completion.tokenOnly
        ? "Keep this private reference. Requests made without an account need their private link to check status."
        : "It is filed under your account. Staff review it before anything is handed over. Keep this private link to check its status."}</p>
      {completion.response.public_token ? <>
        <p className="mt-2 break-all rounded-md bg-canvas px-2 py-1 font-mono text-xs text-ink">{completion.response.public_token}</p>
        {statusHref ? <Link className="mt-2 inline-block font-semibold underline underline-offset-4"
          to={`${statusHref}?token=${encodeURIComponent(completion.response.public_token)}`}>Check its status</Link> : null}
        {completion.persistence?.saved ? <p className="mt-2 text-caption">Saved on this browser. Open My requests to reveal saved links.</p> : null}
        {completion.persistence?.warning ? <p className="mt-2 text-body-ui" role="status">{completion.persistence.warning}</p> : null}
      </> : null}
      <Button className="mt-3" variant="quiet" onClick={onStart}>Start another request</Button>
    </Callout>
  );
}

import { useState } from "react";

import { Card } from "../../components/ui";
import { getSessionGeneration } from "../../lib/apiSession";
import type { RequestCartItem } from "../../types/inventory";
import { PublicBorrowCompletion, PublicBorrowRequest, type BorrowCompletion } from "./PublicBorrowRequest";
import { useAuthActionOwner } from "../auth/useAuthActionOwner";
import { PublicRequestHeader, type DeskIdentity } from "./PublicRequestHeader";
import { useCheckinProvider } from "./useCheckinProvider";
import { usePublicSession } from "./usePublicSession";
import { PublicToolScanPanel } from "./PublicToolScanPanel";
import { RequestDeskTabs, type ActiveTab } from "./RequestDeskTabs";

type PublicRequestPanelProps = {
  items: RequestCartItem[];
  makerspaceSlug: string;
  onClear: (admitted?: RequestCartItem[]) => void;
  disabled?: boolean;
  // The makerspace's policy, not the caller's state. Present only when the space opted
  // into account-less borrow requests.
  requestAccess?: "anyone" | "checked_in";
  // Whether the `membership` module is on: it decides between the `members` and
  // `accounts` policies when `requestAccess` is absent, and whether self-checkout can
  // work at all off the check-in roster (it needs membership, waiver and presence).
  membershipOn?: boolean;
  // The `inventory.self_checkout` feature. Off (or unusable) hides the scan tab.
  selfCheckout?: boolean;
  // The `member_accounts` module: whether a signed-out visitor has anywhere to sign in, and
  // where that is. Off, the only accounts are staff accounts.
  memberAccountsOn?: boolean;
  memberAreaHref?: string;
  requestStatusHref?: string;
};

export function PublicRequestPanel(props: PublicRequestPanelProps) {
  const session = usePublicSession(props.makerspaceSlug, props.requestAccess !== "checked_in" && !props.disabled);
  // The public selection is outside this boundary and may survive same-Maker sign-in.
  const scope = JSON.stringify([props.makerspaceSlug, getSessionGeneration(), props.requestAccess,
    props.membershipOn, props.disabled]);
  return <PublicRequestDesk key={scope} {...props} session={session} />;
}

function PublicRequestDesk({
  items, makerspaceSlug, onClear, disabled = false, requestAccess, membershipOn = false,
  selfCheckout = false, memberAccountsOn = true, memberAreaHref, requestStatusHref, session,
}: PublicRequestPanelProps & { session: ReturnType<typeof usePublicSession> }) {
  const completionOwner = useAuthActionOwner(makerspaceSlug);
  const [completion, setCompletion] = useState<(BorrowCompletion & { context: typeof completionOwner.context }) | null>(null);
  const [draftVisit, setDraftVisit] = useState(0);
  const visibleCompletion = completion?.context === completionOwner.context ? completion : null;
  const clearCompletion = () => { if (completionOwner.isContextCurrent()) setCompletion(null); };
  const [selectedTab, setActiveTab] = useState<ActiveTab>("borrow");
  const scanAvailable = selfCheckout && (requestAccess === "checked_in" || membershipOn);
  const activeTab = scanAvailable ? selectedTab : "borrow";
  const { authenticated, settled: sessionSettled } = session;
  const checkedIn = requestAccess === "checked_in";
  const accountLess = requestAccess === "anyone" && sessionSettled && !authenticated;
  const signedOut = !requestAccess && sessionSettled && !authenticated;
  const checkinProvider = useCheckinProvider(makerspaceSlug);
  const borrowIdentity: DeskIdentity = checkedIn ? "checkin" : accountLess ? "contact"
    : signedOut && !memberAccountsOn ? "desk" : signedOut && !membershipOn ? "signin"
      : requestAccess || !membershipOn ? "account" : "member";

  return (
    <aside className="min-w-0 space-y-4">
      {disabled ? (
        <Card>
          <p className="text-body-ui text-ink-muted">Requests</p>
          <h2 className="mt-1 text-h4 text-ink">Unavailable</h2>
          <p className="mt-2 text-body-ui text-ink-secondary">This makerspace is publishing inventory without public requests.</p>
        </Card>
      ) : (
        <>
          <PublicRequestHeader appearsIn={checkinProvider.appearsIn} tab={activeTab}
            identity={activeTab === "scan" ? (checkedIn ? "checkin" : "member") : borrowIdentity}
            requestAccess={requestAccess} authenticated={authenticated}
            signInHref={signedOut && memberAccountsOn ? memberAreaHref : undefined} />
          {scanAvailable ? <RequestDeskTabs activeTab={activeTab} onChange={setActiveTab} /> : null}
          <div className="min-w-0">
            {activeTab === "borrow" ? (
              <div id="public-request-borrow-panel">
                <PublicBorrowRequest key={draftVisit} slug={makerspaceSlug} items={items} identity={borrowIdentity}
                  checkedIn={checkedIn} accountLess={accountLess} ready={!signedOut && (checkedIn || sessionSettled)}
                  onClear={onClear} onNewDraft={clearCompletion}
                  onComplete={(response, tokenOnly, persistence) => {
                    if (completionOwner.isContextCurrent()) setCompletion({ response, tokenOnly, persistence, context: completionOwner.context });
                  }} />
                {visibleCompletion ? <PublicBorrowCompletion completion={visibleCompletion} statusHref={requestStatusHref}
                  onStart={() => {
                    if (!completionOwner.isContextCurrent()) return;
                    clearCompletion(); setDraftVisit((current) => current + 1);
                  }} /> : null}
              </div>
            ) : null}
            {activeTab === "scan" ? (
              <div id="public-request-scan-panel">
                <PublicToolScanPanel makerspaceSlug={makerspaceSlug} requiresCheckin={checkedIn} />
              </div>
            ) : null}
          </div>
        </>
      )}
    </aside>
  );
}

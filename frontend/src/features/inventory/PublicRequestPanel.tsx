import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Card, useToast } from "../../components/ui";
import type { RequestCartItem } from "../../types/inventory";
import { BorrowRequestCard } from "./BorrowRequestCard";
import { getAccessToken, refreshAccessToken } from "../../lib/api";
import { submitPublicRequest, type CheckinMatch } from "./api";
import { CheckinIdentityStep } from "./CheckinIdentityStep";
import { invalidatePublicInventory } from "../staff/queryInvalidation";
import { PublicRequestHeader, type DeskIdentity } from "./PublicRequestHeader";
import { useCheckinProvider } from "./useCheckinProvider";
import { PublicToolScanPanel } from "./PublicToolScanPanel";
import { RequestDeskTabs, type ActiveTab } from "./RequestDeskTabs";

type PublicRequestPanelProps = {
  items: RequestCartItem[];
  makerspaceSlug: string;
  onClear: () => void;
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
};

// The header is required for account-less submissions, and it is what makes a retry
// idempotent: the same key with the same payload returns the original request. Held for
// the lifetime of one composed request and rotated only after a successful submit, so a
// network retry of the SAME attempt cannot create a second request.
function newIdempotencyKey() {
  const cryptoRef = globalThis.crypto;
  if (cryptoRef && typeof cryptoRef.randomUUID === "function") {
    return cryptoRef.randomUUID();
  }
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
}

export function PublicRequestPanel({
  items,
  makerspaceSlug,
  onClear,
  disabled = false,
  requestAccess,
  membershipOn = false,
  selfCheckout = false,
  memberAccountsOn = true,
  memberAreaHref,
}: PublicRequestPanelProps) {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [selectedTab, setActiveTab] = useState<ActiveTab>("borrow");
  // Self-checkout off the roster runs `require_active_member_presence`, which no caller
  // can satisfy with `membership` off -- so the tab is offered only where it can work.
  const scanAvailable = selfCheckout && (requestAccess === "checked_in" || membershipOn);
  const activeTab: ActiveTab = scanAvailable ? selectedTab : "borrow";
  const [requestedFor, setRequestedFor] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [contactName, setContactName] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [website, setWebsite] = useState("");
  const [confirmedCheckin, setConfirmedCheckin] = useState<CheckinMatch | null>(null);
  const [publicToken, setPublicToken] = useState("");
  const idempotencyKey = useRef(newIdempotencyKey());
  // A signed-in member who RELOADED this page holds no in-memory access token -- it lives
  // behind the refresh cookie, and unlike `MemberArea` this page never hydrates. Without
  // the probe they would be classified as anonymous and their request filed against the
  // SHARED anonymous principal, which every per-person view excludes: it would vanish from
  // their own activity and take the unverified-contact path instead of notifying them.
  const sessionProbe = useQuery({
    queryKey: ["public-request-session", makerspaceSlug],
    queryFn: async () => (getAccessToken() ? true : refreshAccessToken()),
    // On `checked_in` the roster is the identity for everyone, signed in or not, so there is
    // nothing to probe. Every other policy files the request under the signed-in caller, and
    // without the probe a reload made a signed-in borrower's submit go out bare and 401.
    enabled: requestAccess !== "checked_in" && !disabled,
    staleTime: Infinity,
    retry: false,
  });
  const authenticated = sessionProbe.data === true || Boolean(getAccessToken());
  // Policy AND caller state. `tenantPublicRequest` still attaches Authorization when a
  // token is in memory, and the backend then takes the AUTHENTICATED branch and ignores
  // these contact fields -- so asking for them would promise something the stored request
  // does not honour. Until the probe settles we assume a member: claiming "no account
  // needed" and then discovering a session would be the worse way round.
  const accountLess =
    requestAccess === "anyone" && sessionProbe.isFetched && !authenticated;
  // Mirrors `RequestSubmitView`: the roster on `checked_in` for everyone (a signed-in
  // account, staff included, is not a bypass), contact details on `anyone` without a
  // session, otherwise the caller's own account (membership, waiver and presence only
  // with `membership` on).
  const checkedIn = requestAccess === "checked_in";
  const checkinProvider = useCheckinProvider(makerspaceSlug);
  // The `accounts` and `members` policies with nobody signed in: the backend can only 401,
  // so the desk says where to sign in -- or, with no member accounts, that there is nowhere.
  const signedOut = !requestAccess && sessionProbe.isFetched && !authenticated;
  const borrowIdentity: DeskIdentity = checkedIn
    ? "checkin"
    : accountLess
      ? "contact"
      : signedOut && !memberAccountsOn
        ? "desk"
        : signedOut && !membershipOn
          ? "signin"
          : requestAccess || !membershipOn
            ? "account"
            : "member";
  const totalItems = useMemo(
    () => items.reduce((total, item) => total + item.quantity, 0),
    [items],
  );

  const submitMutation = useMutation({
    mutationFn: () =>
      submitPublicRequest(
        makerspaceSlug,
        {
          requested_for: requestedFor.trim(),
          items: items.map((item) => ({
            product_id: item.productId,
            quantity: item.quantity,
          })),
          website,
          ...(accountLess
            ? {
                contact_name: contactName.trim(),
                contact_email: contactEmail.trim(),
                contact_phone: contactPhone.trim(),
              }
            : {}),
          // No contact fields on this policy: identity is the roster match.
          ...(checkedIn && confirmedCheckin
            ? { name: confirmedCheckin.name, checkin_mid: confirmedCheckin.mid }
            : {}),
        },
        accountLess || checkedIn ? idempotencyKey.current : undefined,
      ),
    // The previous banner and token must not survive into the next attempt: if this one
    // fails, showing the error beside a stale token invites the requester to save the
    // wrong reference -- and it is their only route back to the request.
    onMutate: () => {
      setSubmitted(false);
      setPublicToken("");
    },
    onSuccess: (response) => {
      invalidatePublicInventory(queryClient, makerspaceSlug);
      // Kept before the form is cleared: this token is the account-less requester's only
      // way back to the request.
      setPublicToken(response?.public_token ?? "");
      setSubmitted(true);
      onClear();
      setContactName("");
      setContactEmail("");
      setContactPhone("");
      setRequestedFor("");
      setWebsite("");
      // Only after the server accepted it: reusing the key for the NEXT request would
      // return this one back instead of creating anything.
      idempotencyKey.current = newIdempotencyKey();
      showToast("Request submitted", { tone: "success" });
    },
    onError: () => showToast("Your request was not submitted", { tone: "error" }),
  });

  const contactReady =
    !accountLess ||
    (contactName.trim().length > 0 && contactEmail.trim().length > 0);
  // On the checked-in policy the confirmed roster entry IS the identity, so submitting
  // without one would post a request the backend can only refuse.
  const identityReady = !checkedIn || confirmedCheckin !== null;
  // While the probe is unresolved `accountLess` is still false, so `contactReady` is
  // vacuously true and the button would go live before the contact fields exist. On a
  // slow refresh a visitor could submit a member-shaped body and take a 400.
  const policyResolved = checkedIn || sessionProbe.isFetched;
  const canSubmit =
    !signedOut &&
    requestedFor.trim().length > 0 &&
    items.length > 0 &&
    contactReady &&
    identityReady &&
    policyResolved &&
    !submitMutation.isPending;

  return (
    <aside className="space-y-4 lg:sticky lg:top-20 lg:flex lg:max-h-[calc(100dvh-6rem)] lg:flex-col lg:overflow-hidden">
      {disabled ? (
        <Card>
          <p className="text-body-ui text-ink-muted">Requests</p>
          <h2 className="mt-1 text-h4 text-ink">Unavailable</h2>
          <p className="mt-2 text-body-ui text-ink-secondary">
            This makerspace is publishing inventory without public requests.
          </p>
        </Card>
      ) : (
        <>
          <PublicRequestHeader
            appearsIn={checkinProvider.appearsIn}
            tab={activeTab}
            identity={activeTab === "scan" ? (requestAccess === "checked_in" ? "checkin" : "member") : borrowIdentity}
            requestAccess={requestAccess}
            // A signed-in caller is only known NOT to be a member here once the probe
            // settles; until then the borrow desk must not tell staff they are outsiders.
            authenticated={authenticated}
            signInHref={signedOut && memberAccountsOn ? memberAreaHref : undefined}
          />

          {scanAvailable ? <RequestDeskTabs activeTab={activeTab} onChange={setActiveTab} /> : null}

          <div className="lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
            {activeTab === "borrow" ? (
              <div
                id="public-request-borrow-panel"
              >
                {checkedIn ? (
                  <div className="mb-4">
                    <CheckinIdentityStep
                      makerspaceSlug={makerspaceSlug}
                      confirmed={confirmedCheckin}
                      onConfirm={setConfirmedCheckin}
                      disabled={submitMutation.isPending || submitted}
                    />
                  </div>
                ) : null}
                <BorrowRequestCard
                  canSubmit={canSubmit}
                  items={items}
                  requestedFor={requestedFor}
                  submitError={submitMutation.error?.message}
                  submitPending={submitMutation.isPending}
                  submitted={submitted}
                  totalItems={totalItems}
                  onClear={onClear}
                  onRequestedForChange={setRequestedFor}
                  onSubmit={() => submitMutation.mutate()}
                  identity={borrowIdentity}
                  contactName={contactName}
                  contactEmail={contactEmail}
                  contactPhone={contactPhone}
                  onContactNameChange={setContactName}
                  onContactEmailChange={setContactEmail}
                  onContactPhoneChange={setContactPhone}
                  website={website}
                  onWebsiteChange={setWebsite}
                  publicToken={publicToken}
                />
              </div>
            ) : null}

            {activeTab === "scan" ? (
              <div id="public-request-scan-panel">
                <PublicToolScanPanel
                  makerspaceSlug={makerspaceSlug}
                  requiresCheckin={requestAccess === "checked_in"}
                />
              </div>
            ) : null}
          </div>
        </>
      )}
    </aside>
  );
}

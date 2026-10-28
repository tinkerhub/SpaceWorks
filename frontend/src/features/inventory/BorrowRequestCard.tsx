import { Link } from "react-router-dom";

import { Button, Callout, Card, Chip, ErrorText, Field, Input, Textarea } from "../../components/ui";
import type { RequestCartItem } from "../../types/inventory";
import type { DeskIdentity } from "./PublicRequestHeader";

const EMPTY_HINT: Record<DeskIdentity, string> = {
  contact: "Add public items from the inventory list, then leave your name and email to submit the request.",
  checkin: "Add public items from the inventory list, confirm your check-in name, then submit the request.",
  account: "Add public items from the inventory list, then submit the request from your signed-in account.",
  member: "Add public items from the inventory list, then submit the request with your signed-in member account.",
  signin: "Add public items from the inventory list, then sign in to submit the request.",
  desk: "Staff at the desk can lend you anything listed here.",
};

type BorrowRequestCardProps = {
  canSubmit: boolean;
  items: RequestCartItem[];
  requestedFor: string;
  submitError?: string;
  submitPending: boolean;
  submitted: boolean;
  totalItems: number;
  onClear: () => void;
  onRequestedForChange: (value: string) => void;
  onSubmit: () => void;
  // Who the request is filed under. `contact` is the account-less mode: the borrower has
  // no profile to read a name and email from and must supply them here. `checkin` has no
  // account either, so its public token is the borrower's only handle on the request.
  identity: DeskIdentity;
  contactName?: string;
  contactEmail?: string;
  contactPhone?: string;
  onContactNameChange?: (value: string) => void;
  onContactEmailChange?: (value: string) => void;
  onContactPhoneChange?: (value: string) => void;
  // Honeypot, carried by every other public form (booking, printing, events). A bot that
  // autofills it gets the server's decoy response instead of a real request.
  website?: string;
  onWebsiteChange?: (value: string) => void;
  // The ONLY handle an account-less requester has on their request: their contact details
  // are unverified so no lifecycle email is sent, and status lookup is by token.
  publicToken?: string;
  // Where that token can be looked up again.
  statusHref?: string;
};

export function BorrowRequestCard({
  canSubmit,
  items,
  requestedFor,
  submitError,
  submitPending,
  submitted,
  totalItems,
  onClear,
  onRequestedForChange,
  onSubmit,
  identity,
  contactName = "",
  contactEmail = "",
  contactPhone = "",
  onContactNameChange,
  onContactEmailChange,
  onContactPhoneChange,
  website = "",
  onWebsiteChange,
  publicToken,
  statusHref,
}: BorrowRequestCardProps) {
  const accountLess = identity === "contact";
  const tokenOnly = accountLess || identity === "checkin";
  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-body-ui text-ink-muted">Borrow request</p>
          <h2 className="mt-1 text-h4 text-ink">Selected equipment</h2>
        </div>
        <Chip tone="secondary" className="tabular-nums">{totalItems}</Chip>
      </div>

      {items.length === 0 ? (
        <p className="mt-4 rounded-md border-[1.5px] border-dashed border-line-strong px-3 py-3 text-body-ui text-ink-muted">
          {EMPTY_HINT[identity]}
        </p>
      ) : (
        <div className="mt-4 space-y-2">
          <ul className="max-h-40 divide-y divide-line overflow-y-auto rounded-md border border-line">
            {items.map((item) => (
              <li className="flex items-center justify-between gap-3 px-3 py-2" key={item.productId}>
                <span className="min-w-0 flex-1 text-body-ui font-medium text-ink [overflow-wrap:anywhere]">{item.name}</span>
                <span className="shrink-0 font-mono text-sm tabular-nums text-ink-muted">×{item.quantity}</span>
              </li>
            ))}
          </ul>
          <Button variant="quiet" size="sm" onClick={onClear}>
            Clear selection
          </Button>
        </div>
      )}

      <div className="mt-5 space-y-4">
        {accountLess ? (
          <>
            <Field label="Your name">
              <Input
                autoComplete="name"
                maxLength={200}
                placeholder="Ada Lovelace"
                type="text"
                value={contactName}
                onChange={(event) => onContactNameChange?.(event.target.value)}
              />
            </Field>
            <Field label="Email" helperText="Staff use this to reach you about the request.">
              <Input
                autoComplete="email"
                maxLength={254}
                placeholder="you@example.com"
                type="email"
                value={contactEmail}
                onChange={(event) => onContactEmailChange?.(event.target.value)}
              />
            </Field>
            <Field label="Phone" optional>
              <Input
                autoComplete="tel"
                maxLength={32}
                placeholder="+44 20 1234 5678"
                type="tel"
                value={contactPhone}
                onChange={(event) => onContactPhoneChange?.(event.target.value)}
              />
            </Field>
          </>
        ) : null}
        <label aria-hidden="true" className="absolute left-[-10000px] top-auto h-px w-px overflow-hidden">
          Website
          <input
            autoComplete="off"
            name="website"
            tabIndex={-1}
            value={website}
            onChange={(event) => onWebsiteChange?.(event.target.value)}
          />
        </label>
        <Field label="Request purpose">
          <Textarea
            placeholder="What do you need these items for?"
            value={requestedFor}
            onChange={(event) => onRequestedForChange(event.target.value)}
          />
        </Field>
        <Button variant="primary" fullWidth disabled={!canSubmit} loading={submitPending} loadingLabel="Submitting…" onClick={onSubmit}>
          Submit request
        </Button>
        <ErrorText message={submitError} />
        {submitted ? (
          <Callout tone="success" role="status" title="Request submitted">
            {tokenOnly ? (
              <>
                <p>Save this reference: a request made without an account has no sign-in to come back to, and staff will ask for it.</p>
                {publicToken ? (
                  <>
                    <p className="mt-2 break-all rounded-md bg-canvas px-2 py-1 font-mono text-xs text-ink">{publicToken}</p>
                    {statusHref ? (
                      <Link className="mt-2 inline-block font-semibold underline underline-offset-4" to={`${statusHref}?token=${encodeURIComponent(publicToken)}`}>
                        Check its status
                      </Link>
                    ) : null}
                  </>
                ) : null}
              </>
            ) : (
              <p>It is filed under your account. Staff review it before anything is handed over.</p>
            )}
          </Callout>
        ) : null}
      </div>
    </Card>
  );
}

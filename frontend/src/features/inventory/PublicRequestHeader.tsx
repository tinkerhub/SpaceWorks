import { Link } from "react-router-dom";

import { Card, buttonClasses } from "../../components/ui";

/**
 * Who a request is filed under, which is what the desk copy has to describe:
 * - `contact`: no account, the visitor leaves a name and email (`anyone` policy).
 * - `checkin`: no account, the visitor is matched against the upstream check-in roster.
 * - `account`: the caller's own signed-in account, with no membership requirement.
 * - `member`: a signed-in member with membership, waiver and presence (`membership` on).
 * - `signin`: the `accounts` policy with nobody signed in, where member sign-in exists.
 * - `desk`: an account is required but this space has no member accounts to sign in with.
 */
export type DeskIdentity = "contact" | "checkin" | "account" | "member" | "signin" | "desk";
export type DeskTab = "borrow" | "scan";

type Props = {
  tab: DeskTab;
  identity: DeskIdentity;
  requestAccess?: "anyone" | "checked_in";
  authenticated: boolean;
  /** Where the borrower's check-in name is shown, e.g. "in TinkerHub" (useCheckinProvider). */
  appearsIn?: string;
  /** A signed-out borrower who must sign in first: where to do it. */
  signInHref?: string;
};

const REVIEW = "Staff review it before anything is handed over.";
const MEMBER_RULES = "An active membership, waiver acceptance, and current presence are required.";

/**
 * The copy mirrors the backend branch exactly (`RequestSubmitView` for borrow requests,
 * the public tool views for scanning), because every sentence here is a promise:
 * membership, waivers and presence only exist with the `membership` module on, and on the
 * `checked_in` policy every borrower -- signed in or not, staff included -- is matched
 * against the roster, for borrow requests and self-checkout alike.
 */
export function deskCopy({ tab, identity, requestAccess, authenticated, appearsIn = "on the check-in list" }: Props): { title: string; body: string } {
  if (tab === "scan") {
    if (identity === "checkin") {
      return {
        title: "Scan a tool with check-in",
        body: `No account needed. Confirm your name as it appears ${appearsIn}, add a photo, then scan the tool's QR label. The checkout is recorded under that check-in name${authenticated ? ", even while you are signed in" : ""}.`,
      };
    }
    return { title: "Member self-checkout", body: `Self-checkout uses your signed-in member account. ${MEMBER_RULES}` };
  }
  switch (identity) {
    case "contact":
      return {
        title: "Borrow something",
        body: "No account needed. Leave your name and email so staff can reach you about the request; they review it before anything is handed over.",
      };
    case "checkin":
      return {
        title: "Borrow with check-in",
        body: authenticated
          ? `Borrowing here always uses check-in, even while you are signed in. Confirm your name as it appears ${appearsIn} against the upstream check-in roster; the request is filed under that check-in name. ${REVIEW}`
          : `No account needed. Confirm your name as it appears ${appearsIn} against the upstream check-in roster; staff review the request before anything is handed over.`,
      };
    case "account":
      return {
        title: "Borrow with your account",
        body:
          requestAccess === "anyone"
            ? `You are signed in, so this request is filed against your account. ${REVIEW}`
            : "Requests are filed under a signed-in account. Staff review them before anything is handed over.",
      };
    case "member":
      return { title: "Member borrowing", body: `Requests use your signed-in member account. ${MEMBER_RULES}` };
    case "signin":
      return { title: "Borrow with your account", body: `Your request is filed under your account, so sign in first. ${REVIEW}` };
    case "desk":
      return {
        title: "Borrow at the desk",
        body: "Requests here are filed under an account, and this makerspace offers no public sign-up. Ask staff at the desk to lend you what you need.",
      };
  }
}

export function PublicRequestHeader(props: Props) {
  const { title, body } = deskCopy(props);
  return (
    <Card className="shrink-0">
      <p className="text-body-ui text-ink-muted">Request desk</p>
      <h2 className="mt-1 text-h4 text-ink">{title}</h2>
      <p className="mt-2 max-w-[65ch] text-body-ui text-ink-secondary">{body}</p>
      {props.signInHref ? (
        <Link className={buttonClasses({ variant: "secondary", size: "sm", className: "mt-3" })} to={props.signInHref}>Sign in</Link>
      ) : null}
    </Card>
  );
}

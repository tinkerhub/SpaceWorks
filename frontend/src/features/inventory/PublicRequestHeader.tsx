import { Card } from "../../components/ui";

/**
 * Who a request is filed under, which is what the desk copy has to describe:
 * - `contact`: no account, the visitor leaves a name and email (`anyone` policy).
 * - `checkin`: no account, the visitor is matched against the upstream check-in roster.
 * - `account`: the caller's own signed-in account, with no membership requirement.
 * - `member`: a signed-in member with membership, waiver and presence (`membership` on).
 */
export type DeskIdentity = "contact" | "checkin" | "account" | "member";
export type DeskTab = "borrow" | "scan";

type Props = {
  tab: DeskTab;
  identity: DeskIdentity;
  requestAccess?: "anyone" | "checked_in";
  authenticated: boolean;
};

const REVIEW = "Staff review it before anything is handed over.";
const MEMBER_RULES = "An active membership, waiver acceptance, and current presence are required.";

/**
 * The copy mirrors the backend branch exactly (`RequestSubmitView` for borrow requests,
 * the public tool views for scanning), because every sentence here is a promise:
 * membership, waivers and presence only exist with the `membership` module on, and a
 * signed-in caller on the `checked_in` policy is filed under their own account only when
 * they hold an active membership at THIS makerspace -- anyone else is matched against the
 * roster. Self-checkout on `checked_in` always uses the roster, signed in or not.
 */
export function deskCopy({ tab, identity, requestAccess, authenticated }: Props): { title: string; body: string } {
  if (tab === "scan") {
    if (identity === "checkin") {
      return {
        title: "Scan a tool with check-in",
        body: `No account needed. Confirm your name as it appears in TinkerHub, add a photo, then scan the tool's QR label. The checkout is recorded under that check-in name${authenticated ? ", even while you are signed in" : ""}.`,
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
          ? `Your account is not part of this makerspace, so confirm your name as it appears in TinkerHub against the upstream check-in roster. The request is filed under that check-in name. ${REVIEW}`
          : "No account needed. Confirm your name as it appears in TinkerHub against the upstream check-in roster; staff review the request before anything is handed over.",
      };
    case "account":
      return {
        title: "Borrow with your account",
        body:
          requestAccess === "checked_in"
            ? `You are signed in to this makerspace, so the request is filed under your account and needs no check-in name. ${REVIEW}`
            : requestAccess === "anyone"
              ? `You are signed in, so this request is filed against your account. ${REVIEW}`
              : "Requests are filed under a signed-in account. Staff review them before anything is handed over.",
      };
    case "member":
      return { title: "Member borrowing", body: `Requests use your signed-in member account. ${MEMBER_RULES}` };
  }
}

export function PublicRequestHeader(props: Props) {
  const { title, body } = deskCopy(props);
  return (
    <Card className="shrink-0">
      <p className="text-body-ui text-ink-muted">Request desk</p>
      <h2 className="mt-1 text-h4 text-ink">{title}</h2>
      <p className="mt-2 text-body-ui text-ink-secondary">{body}</p>
    </Card>
  );
}

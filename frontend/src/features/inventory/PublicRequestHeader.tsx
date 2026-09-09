import { Card } from "../../components/ui/Card";

type Props = {
  accountLess: boolean;
  activeTab: "borrow" | "scan";
  checkedIn: boolean;
  requestAccess?: "anyone" | "checked_in";
};

export function PublicRequestHeader({
  accountLess,
  activeTab,
  checkedIn,
  requestAccess,
}: Props) {
  return (
    <Card className="shrink-0" padding="sm">
      <h2 className="title-panel text-secondary-ink">
        {activeTab === "borrow" && accountLess
          ? "Borrow something"
          : activeTab === "borrow" && checkedIn
            ? "Borrow with check-in"
            : "Member borrowing"}
      </h2>
      <p className="mt-2 text-sm text-muted">
        {/* Four states, because the requirements genuinely differ. Scoped to the
            borrow tab: scanning a tool is self-checkout, which DOES require an
            authenticated member with active presence, so "no account needed" would
            be false there until it 401s. The checked-in path instead confirms the
            visitor against the upstream roster, with no account, membership or waiver.
            And an `anyone` policy necessarily has the membership module off, so the
            membership/waiver/presence sentence cannot be true on such a space even for
            a signed-in visitor. */}
        {activeTab === "borrow" && accountLess
          ? "No account needed. Leave your name and email so staff can reach you about the request; they review it before anything is handed over."
          : activeTab === "borrow" && checkedIn
            ? "No account needed. Confirm your name as it appears in TinkerHub against the upstream check-in roster; staff review the request before anything is handed over."
            : activeTab === "borrow" && requestAccess === "anyone"
              ? "You are signed in, so this request is filed against your account. Staff review it before anything is handed over."
              : "Requests use your signed-in member account. An active membership, waiver acceptance, and current presence are required."}
      </p>
    </Card>
  );
}

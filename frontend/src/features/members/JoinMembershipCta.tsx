import type { MembershipPolicyEnum } from "../../generated/api";
import { Button } from "../../components/ui";
import { AccountCard } from "../account/AccountCard";

export type JoinCtaState = {
  title: string;
  description: string;
  action: "join" | "sign_in" | "none";
  actionLabel?: string;
};

export function joinCtaState(policy: MembershipPolicyEnum, signedIn: boolean): JoinCtaState {
  if (policy === "invite_only") {
    return {
      title: "Invite-only makerspace",
      description: "This makerspace does not accept self-join requests. Ask a space manager for an invitation.",
      action: "none",
    };
  }
  const instantly = policy === "open";
  return {
    title: "Join this makerspace",
    description: instantly ? "You will become a member immediately." : "Your request will be sent to staff for approval.",
    action: signedIn ? "join" : "sign_in",
    actionLabel: signedIn ? (instantly ? "Join instantly" : "Request to join") : "Sign in to join",
  };
}

export function JoinMembershipCta({ policy, signedIn, pending, onJoin, onSignIn }: {
  policy: MembershipPolicyEnum;
  signedIn: boolean;
  pending: boolean;
  onJoin: () => void;
  onSignIn: () => void;
}) {
  const state = joinCtaState(policy, signedIn);
  return (
    <AccountCard
      title={state.title}
      description={state.description}
      action={state.action !== "none" ? (
        <Button
          variant="primary"
          loading={pending && state.action === "join"}
          loadingLabel="Sending…"
          onClick={state.action === "join" ? onJoin : onSignIn}
        >
          {state.actionLabel}
        </Button>
      ) : null}
    />
  );
}

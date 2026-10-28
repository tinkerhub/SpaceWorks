import { Link } from "react-router-dom";

import { Callout, buttonClasses } from "../../components/ui";

/** Shown before an account-only public form, so a signed-out visitor is not refused on submit. */
export function PublicSignInCallout({ href, children }: { href?: string; children: string }) {
  return (
    <Callout
      title={href ? "Sign in to continue" : "An account is required"}
      action={href ? <Link className={buttonClasses({ variant: "primary", size: "sm" })} to={href}>Sign in</Link> : undefined}
    >
      {href ? children : `${children} This makerspace offers no public sign-up, so ask staff at the desk.`}
    </Callout>
  );
}

export function memberSignInHref(homePath: string, memberAccountsOn: boolean) {
  return memberAccountsOn ? `${homePath.replace(/\/+$/, "")}/member` : undefined;
}

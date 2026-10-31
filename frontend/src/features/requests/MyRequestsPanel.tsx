import { Link, useLocation } from "react-router-dom";
import { Card } from "../../components/ui";
import { getSessionGeneration } from "../../lib/api";
import { usePublicSession } from "../inventory/usePublicSession";
import { OwnRequests } from "./OwnRequests";
import { SavedRequests } from "./SavedRequests";

type Props = {
  slug: string; hardwareOn: boolean; machineOn: boolean; memberAccountsOn: boolean;
  basePath: string; memberAreaHref?: string;
};
export function MyRequestsPanel(props: Props) {
  const session = usePublicSession(props.slug, props.memberAccountsOn && (props.hardwareOn || props.machineOn));
  const location = useLocation();
  const generation = getSessionGeneration();
  // A new route visit, tenant or installed/cleared session destroys the private subtree.
  const boundary = JSON.stringify([props.slug, generation, session.authenticated, location.key]);
  return <div key={boundary} className="space-y-8">
    {session.authenticated ? <OwnRequests {...props} generation={generation} />
      : props.memberAccountsOn ? <Card>
        <p className="text-body-ui text-ink-secondary">{!session.settled ? "Checking account sign-in…" : "Sign in to view requests filed under your account."}</p>
        {session.settled && props.memberAreaHref ? <Link to={props.memberAreaHref}
          className="mt-3 inline-block text-body-ui font-semibold text-ink underline underline-offset-4">Open member area to sign in</Link> : null}
      </Card> : null}
    <SavedRequests {...props} generation={generation} />
  </div>;
}

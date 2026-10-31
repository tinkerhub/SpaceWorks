import { Link } from "react-router-dom";

import { SkipLink } from "../../components/SkipLink";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Button, Callout, PageHeader } from "../../components/ui";
import type { Makerspace } from "./StaffPanels";
import { MakerspaceChoices } from "./MakerspaceChoices";

/**
 * Superadmin entry screen: the superadmin operates one makerspace at a time, so
 * before the console loads they explicitly pick which makerspace to operate. The
 * chosen id then scopes every staff API call (the backend already takes a
 * makerspace_id per request). Reachable again via "Switch makerspace" in the shell.
 */
export function MakerspacePicker({
  makerspaces,
  loading,
  error = false,
  unavailable = false,
  globalAdmin = true,
  platformAvailable = false,
  originLocked = false,
  onRetry,
  username,
  onSelect,
  onSignOut,
}: {
  makerspaces: Makerspace[];
  loading: boolean;
  error?: boolean;
  unavailable?: boolean;
  globalAdmin?: boolean;
  platformAvailable?: boolean;
  originLocked?: boolean;
  onRetry?: () => void;
  username: string;
  onSelect: (id: number) => void;
  onSignOut: () => void;
}) {
  return (
    <div className="flex min-h-dvh flex-col bg-subtle text-ink">
      <SkipLink />
      <header className="flex items-center justify-between gap-3 px-4 py-4 sm:px-6">
        <SpaceWorksBadge />
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Button variant="secondary" size="sm" onClick={onSignOut}>
            Sign out
          </Button>
        </div>
      </header>
      <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-3xl flex-1 px-4 pb-12 pt-6 sm:px-6">
        <PageHeader
          kicker={globalAdmin ? "Super Admin" : "Staff console"}
          title={unavailable ? "Makerspace unavailable" : "Choose a makerspace to operate"}
          description={`Signed in as ${username}. Choose a makerspace available to this account from this site.`}
        />
        {unavailable ? (
          <Callout tone="warning" className="mt-6">
            This makerspace is unavailable to this account from this site. Choose an allowed makerspace below or sign out.
          </Callout>
        ) : null}
        {platformAvailable ? (
          <Button asChild variant="primary" className="mt-6"><Link to="/admin/platform">Platform settings</Link></Button>
        ) : originLocked && globalAdmin ? (
          <Callout tone="info" className="mt-6">This site's staff session is pinned to its makerspace. To manage the platform or other makerspaces, sign in through the operator-configured shared portal.</Callout>
        ) : null}
        <div className="mt-8">
          <MakerspaceChoices makerspaces={makerspaces} loading={loading} error={error} onRetry={onRetry} onSelect={onSelect} />
        </div>
      </main>
    </div>
  );
}

import { ChevronRight } from "lucide-react";

import { SkipLink } from "../../components/SkipLink";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Button, Callout, Chip, Loader, PageHeader } from "../../components/ui";
import type { Makerspace } from "./StaffPanels";

/**
 * Superadmin entry screen: the superadmin operates one makerspace at a time, so
 * before the console loads they explicitly pick which makerspace to operate. The
 * chosen id then scopes every staff API call (the backend already takes a
 * makerspace_id per request). Reachable again via "Switch makerspace" in the shell.
 */
export function MakerspacePicker({
  makerspaces,
  loading,
  username,
  onSelect,
  onSignOut,
}: {
  makerspaces: Makerspace[];
  loading: boolean;
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
          kicker="Super Admin"
          title="Choose a makerspace to operate"
          description={`Signed in as ${username}. Pick a makerspace to manage its operations.`}
        />
        <div className="mt-8">
          {loading ? (
            <div className="flex justify-center py-10"><Loader label="Loading makerspaces" /></div>
          ) : !makerspaces.length ? (
            <Callout tone="warning">No makerspaces exist yet. Create one from the Django control plane.</Callout>
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2">
              {makerspaces.map((makerspace) => (
                <li key={makerspace.id} className="min-w-0">
                  <button
                    type="button"
                    onClick={() => onSelect(makerspace.id)}
                    className="group flex h-full w-full min-w-0 items-center gap-3 rounded-lg border border-line bg-canvas p-4 text-left transition-colors duration-180 ease-standard hover:bg-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                  >
                    <span className="flex min-w-0 flex-1 flex-col gap-1">
                      <span className="max-w-full break-all font-mono text-caption text-ink-muted">
                        {makerspace.public_code ?? makerspace.slug}
                      </span>
                      <span className="max-w-full break-words text-title text-ink">{makerspace.name}</span>
                      {makerspace.superadmin_access_enabled === false ? (
                        <span className="mt-1">
                          <Chip size="sm" tone="warning">Superadmin access: Off</Chip>
                        </span>
                      ) : null}
                      <span className="sr-only">Operate this makerspace</span>
                    </span>
                    <ChevronRight aria-hidden="true" className="size-5 shrink-0 text-ink-muted transition-transform duration-180 ease-standard group-hover:translate-x-0.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  );
}

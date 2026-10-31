import { Link } from "react-router-dom";

import { SkipLink } from "../../components/SkipLink";
import { SpaceWorksBadge } from "../../components/SpaceWorksLogo";
import { ThemeToggle } from "../../components/ThemeToggle";
import { Button, PageHeader, SectionHeading } from "../../components/ui";
import type { StaffAuthUser } from "../../lib/api";
import { documentTitle, useDocumentTitle } from "../../lib/useDocumentTitle";
import { MakerspaceChoices, type MakerspaceChoicesProps } from "./MakerspaceChoices";
import { PlatformSettingsPanels } from "./PlatformSettingsPanels";

export function StaffPlatformPage({ user, onSignOut, ...choices }: MakerspaceChoicesProps & {
  user: StaffAuthUser;
  onSignOut: () => void;
}) {
  useDocumentTitle(documentTitle("Platform settings"));
  return (
    <div className="flex min-h-dvh flex-col bg-subtle text-ink">
      <SkipLink />
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-6">
        <SpaceWorksBadge />
        <div className="flex items-center gap-2">
          <Button asChild variant="secondary" size="sm"><Link to="/admin">Makerspaces</Link></Button>
          <ThemeToggle />
          <Button variant="secondary" size="sm" onClick={onSignOut}>Sign out</Button>
        </div>
      </header>
      <main id="main-content" tabIndex={-1} className="mx-auto grid w-full max-w-5xl gap-8 px-4 pb-12 pt-6 sm:px-6">
        <PageHeader kicker="Super Admin" title="Platform settings" description={`Signed in as ${user.username}. Manage shared settings without selecting a makerspace.`} />
        <section aria-labelledby="platform-makerspaces" className="grid gap-4">
          <SectionHeading title={<span id="platform-makerspaces">Makerspaces</span>} description="Choose a makerspace to open its staff console." />
          <MakerspaceChoices {...choices} />
        </section>
        <PlatformSettingsPanels user={user} />
      </main>
    </div>
  );
}
